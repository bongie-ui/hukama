"""PayPal checkout (Orders v2 via the PayPal Server SDK) with the SDK's orders controller faked."""

from decimal import Decimal
from types import SimpleNamespace as NS
from unittest import mock

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.testing import Fixtures
from mandates import services
from mandates.models import Funding, LedgerEntry, Mandate
from payments import checkout

PAYPAL = dict(PAYPAL_CLIENT_ID="client-id", PAYPAL_CLIENT_SECRET="secret",
              PAYPAL_BASE_URL="https://api-m.sandbox.paypal.com")


def ok(body):
    return NS(is_success=lambda: True, body=body)


def captured(funding_id, value, status="COMPLETED", currency="USD", capture_id="CAP-1"):
    capture = NS(id=capture_id, status=status, custom_id=str(funding_id),
                 amount=NS(currency_code=currency, value=value))
    return NS(id="ORDER-1", status="COMPLETED", purchase_units=[NS(payments=NS(captures=[capture]))])


class FakeOrders:
    """Records calls; capture returns whatever the test sets."""

    def __init__(self):
        self.calls = []
        self.capture_body = None
        self.capture_error = None
        self.order_body = None

    def create_order(self, request):
        self.calls.append(("create", request))
        return ok(NS(id="ORDER-1", status="CREATED"))

    def capture_order(self, request):
        self.calls.append(("capture", request))
        if self.capture_error:
            raise self.capture_error
        return ok(self.capture_body)

    def get_order(self, request):
        self.calls.append(("get", request))
        return ok(self.order_body)


@override_settings(**PAYPAL)
class CheckoutTests(TestCase):
    def setUp(self):
        self.f = Fixtures()
        self.mandate = self.f.support_mandate(fund=None)
        self.orders = FakeOrders()

    def start(self, amount="25.00", **kw):
        return checkout.start(self.mandate, amount, funder=kw.pop("funder", self.f.owner), orders=self.orders, **kw)

    def test_order_carries_our_funding_id_amount_and_an_idempotency_key(self):
        funding = self.start()
        _, request = self.orders.calls[0]
        unit = request["body"].purchase_units[0]
        self.assertEqual((unit.custom_id, unit.amount.value, unit.amount.currency_code),
                         (str(funding.id), "25.00", "USD"))
        self.assertEqual(request["paypal_request_id"], f"hukama-order-{funding.id}")
        self.assertEqual((funding.status, funding.paypal_order_id), (Funding.CREATED, "ORDER-1"))

    def test_capture_counts_the_money_once(self):
        funding = self.start()
        self.orders.capture_body = captured(funding.id, "25.00")
        funding = checkout.finish(funding, orders=self.orders)
        self.assertEqual((funding.status, funding.external_id), (Funding.CAPTURED, "CAP-1"))
        self.assertEqual(services.captured_total(self.mandate), Decimal("25.00"))
        checkout.finish(funding, orders=self.orders)  # a retried capture does nothing
        self.assertEqual(len([c for c in self.orders.calls if c[0] == "capture"]), 1)
        self.assertEqual(LedgerEntry.objects.filter(event=LedgerEntry.FUNDED, mandate=self.mandate).count(), 1)
        self.assertEqual(self.orders.calls[1][1]["paypal_request_id"], f"hukama-capture-{funding.id}")

    def test_wrong_amount_or_someone_elses_capture_never_counts(self):
        for body in (lambda f: captured(f.id, "2.50"), lambda f: captured("another-funding", "25.00"),
                     lambda f: captured(f.id, "25.00", status="PENDING")):
            funding = self.start()
            self.orders.capture_body = body(funding)
            with self.assertRaises(checkout.CheckoutError):
                checkout.finish(funding, orders=self.orders)
            funding.refresh_from_db()
            self.assertEqual(funding.status, Funding.FAILED)
        self.assertEqual(services.captured_total(self.mandate), Decimal("0"))

    def test_already_captured_order_is_reconciled(self):
        from paypalserversdk.exceptions.error_exception import ErrorException
        funding = self.start()
        response = NS(status_code=422, text='{"name": "UNPROCESSABLE_ENTITY", "message": "already", '
                                            '"details": [{"issue": "ORDER_ALREADY_CAPTURED"}]}')
        self.orders.capture_error = ErrorException("already", response)
        self.orders.order_body = captured(funding.id, "25.00")
        self.assertEqual(checkout.finish(funding, orders=self.orders).status, Funding.CAPTURED)

    def test_paypal_refusal_is_readable_and_nothing_counts(self):
        from paypalserversdk.exceptions.error_exception import ErrorException
        funding = self.start()
        response = NS(status_code=422, text='{"message": "Instrument declined", '
                                            '"details": [{"issue": "INSTRUMENT_DECLINED"}]}')
        self.orders.capture_error = ErrorException("declined", response)
        with self.assertRaisesMessage(checkout.CheckoutError, "Instrument declined"):
            checkout.finish(funding, orders=self.orders)
        self.assertEqual(services.captured_total(self.mandate), Decimal("0"))

    def test_bad_amounts_and_strangers_are_refused_before_paypal(self):
        for amount in ("0", "-5", "abc", "5000.01"):
            with self.assertRaises(services.ServiceError):
                self.start(amount)
        stranger = Fixtures(prefix="x-").owner
        with self.assertRaisesMessage(services.ServiceError, "funders"):
            self.start(funder=stranger)
        self.assertEqual(self.orders.calls, [])

    @override_settings(PAYPAL_CLIENT_SECRET="")
    def test_not_configured(self):
        with self.assertRaises(checkout.CheckoutError):
            self.start()


