"""Monthly premiums through PayPal Subscriptions, with the SDK's subscriptions controller and REST faked."""

from decimal import Decimal
from types import SimpleNamespace as NS
from unittest import mock

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.testing import Fixtures
from mandates import services
from mandates.models import Funding, Mandate, Payee, Request
from payments import premiums
from payments.models import PayPalPlan, PremiumSubscription

from agent.tests.fakes import fake_rails

PAYPAL = dict(PAYPAL_CLIENT_ID="client-id", PAYPAL_CLIENT_SECRET="secret", PAYPAL_WEBHOOK_ID="WH-1",
              PAYPAL_BASE_URL="https://api-m.sandbox.paypal.com")


def ok(body):
    return NS(is_success=lambda: True, body=body)


class FakeSubscriptions:
    def __init__(self):
        self.calls = []
        self.transactions = []

    def create_billing_plan(self, request):
        self.calls.append(("plan", request))
        return ok(NS(id="P-1", name=request["body"].name))

    def create_subscription(self, request):
        self.calls.append(("subscription", request))
        return ok(NS(id="I-SUB1", links=[NS(rel="self", href="x"), NS(rel="approve", href="https://paypal/approve")]))

    def list_subscription_transactions(self, request):
        self.calls.append(("transactions", request))
        return ok(NS(transactions=self.transactions))

    def cancel_subscription(self, request):
        self.calls.append(("cancel", request))
        return ok(None)


def txn(txn_id, value="18.00", status="COMPLETED"):
    return NS(id=txn_id, status=status, amount_with_breakdown=NS(gross_amount=NS(value=value)))


