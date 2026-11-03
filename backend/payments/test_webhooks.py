"""PayPal webhooks: only verified events count, each is applied once, and they never double-count money."""

from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.testing import Fixtures
from mandates import services
from mandates.models import Funding, LedgerEntry, Request
from payments import webhooks
from payments.models import RailTransaction, WebhookEvent

from agent.tests.helpers import submit

SIGNED = {"HTTP_PAYPAL_AUTH_ALGO": "SHA256withRSA", "HTTP_PAYPAL_CERT_URL": "https://api.paypal.com/cert",
          "HTTP_PAYPAL_TRANSMISSION_ID": "t-1", "HTTP_PAYPAL_TRANSMISSION_SIG": "sig",
          "HTTP_PAYPAL_TRANSMISSION_TIME": "2026-11-03T10:00:00Z"}


def paypal(verified=True):
    client = mock.Mock()
    client.request.return_value = {"verification_status": "SUCCESS" if verified else "FAILURE"}
    return mock.patch("payments.webhooks.get_client", return_value=client), client


@override_settings(PAYPAL_WEBHOOK_ID="WH-1")
class WebhookTests(TestCase):
    def setUp(self):
        self.f = Fixtures()
        self.client = APIClient()

    def post(self, event, verified=True, headers=SIGNED):
        patcher, client = paypal(verified)
        with patcher:
            response = self.client.post("/api/webhooks/paypal/", event, format="json", **headers)
        return response, client

    def funding(self):
        mandate = self.f.support_mandate(fund=None)
        funding = services.create_funding(mandate, self.f.owner, Decimal("25"))
        funding.paypal_order_id = "ORDER-9"
        funding.save()
        return funding

    def capture_event(self, funding, value="25.00", event_id="WH-EVT-1"):
        return {"id": event_id, "event_type": "PAYMENT.CAPTURE.COMPLETED", "resource": {
            "id": "CAP-9", "status": "COMPLETED", "custom_id": str(funding.id),
            "amount": {"value": value, "currency_code": "USD"}}}

    def test_signature_is_verified_with_paypal(self):
        funding = self.funding()
        r, client = self.post(self.capture_event(funding))
        self.assertEqual(r.data["result"], "processed")
        body = client.request.call_args.kwargs["json"]
        self.assertEqual((body["webhook_id"], body["transmission_id"]), ("WH-1", "t-1"))

    def test_unverified_or_unsigned_events_change_nothing(self):
        funding = self.funding()
        self.assertEqual(self.post(self.capture_event(funding), verified=False)[0].status_code, 400)
        self.assertEqual(self.post(self.capture_event(funding), headers={})[0].status_code, 400)
        funding.refresh_from_db()
        self.assertEqual(funding.status, Funding.CREATED)
        self.assertFalse(WebhookEvent.objects.exists())

    def test_capture_counts_once_even_when_delivered_twice(self):
        funding = self.funding()
        self.post(self.capture_event(funding))
        r, _ = self.post(self.capture_event(funding))
        self.assertEqual(r.data["result"], "duplicate")
        funding.refresh_from_db()
        self.assertEqual((funding.status, funding.external_id), (Funding.CAPTURED, "CAP-9"))
        self.assertEqual(LedgerEntry.objects.filter(event=LedgerEntry.FUNDED, mandate=funding.mandate).count(), 1)

    def test_capture_with_the_wrong_amount_is_ignored(self):
        funding = self.funding()
        r, _ = self.post(self.capture_event(funding, value="2.00"))
        self.assertEqual(r.data["result"], "ignored")
        funding.refresh_from_db()
        self.assertEqual(funding.status, Funding.CREATED)

    def test_payout_events_settle_the_request(self):
        mandate = self.f.support_mandate()
        req = submit(self.f, mandate, "10", product="bundles")
        tx = req.rail_transactions.get()
        event = {"id": "WH-EVT-2", "event_type": "PAYMENT.PAYOUTS-ITEM.SUCCEEDED",
                 "resource": {"payout_batch_id": tx.external_id, "transaction_status": "SUCCESS"}}
        self.assertEqual(self.post(event)[0].data["result"], "processed")
        req.refresh_from_db()
        tx.refresh_from_db()
        self.assertEqual((req.status, tx.status), (Request.PAID, RailTransaction.SUCCESS))
        self.assertEqual(tx.last_mile_status, RailTransaction.DELIVERING)  # last mile starts on payout success

    def test_returned_payout_marks_the_request_failed(self):
        mandate = self.f.support_mandate()
        req = submit(self.f, mandate, "10", product="bundles")
        tx = req.rail_transactions.get()
        event = {"id": "WH-EVT-3", "event_type": "PAYMENT.PAYOUTS-ITEM.RETURNED",
                 "resource": {"payout_batch_id": tx.external_id, "transaction_status": "RETURNED"}}
        self.post(event)
        req.refresh_from_db()
        self.assertEqual(req.status, Request.FAILED)

    def test_unknown_events_are_stored_and_ignored(self):
        r, _ = self.post({"id": "WH-EVT-4", "event_type": "CHECKOUT.ORDER.APPROVED", "resource": {}})
        self.assertEqual(r.data["result"], "ignored")
        self.assertEqual(WebhookEvent.objects.get().event_type, "CHECKOUT.ORDER.APPROVED")

    @override_settings(PAYPAL_WEBHOOK_ID="")
    def test_webhook_id_is_found_from_paypal_when_not_configured(self):
        webhooks._webhook_id = None
        client = mock.Mock()
        client.request.return_value = {"webhooks": [{"id": "WH-FOUND", "url": "https://x.example/api/webhooks/paypal/"}]}
        self.assertEqual(webhooks.webhook_id(client), "WH-FOUND")
        webhooks._webhook_id = None
