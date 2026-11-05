"""Money-flow loopholes closed in the 5 Nov audit: refunds, out-of-order payout events, lost webhooks,
double-counted premiums and sub-dollar checkouts."""

from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings

from agent.tests.helpers import fake_pay, submit
from core.testing import Fixtures
from mandates import services
from mandates.models import LedgerEntry, Request
from payments import checkout, premiums, webhooks
from payments.models import PayPalPlan, PremiumSubscription, RailTransaction, WebhookEvent
from payments.payouts import apply_rail_status
from payments.rails.paypal import PayPalPayoutRail

VERIFIED = mock.patch("payments.webhooks.verify", return_value=True)


@override_settings(PAYPAL_WEBHOOK_ID="WH-1")
class RefundTests(TestCase):
    def setUp(self):
        self.f = Fixtures()
        self.mandate = self.f.support_mandate(fund=None)
        funding = services.create_funding(self.mandate, self.f.owner, Decimal("100"))
        self.funding = services.mark_funding_captured(funding, external_id="CAP-1")

    def event(self, kind, resource, event_id):
        with VERIFIED:
            return webhooks.receive({}, {"id": event_id, "event_type": kind, "resource": resource})

    def test_a_refund_takes_the_money_out_of_the_mandate_once(self):
        refund = {"id": "REF-1", "amount": {"value": "40.00", "currency_code": "USD"},
                  "seller_payable_breakdown": {"total_refunded_amount": {"value": "40.00"}},
                  "links": [{"rel": "up", "href": "https://api-m.paypal.com/v2/payments/captures/CAP-1"}]}
        self.assertEqual(self.event("PAYMENT.CAPTURE.REFUNDED", refund, "E1"), "processed")
        self.event("PAYMENT.CAPTURE.REFUNDED", refund, "E2")  # same refund, new event id
        self.assertEqual(services.mandate_balance(self.mandate), Decimal("60"))
        self.assertEqual(LedgerEntry.objects.filter(event=LedgerEntry.REFUNDED).count(), 1)

    def test_a_chargeback_removes_the_whole_funding_and_blocks_spending_it(self):
        reversed_ = {"id": "CAP-1", "status": "REVERSED", "custom_id": str(self.funding.id),
                     "amount": {"value": "100.00", "currency_code": "USD"}}
        self.event("PAYMENT.CAPTURE.REVERSED", reversed_, "E3")
        self.assertEqual(services.mandate_balance(self.mandate), Decimal("0"))
        req = submit(self.f, self.mandate, 5, product="airtime")
        self.assertEqual(req.status, Request.REFUSED)
        self.assertIn("Insufficient", req.latest_decision.reason)

    def test_a_failure_while_applying_keeps_the_event_retryable(self):
        resource = {"id": "CAP-1", "custom_id": str(self.funding.id), "amount": {"value": "100.00"}}
        with mock.patch("payments.webhooks.apply", side_effect=RuntimeError("db down")), \
                self.assertRaises(RuntimeError):
            self.event("PAYMENT.CAPTURE.REVERSED", resource, "E4")
        self.assertFalse(WebhookEvent.objects.filter(paypal_event_id="E4").exists())
        self.assertEqual(self.event("PAYMENT.CAPTURE.REVERSED", resource, "E4"), "processed")  # PayPal retry
        self.assertEqual(services.mandate_balance(self.mandate), Decimal("0"))


class PayoutOrderTests(TestCase):
    def setUp(self):
        self.f = Fixtures()
        self.req = submit(self.f, self.f.support_mandate(), 5, product="airtime")
        self.tx = self.req.rail_transactions.get()

    def test_a_late_batch_success_cannot_undo_a_returned_item(self):
        apply_rail_status(self.tx, RailTransaction.RETURNED)
        apply_rail_status(self.tx, RailTransaction.SUCCESS)
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.status, RailTransaction.RETURNED)
        self.assertEqual(Request.objects.get(pk=self.req.pk).status, Request.FAILED)

    def test_polling_reads_the_item_not_just_the_batch(self):
        rail = PayPalPayoutRail(client=mock.Mock())
        for item, expected in (("SUCCESS", "succeeded"), ("UNCLAIMED", "pending"), ("RETURNED", "failed")):
            data = {"batch_header": {"payout_batch_id": "B1", "batch_status": "SUCCESS"},
                    "items": [{"transaction_status": item}]}
            with self.subTest(item=item):
                self.assertEqual(rail._result(data, "ref").status, expected)


class PremiumAndCheckoutTests(TestCase):
    def setUp(self):
        self.f = Fixtures()

    def test_the_same_premium_payment_is_counted_once(self):
        cover = self.f.mandate("VIKELA", [
            {"kind": "allowed_payees", "params": {"payee_ids": [str(self.f.school.id)]}},
            {"kind": "max_per_request", "params": {"amount": 18}},
        ], fund=None)
        plan = PayPalPlan.objects.create(name="p", product_id="PROD", plan_id="P-1", amount=Decimal("18"))
        premium = PremiumSubscription.objects.create(mandate=cover, funder=self.f.owner, plan=plan,
                                                     amount=Decimal("18"), status=PremiumSubscription.ACTIVE)
        with mock.patch("payments.rails.for_payee") as for_payee:
            for_payee.return_value.pay.side_effect = fake_pay
            premiums.record_payment(premium, "SALE-1", "18.00")
            self.assertIsNone(premiums.record_payment(premium, "SALE-1", "18.00"))
        self.assertEqual(cover.fundings.count(), 1)

    def test_checkout_minimum_is_one_dollar(self):
        with self.assertRaises(services.ServiceError):
            checkout.validate_amount("0.50")
        self.assertEqual(checkout.validate_amount("1"), Decimal("1.00"))