@override_settings(**PAYPAL)
class PremiumTests(TestCase):
    def setUp(self):
        self.f = Fixtures()
        patcher, self.for_payee = fake_rails()
        self.addCleanup(patcher.stop)
        self.provider = Payee.objects.create(family=self.f.family, name="Test Cover", kind=Payee.FUNERAL_PROVIDER,
                                             rail=Payee.BILLER_SIM, external_ref="POL-1", verified=True)
        self.cover = self.f.mandate(Mandate.VIKELA, [
            {"kind": "allowed_payees", "params": {"payee_ids": [str(self.provider.id)]}},
            {"kind": "max_per_request", "params": {"amount": 18}}], fund=None)
        self.subs = FakeSubscriptions()
        self.rest = mock.Mock()
        self.rest.request.side_effect = self.rest_request
        self.rest_status = "ACTIVE"

    def rest_request(self, method, path, json=None, headers=None):
        if path == "/v1/catalogs/products":
            return {"id": "PROD-1"}
        if path.startswith("/v1/billing/subscriptions/"):
            return {"id": "I-SUB1", "status": self.rest_status}
        return {"verification_status": "SUCCESS"}

    def start(self, user=None):
        return premiums.start(self.cover, user or self.f.owner, "https://app.example/", self.subs, self.rest)

    def test_premium_is_the_mandates_per_payment_limit_and_only_for_cover(self):
        self.assertEqual(premiums.premium_for(self.cover), Decimal("18.00"))
        self.assertIsNone(premiums.premium_for(self.f.support_mandate()))

    def test_start_creates_product_and_plan_once_and_a_subscription(self):
        premium, approve = self.start()
        self.assertEqual(approve, "https://paypal/approve")
        self.assertEqual((premium.paypal_subscription_id, premium.status), ("I-SUB1", PremiumSubscription.APPROVAL_PENDING))
        body = [r for k, r in self.subs.calls if k == "subscription"][0]["body"]
        self.assertEqual((body.plan_id, body.custom_id), ("P-1", str(premium.id)))
        self.assertEqual(body.application_context.return_url,
                         f"https://app.example/paypal/premium-return/?premium={premium.id}")
        plan = [r for k, r in self.subs.calls if k == "plan"][0]["body"]
        self.assertEqual((plan.product_id, plan.billing_cycles[0].pricing_scheme.fixed_price.value), ("PROD-1", "18.00"))
        premiums.start(self.cover, self.f.funders[1], "https://app.example/", self.subs, self.rest)
        self.assertEqual(PayPalPlan.objects.count(), 1)  # reused for the same price
        self.assertEqual(len([k for k, _ in self.subs.calls if k == "plan"]), 1)

    def test_only_funders_and_one_active_premium(self):
        with self.assertRaisesMessage(services.ServiceError, "funders"):
            self.start(Fixtures(prefix="x-").owner)
        premium, _ = self.start()
        premiums.set_status(premium, "ACTIVE")
        with self.assertRaisesMessage(services.ServiceError, "already active"):
            self.start()

    def test_each_payment_funds_once_and_pays_the_provider_through_the_rules(self):
        premium, _ = self.start()
        req = premiums.record_payment(premium, "SALE-1", "18.00")
        self.assertEqual((req.status, req.payee, req.channel, req.product),
                         (Request.APPROVED, self.provider, Request.SCHEDULE, "premium"))
        self.assertEqual(Funding.objects.get(external_id="SALE-1").status, Funding.CAPTURED)
        premium.refresh_from_db()
        self.assertEqual(premium.status, PremiumSubscription.ACTIVE)  # a payment proves it is active
        self.assertIsNone(premiums.record_payment(premium, "SALE-1", "18.00"))  # same transaction again
        self.assertIsNone(premiums.record_payment(premium, "SALE-2", "50.00"))  # not the premium
        self.assertEqual(Funding.objects.filter(mandate=self.cover).count(), 1)
        self.assertEqual(self.for_payee.return_value.pay.call_count, 1)

    def test_sync_reads_status_and_records_completed_payments(self):
        premium, _ = self.start()
        self.subs.transactions = [txn("SALE-9"), txn("SALE-10", status="PENDING")]
        premiums.sync(premium, self.subs, self.rest)
        premium.refresh_from_db()
        self.assertEqual(premium.status, PremiumSubscription.ACTIVE)
        self.assertEqual(list(Funding.objects.filter(mandate=self.cover).values_list("external_id", flat=True)),
                         ["SALE-9"])

    def test_cancel(self):
        premium, _ = self.start()
        premiums.set_status(premium, "ACTIVE")
        with self.assertRaises(services.ServiceError):
            premiums.cancel(premium, Fixtures(prefix="y-").owner, self.subs)
        premium = premiums.cancel(premium, self.f.owner, self.subs)
        self.assertEqual(premium.status, PremiumSubscription.CANCELLED)
        self.assertEqual([r["id"] for k, r in self.subs.calls if k == "cancel"], ["I-SUB1"])

    def test_webhooks_record_payments_and_status(self):
        premium, _ = self.start()
        client = APIClient()
        headers = {"HTTP_PAYPAL_AUTH_ALGO": "a", "HTTP_PAYPAL_CERT_URL": "c", "HTTP_PAYPAL_TRANSMISSION_ID": "t",
                   "HTTP_PAYPAL_TRANSMISSION_SIG": "s", "HTTP_PAYPAL_TRANSMISSION_TIME": "now"}
        with mock.patch("payments.webhooks.get_client", return_value=self.rest):
            client.post("/api/webhooks/paypal/", {"id": "E1", "event_type": "PAYMENT.SALE.COMPLETED", "resource": {
                "id": "SALE-7", "billing_agreement_id": "I-SUB1", "amount": {"total": "18.00", "currency": "USD"}}},
                format="json", **headers)
            client.post("/api/webhooks/paypal/", {"id": "E2", "event_type": "BILLING.SUBSCRIPTION.CANCELLED",
                                                  "resource": {"id": "I-SUB1", "status": "CANCELLED"}},
                        format="json", **headers)
        premium.refresh_from_db()
        self.assertEqual(premium.status, PremiumSubscription.CANCELLED)
        self.assertTrue(Funding.objects.filter(external_id="SALE-7", status=Funding.CAPTURED).exists())

    def test_paypal_return_continues_in_the_app(self):
        premium, _ = self.start()
        r = self.client.get(f"/paypal/premium-return/?premium={premium.id}&subscription_id=I-SUB1&ba_token=x")
        self.assertEqual(r["Location"], f"/#/mandates/{self.cover.id}?premium={premium.id}")
        self.assertEqual(self.client.get("/paypal/premium-return/?premium=nope")["Location"], "/")

    def test_api(self):
        api = APIClient()
        api.force_authenticate(self.f.owner)
        with mock.patch("payments.premiums.sdk", return_value=NS(subscriptions=self.subs)), \
                mock.patch("payments.premiums.get_client", return_value=self.rest):
            r = api.post(f"/api/mandates/{self.cover.id}/premium/start/")
            self.assertEqual((r.status_code, r.data["approve_url"]), (201, "https://paypal/approve"))
            self.subs.transactions = [txn("SALE-3")]
            self.assertEqual(api.post(f"/api/premiums/{r.data['id']}/sync/").data["status"], "ACTIVE")
        info = api.get(f"/api/mandates/{self.cover.id}/premium/").data
        self.assertEqual((info["amount"], info["subscriptions"][0]["status"]), ("18.00", "ACTIVE"))
