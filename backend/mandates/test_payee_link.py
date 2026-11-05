"""Payee upload links: a school or builder with no account sends invoices, quotes and photos through a
private link. Whatever arrives can only ever pay that payee, and the fraud checks and rules decide."""

from decimal import Decimal
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from agent.tests.helpers import fake_pay, quiet_ai
from core.testing import Fixtures
from mandates import services
from mandates.models import Approval, Evidence, Mandate, PayeeLink, Request

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def invoice_reader(total, supplier):
    def read(evidence):
        evidence.extracted = {"total": total, "supplier": supplier, "items": []}
        evidence.save(update_fields=["extracted", "updated_at"])
    return read


class PayeeLinkTests(TestCase):
    def setUp(self):
        self.f = Fixtures()
        self.school = self.f.mandate(Mandate.IMFUNDO, [
            {"kind": "allowed_payees", "params": {"payee_ids": [str(self.f.school.id)]}},
            {"kind": "requires_invoice", "params": {}},
        ])
        self.link = services.set_payee_link(self.f.family, self.f.school, self.f.funders[1], enabled=True)
        self.api = APIClient(enforce_csrf_checks=True)

    def send(self, total="340.00", supplier="Test School", **data):
        data = {"kind": "INVOICE", "mandate": str(self.school.id), "amount": "340", **data}
        data["file"] = SimpleUploadedFile("invoice.png", PNG, content_type="image/png")
        with mock.patch("mandates.services._extract", invoice_reader(total, supplier)), \
                mock.patch("mandates.services._intent_analyzer", return_value=quiet_ai), \
                mock.patch("payments.rails.for_payee") as for_payee:
            for_payee.return_value.pay.side_effect = fake_pay
            return self.api.post(f"/api/public/payee/{self.link.token}/send/", data, format="multipart")

    def test_the_payees_invoice_is_checked_and_paid_to_the_payee(self):
        r = self.send()
        self.assertEqual(r.status_code, 201, r.data)
        req = Request.objects.get(pk=r.data["id"])
        self.assertEqual((req.status, req.payee, req.channel, req.product),
                         (Request.APPROVED, self.f.school, Request.LINK, "school_fees"))
        self.assertEqual(r.data["status"], "Approved, payment on its way")
        self.assertEqual(req.evidence.get().kind, Evidence.INVOICE)

    def test_a_wrong_invoice_is_refused_with_what_to_fix(self):
        r = self.send(total="300.00")
        self.assertEqual(r.data["state"], Request.REFUSED)
        self.assertTrue(any("does not match" in x for x in r.data["to_fix"]))

    def test_a_link_can_only_reach_mandates_that_pay_this_payee(self):
        support = self.f.support_mandate()
        r = self.send(mandate=str(support.id))
        self.assertEqual(r.status_code, 400)
        self.assertFalse(support.requests.exists())

    def test_a_link_can_add_a_file_to_its_own_open_request_only(self):
        refused = Request.objects.get(pk=self.send(total="300.00").data["id"])
        r = self.send(request=str(refused.id))  # the corrected invoice
        self.assertEqual(r.data["state"], Request.APPROVED)
        other = Request.objects.create(mandate=self.school, amount=Decimal("5"), payee=self.f.supplier,
                                       idempotency_key="other", status=Request.REFUSED)
        self.assertEqual(self.send(request=str(other.id)).status_code, 400)

    def test_a_rejected_request_cannot_be_revived_through_the_link(self):
        req = Request.objects.get(pk=self.send(total="300.00").data["id"])
        Approval.objects.create(request=req, user=self.f.owner, action=Approval.REJECT)
        self.assertEqual(self.send(request=str(req.id)).status_code, 400)
        self.assertEqual(req.evidence.count(), 1)  # the new file was not even stored

    def test_turned_off_or_unknown_links_do_nothing(self):
        services.set_payee_link(self.f.family, self.f.school, self.f.owner, enabled=False)
        self.assertEqual(self.api.get(f"/api/public/payee/{self.link.token}/").status_code, 404)
        self.assertEqual(self.send().status_code, 404)
        self.assertEqual(self.api.get("/api/public/payee/nope/").status_code, 404)

    def test_getting_the_link_again_keeps_it_and_new_replaces_it(self):
        again = services.set_payee_link(self.f.family, self.f.school, self.f.owner, enabled=True)
        self.assertEqual(again.token, self.link.token)
        fresh = services.set_payee_link(self.f.family, self.f.school, self.f.owner, enabled=True, new=True)
        self.assertNotEqual(fresh.token, self.link.token)
        self.assertEqual(PayeeLink.objects.filter(payee=self.f.school, active=True).count(), 1)

    def test_only_funders_make_links_and_only_for_payees_a_mandate_can_pay(self):
        from accounts.models import Membership
        viewer = self.f.funders[2]
        Membership.objects.filter(user=viewer).update(role=Membership.VIEWER)
        with self.assertRaises(services.ServiceError):
            services.set_payee_link(self.f.family, self.f.school, viewer, enabled=True)
        with self.assertRaises(services.ServiceError):  # no mandate pays the supplier
            services.set_payee_link(self.f.family, self.f.supplier, self.f.owner, enabled=True)

    def test_public_page_shows_what_to_send_and_never_fraud_details(self):
        self.send(total="300.00")
        data = self.api.get(f"/api/public/payee/{self.link.token}/").data
        self.assertEqual(data["payee"], "Test School")
        self.assertIn("Your invoice, for exactly the amount you ask for", data["mandates"][0]["needs"])
        self.assertNotIn("risk", str(data).lower())
        self.assertNotIn("balance", data["mandates"][0])

    def test_uploads_per_link_are_limited(self):
        with mock.patch("mandates.services.LINK_UPLOADS_PER_DAY", 1):
            self.assertEqual(self.send().status_code, 201)
            self.assertEqual(self.send(idempotency_key="b").status_code, 400)

    def test_the_same_form_sent_twice_makes_one_request(self):
        self.send(idempotency_key="k1")
        self.send(idempotency_key="k1")
        self.assertEqual(self.school.requests.count(), 1)

    def test_funders_see_and_manage_the_link_in_the_api(self):
        self.api.force_authenticate(self.f.owner)
        payees = {p["id"]: p for p in self.api.get("/api/payees/").data}
        self.assertEqual(payees[str(self.f.school.id)]["upload_link"], self.link.token)
        self.assertIsNone(payees[str(self.f.supplier.id)]["upload_link"])
