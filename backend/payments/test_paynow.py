"""Local contributions through Paynow test mode, with Paynow's HTTP replies faked."""

from decimal import Decimal
from unittest import mock
from urllib.parse import urlencode

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.testing import Fixtures
from mandates import services
from mandates.models import Funding, LedgerEntry, Mandate
from payments.rails import paynow_inbound

KEY = "test-key"
PAYNOW = dict(PAYNOW_INTEGRATION_ID="1201", PAYNOW_INTEGRATION_KEY=KEY, PAYNOW_AUTH_EMAIL="merchant@example.com",
              PAYNOW_RESULT_URL="https://app.example/api/webhooks/paynow/", PAYNOW_RETURN_URL="https://app.example/")


def signed(**fields):
    pairs = list(fields.items())
    return urlencode(pairs + [("hash", paynow_inbound.make_hash(pairs, KEY))])


class FakeSession:
    def __init__(self, *bodies):
        self.bodies = list(bodies)
        self.posts = []

    def post(self, url, data=None, timeout=None):
        self.posts.append((url, data))
        return mock.Mock(status_code=200, text=self.bodies.pop(0))


@override_settings(**PAYNOW)
class PaynowTests(TestCase):
    def setUp(self):
        self.f = Fixtures()
        self.pool = self.f.mandate(Mandate.ISILILO, [
            {"kind": "allowed_payees", "params": {"payee_ids": [str(self.f.supplier.id)]}},
            {"kind": "requires_invoice", "params": {}}], fund=Decimal("100"))

    def start(self, session, amount="20", phone="0771111111"):
        return paynow_inbound.start_contribution(mandate=self.pool, amount=amount, name="Aunt Local", phone=phone,
                                                 session=session)

    def test_hash_matches_paynow_rule(self):
        pairs = [("id", "1201"), ("amount", "20.00")]
        import hashlib
        self.assertEqual(paynow_inbound.make_hash(pairs, KEY),
                         hashlib.sha512(b"120120.00test-key").hexdigest().upper())

    def test_paid_contribution_is_captured_once_and_named_in_ledger(self):
        session = FakeSession(signed(status="Ok", pollurl="https://paynow.example/poll/1", paynowreference="987"),
                              signed(reference="x", paynowreference="987", amount="20.00", status="Paid",
                                     pollurl="https://paynow.example/poll/1"))
        funding, _ = self.start(session)
        sent = dict(session.posts[0][1])
        self.assertEqual(sent["phone"], "0771111111")
        self.assertEqual(sent["reference"], f"hukama-{funding.id}")
        self.assertEqual(sent["hash"], paynow_inbound.make_hash(session.posts[0][1][:-1], KEY))
        self.assertEqual(funding.status, Funding.CREATED)

        funding = paynow_inbound.check_contribution(funding, session=session)
        self.assertEqual(funding.status, Funding.CAPTURED)
        self.assertEqual(services.captured_total(self.pool), Decimal("120"))
        entry = LedgerEntry.objects.filter(event=LedgerEntry.FUNDED).latest("created_at")
        self.assertEqual(entry.actor, "Local: Aunt Local")
        self.assertEqual(paynow_inbound.check_contribution(funding, session=FakeSession()).status, Funding.CAPTURED)

    def test_cancelled_on_phone_fails_without_funding(self):
        session = FakeSession(signed(status="Ok", pollurl="https://paynow.example/poll/2"),
                              signed(reference="x", amount="20.00", status="Cancelled", pollurl="p"))
        funding, _ = self.start(session, phone="0773333333")
        funding = paynow_inbound.check_contribution(funding, session=session)
        self.assertEqual(funding.status, Funding.FAILED)
        self.assertEqual(services.captured_total(self.pool), Decimal("100"))

    def test_paynow_error_is_readable_and_records_failure(self):
        with self.assertRaisesMessage(services.ServiceError, "Insufficient balance"):
            self.start(FakeSession(urlencode({"status": "Error", "error": "Insufficient balance"})))
        self.assertEqual(Funding.objects.get(rail=Funding.PAYNOW_INBOUND).status, Funding.FAILED)

    def test_tampered_reply_is_rejected(self):
        body = signed(status="Ok", pollurl="https://paynow.example/poll/3").replace("poll%2F3", "poll%2F4")
        with self.assertRaises(services.ServiceError):
            self.start(FakeSession(body))

    def test_result_callback_captures_and_rejects_forgeries(self):
        funding, _ = self.start(FakeSession(signed(status="Ok", pollurl="https://paynow.example/poll/5")))
        client = APIClient()
        forged = urlencode({"reference": f"hukama-{funding.id}", "amount": "20.00", "status": "Paid", "hash": "BAD"})
        self.assertEqual(client.post("/api/webhooks/paynow/", forged,
                                     content_type="application/x-www-form-urlencoded").status_code, 400)
        good = signed(reference=f"hukama-{funding.id}", paynowreference="555", amount="20.00", status="Paid",
                      pollurl="p")
        self.assertEqual(client.post("/api/webhooks/paynow/", good,
                                     content_type="application/x-www-form-urlencoded").status_code, 200)
        funding.refresh_from_db()
        self.assertEqual(funding.status, Funding.CAPTURED)

    def test_wrong_amount_is_not_captured(self):
        funding, _ = self.start(FakeSession(signed(status="Ok", pollurl="p")))
        with self.assertRaises(paynow_inbound.PaynowError):
            paynow_inbound.apply_status(funding, {"status": "paid", "amount": "2.00"})

    def test_api_contribution_flow(self):
        client = APIClient()
        client.force_authenticate(self.f.owner)
        session = FakeSession(signed(status="Ok", pollurl="https://paynow.example/poll/6", instructions="Dial *151#"))
        with mock.patch("payments.rails.paynow_inbound.requests", session):
            r = client.post(f"/api/mandates/{self.pool.id}/contribute/local/",
                            {"name": "Aunt Local", "phone": "0771111111", "amount": "15"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["rail_label"], "Local mobile money (test mode)")
        self.assertEqual(r.data["instructions"], "Dial *151#")
        listed = client.get(f"/api/mandates/{self.pool.id}/fundings/").data
        self.assertEqual(listed[0]["contributor_name"], "Aunt Local")

    @override_settings(PAYNOW_INTEGRATION_ID="")
    def test_not_configured_is_a_clear_refusal(self):
        with self.assertRaisesMessage(services.ServiceError, "not switched on"):
            self.start(FakeSession())
