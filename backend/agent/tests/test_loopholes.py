"""Loopholes closed in the 5 Nov audit: each test shows a way money could leak, and that it no longer can."""

from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from core.testing import Fixtures
from mandates import services
from mandates.models import Approval, Evidence, Payee, Request

from .helpers import fake_pay, midday, submit


def risky_ai(context):
    return {"ai_risk": 70, "flags": [{"flag": "URGENCY_PRESSURE", "reason": "pressure", "quote": "now"}],
            "summary": "pressure"}


def quiet_ai(context):
    return {"ai_risk": 0, "flags": [], "summary": ""}


class UnverifiedPayeeTests(TestCase):
    def setUp(self):
        self.f = Fixtures()

    def test_a_funder_cannot_pay_their_own_new_payee(self):
        """A funder adds "a payee" with their own PayPal email and asks a shared mandate to pay it."""
        own = Payee.objects.create(family=self.f.family, name="New Shop", kind=Payee.SUPPLIER,
                                   paypal_email="me@example.com")
        mandate = self.f.mandate("ISIKHWAMA", [  # no allowed_payees rule: the template does not require one
            {"kind": "allowed_beneficiaries", "params": {"beneficiary_ids": [str(self.f.beneficiary.id)]}},
            {"kind": "allowed_products", "params": {"products": ["cash"]}},
        ])
        req = submit(self.f, mandate, 40, product="cash", payee=own, user=self.f.funders[1])
        self.assertEqual(req.status, Request.REFUSED)
        self.assertIn("not been verified", req.latest_decision.reason)
        self.assertFalse(req.rail_transactions.exists())

    def test_verified_payee_is_paid(self):
        mandate = self.f.support_mandate()
        self.assertEqual(submit(self.f, mandate, 5, product="airtime").status, Request.APPROVED)


class AmountTests(TestCase):
    def setUp(self):
        self.f = Fixtures()
        self.mandate = self.f.support_mandate()

    def test_fractions_of_a_cent_and_nonsense_are_rejected(self):
        for amount in ("0.001", "abc", "NaN", "-5", "0"):
            with self.subTest(amount=amount), self.assertRaises(services.ServiceError):
                services.submit_request(mandate=self.mandate, amount=amount, product="airtime",
                                        requester_user=self.f.owner, idempotency_key=f"amt-{amount}",
                                        beneficiary=self.f.beneficiary, payee=self.f.provider,
                                        intent_analyzer=quiet_ai, now=midday())


class ReassessTests(TestCase):
    def setUp(self):
        self.f = Fixtures()

    def _reassess(self, req, analyzer=quiet_ai):
        with mock.patch("payments.rails.for_payee") as for_payee:
            for_payee.return_value.pay.side_effect = fake_pay
            return services.reassess(req, intent_analyzer=analyzer, now=midday())

    def test_a_funders_rejection_cannot_be_undone_by_new_evidence(self):
        mandate = self.f.support_mandate()
        req = submit(self.f, mandate, 5, product="airtime", analyzer=risky_ai)
        self.assertEqual(req.status, Request.ESCALATED)
        services.apply_approval(req, self.f.funders[1], Approval.REJECT, note="No")
        with self.assertRaises(services.ServiceError):
            self._reassess(Request.objects.get(pk=req.pk))
        self.assertEqual(Request.objects.get(pk=req.pk).status, Request.REFUSED)

    def test_a_recheck_never_lowers_the_risk(self):
        """Refused for missing evidence with some risk; after the evidence arrives, the risk is still there."""
        mandate = self.f.build_mandate()
        req = submit(self.f, mandate, 420, product="materials", beneficiary=None, payee=self.f.supplier,
                     analyzer=risky_ai)
        self.assertEqual(req.status, Request.REFUSED)
        req.evidence.create(kind=Evidence.QUOTE, extracted={"total": 420, "items": [
            {"key": "cement_bag", "name": "Cement", "quantity": 40, "unit_price": 10.5}]})
        req.evidence.create(kind=Evidence.MILESTONE_PHOTO, extracted={"verdict": "matches"})
        req = self._reassess(req, analyzer=quiet_ai)  # the model happens to see no risk this time
        self.assertEqual(req.status, Request.ESCALATED)
        self.assertEqual(req.risk_assessment.score, 35)
        self.assertFalse(req.rail_transactions.exists())


class AddressChangeTests(TestCase):
    def setUp(self):
        self.f = Fixtures()

    def test_changing_the_delivery_address_is_a_fraud_signal(self):
        from agent import fraud

        b = services.change_beneficiary_address(self.f.beneficiary, "12 New Road", self.f.funders[1])
        self.assertIsNotNone(b.address_changed_at)
        mandate = self.f.support_mandate()
        req = Request(mandate=mandate, amount=Decimal("30"), beneficiary=b, product="groceries",
                      fulfilment=Request.DELIVERY)
        signals = [s["signal"] for s in fraud.deterministic_signals(req, now=timezone.now())]
        self.assertIn("BENEFICIARY_RECENTLY_CHANGED", signals)
        later = timezone.now() + timedelta(hours=73)
        self.assertNotIn("BENEFICIARY_RECENTLY_CHANGED",
                         [s["signal"] for s in fraud.deterministic_signals(req, now=later)])

    def test_unchanged_address_is_not_a_change(self):
        b = services.change_beneficiary_address(self.f.beneficiary, self.f.beneficiary.address, self.f.owner)
        self.assertIsNone(b.address_changed_at)