@override_settings(**PAYPAL)
class CheckoutApiTests(TestCase):
    def setUp(self):
        self.f = Fixtures()
        self.pool = self.f.mandate(Mandate.ISILILO, [
            {"kind": "allowed_payees", "params": {"payee_ids": [str(self.f.supplier.id)]}},
            {"kind": "requires_invoice", "params": {}}], fund=None)
        services.set_contribution_link(self.pool, self.f.owner, enabled=True)
        self.orders = FakeOrders()
        patcher = mock.patch("payments.checkout._orders", return_value=self.orders)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_funder_adds_funds(self):
        client = APIClient()
        client.force_authenticate(self.f.owner)
        r = client.post(f"/api/mandates/{self.pool.id}/fund/create-order/", {"amount": "40"}, format="json")
        self.assertEqual((r.status_code, r.data["order_id"]), (201, "ORDER-1"))
        self.orders.capture_body = captured(r.data["funding_id"], "40.00")
        r = client.post(f"/api/mandates/{self.pool.id}/fund/capture/", {"order_id": "ORDER-1"}, format="json")
        self.assertEqual(r.data["status"], Funding.CAPTURED)
        client.force_authenticate(self.f.funders[1])  # only the funder who started it can capture it
        self.assertEqual(client.post(f"/api/mandates/{self.pool.id}/fund/capture/", {"order_id": "ORDER-1"},
                                     format="json").status_code, 404)

    def test_anyone_with_the_link_gives(self):
        token = self.pool.contribute_token
        anon = APIClient()
        self.assertEqual(anon.post(f"/api/public/pools/{token}/contribute/", {"amount": "10"},
                                   format="json").status_code, 400)  # a name is required
        r = anon.post(f"/api/public/pools/{token}/contribute/",
                      {"name": "Example Giver", "amount": "10", "message": "Thinking of you"}, format="json")
        self.assertEqual(r.status_code, 201)
        funding = Funding.objects.get(paypal_order_id="ORDER-1")
        self.assertEqual((funding.funder, funding.contributor_name, funding.message),
                         (None, "Example Giver", "Thinking of you"))
        self.orders.capture_body = captured(funding.id, "10.00")
        r = anon.post(f"/api/public/pools/{token}/capture/", {"order_id": "ORDER-1"}, format="json")
        self.assertEqual((r.data["status"], r.data["name"]), (Funding.CAPTURED, "Example G."))
        self.assertEqual(anon.get(f"/api/public/pools/{token}/").data["raised"], "10.00")

    def test_paypal_config_is_public_and_has_no_secret(self):
        r = APIClient().get("/api/config/paypal/")
        self.assertEqual(r.data["client_id"], "client-id")
        self.assertIn("sandbox.paypal.com/web-sdk/v6/core", r.data["sdk_url"])
        self.assertNotIn("secret", str(r.data))
