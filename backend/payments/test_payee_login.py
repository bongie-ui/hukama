"""Log in with PayPal on payee upload links: only the owner of the PayPal account that would be paid can send."""

from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from agent.tests.helpers import fake_pay, quiet_ai
from core.testing import Fixtures
from mandates import services
from mandates.models import Mandate, Request
from payments import identity

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def paypal(email):
    client = mock.Mock(client_id="CLIENT", is_sandbox=True)
    client.user_token.return_value = "USER-TOKEN"
    client.user_info.return_value = {"user_id": "U1", "emails": [{"value": email, "primary": True, "confirmed": True}]}
    return mock.patch("payments.identity.get_client", return_value=client)


@override_settings(PAYEE_PAYPAL_LOGIN=True, PUBLIC_BASE_URL="https://hukama.example/")
class PayeeLoginTests(TestCase):
    def setUp(self):
        self.f = Fixtures()
        self.f.mandate(Mandate.IMFUNDO, [
            {"kind": "allowed_payees", "params": {"payee_ids": [str(self.f.school.id)]}},
            {"kind": "requires_invoice", "params": {}},
        ])
        self.link = services.set_payee_link(self.f.family, self.f.school, self.f.owner, enabled=True)
        self.api = APIClient(enforce_csrf_checks=True)

    def login(self, email):
        with paypal(email):
            start = self.api.get(f"/api/public/payee/{self.link.token}/paypal-login/")
            state = parse_qs(urlparse(start["Location"]).query)["state"][0]
            return self.api.get("/paypal/payee-login/", {"code": "CODE", "state": state})

    def send(self):
        mandate = Mandate.objects.get(type=Mandate.IMFUNDO)

        def read(evidence):
            evidence.extracted = {"total": 340, "supplier": "Test School", "items": []}
            evidence.save()
        with mock.patch("mandates.services._extract", read), \
                mock.patch("mandates.services._intent_analyzer", return_value=quiet_ai), \
                mock.patch("payments.rails.for_payee") as for_payee:
            for_payee.return_value.pay.side_effect = fake_pay
            return self.api.post(f"/api/public/payee/{self.link.token}/send/", {
                "kind": "INVOICE", "mandate": str(mandate.id), "amount": "340",
                "file": SimpleUploadedFile("i.png", PNG, content_type="image/png")}, format="multipart")

    def test_sending_needs_a_paypal_login(self):
        data = self.api.get(f"/api/public/payee/{self.link.token}/").data
        self.assertEqual((data["paypal_login"]["required"], data["paypal_login"]["verified_as"]), (True, None))
        self.assertEqual(data["requests"], [])  # no history before the login
        self.assertEqual(self.send().status_code, 403)
        self.assertFalse(Request.objects.exists())

    def test_login_goes_to_paypal_with_a_signed_state(self):
        with paypal("x@example.com"):
            r = self.api.get(f"/api/public/payee/{self.link.token}/paypal-login/")
        url = urlparse(r["Location"])
        q = parse_qs(url.query)
        self.assertEqual((url.netloc, q["client_id"][0], q["redirect_uri"][0]),
                         ("www.sandbox.paypal.com", "CLIENT", "https://hukama.example/paypal/payee-login/"))
        self.assertIn("email", q["scope"][0])

    def test_the_payees_own_paypal_account_unlocks_the_link(self):
        r = self.login("School@Example.com")  # case does not matter
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].endswith("?login=ok"))
        data = self.api.get(f"/api/public/payee/{self.link.token}/").data
        self.assertEqual(data["paypal_login"]["verified_as"], "school@example.com")
        sent = self.send()
        self.assertEqual(sent.status_code, 201, sent.data)
        self.assertEqual(Request.objects.get().details["paypal_login"], "school@example.com")

    def test_another_paypal_account_is_turned_away(self):
        r = self.login("someone.else@example.com")
        self.assertIn("login=", r["Location"])
        self.assertNotIn("login=ok", r["Location"])
        self.assertNotIn(identity.COOKIE, r.cookies)
        self.assertEqual(self.send().status_code, 403)

    def test_a_tampered_state_or_a_turned_off_link_does_nothing(self):
        r = self.api.get("/paypal/payee-login/", {"code": "CODE", "state": "forged"})
        self.assertEqual(r["Location"], "/")
        with paypal("school@example.com"):
            start = self.api.get(f"/api/public/payee/{self.link.token}/paypal-login/")
        state = parse_qs(urlparse(start["Location"]).query)["state"][0]
        services.set_payee_link(self.f.family, self.f.school, self.f.owner, enabled=False)
        with paypal("school@example.com"):
            r = self.api.get("/paypal/payee-login/", {"code": "CODE", "state": state})
        self.assertNotIn(identity.COOKIE, r.cookies)

    def test_a_login_for_one_link_does_not_open_another(self):
        self.login("school@example.com")
        new = services.set_payee_link(self.f.family, self.f.school, self.f.owner, enabled=True, new=True)
        self.link = new
        self.assertEqual(self.send().status_code, 403)

    def test_logout(self):
        self.login("school@example.com")
        self.api.post(f"/api/public/payee/{self.link.token}/logout/")
        self.assertIsNone(self.api.get(f"/api/public/payee/{self.link.token}/").data["paypal_login"]["verified_as"])

    def test_userinfo_shapes(self):
        self.assertEqual(identity.emails({"emails": [{"value": "A@x.com", "confirmed": True},
                                                     {"value": "b@x.com", "confirmed": False}]}), {"a@x.com"})
        self.assertEqual(identity.emails({"email": "c@x.com", "email_verified": True}), {"c@x.com"})
