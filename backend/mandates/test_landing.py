"""The landing page's ways in without a link: a business logs in with PayPal and sees the families it can invoice;
someone at home opens their shop with their registered phone and PIN; and a guide answers questions."""

from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from agent.tests.helpers import fake_pay, quiet_ai
from core.testing import Fixtures
from mandates import services
from mandates.models import Mandate, Payee, Request

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def paypal(email):
    client = mock.Mock(client_id="CLIENT", is_sandbox=True)
    client.user_token.return_value = "USER-TOKEN"
    client.user_info.return_value = {"emails": [{"value": email, "confirmed": True}]}
    return mock.patch("payments.identity.get_client", return_value=client)


@override_settings(PAYEE_PAYPAL_LOGIN=True, PUBLIC_BASE_URL="https://hukama.example/", PAYPAL_CLIENT_ID="X",
                   PAYPAL_CLIENT_SECRET="Y")
class BusinessEntryTests(TestCase):
    def setUp(self):
        self.f = Fixtures()
        self.school_fees = self.f.mandate(Mandate.IMFUNDO, [
            {"kind": "allowed_payees", "params": {"payee_ids": [str(self.f.school.id)]}},
            {"kind": "requires_invoice", "params": {}},
        ])
        self.api = APIClient(enforce_csrf_checks=True)

    def login(self, email):
        with paypal(email):
            start = self.api.get("/api/public/business/login/")
            state = parse_qs(urlparse(start["Location"]).query)["state"][0]
            return self.api.get("/paypal/payee-login/", {"code": "CODE", "state": state})

    def test_nothing_is_shown_before_the_paypal_login(self):
        self.assertEqual(self.api.get("/api/public/business/").data["verified"], False)

    def test_the_school_logs_in_and_sees_the_families_it_can_invoice(self):
        r = self.login("School@Example.com")
        self.assertTrue(r["Location"].endswith("/#/business?login=ok"))
        data = self.api.get("/api/public/business/").data
        self.assertEqual(data["email"], "school@example.com")
        [row] = data["families"]
        self.assertEqual((row["payee"], row["family"], row["for"]), ("Test School", "Test family", [self.school_fees.title]))
        # The same login unlocks that upload page: no second PayPal login needed.
        token = row["upload"]
        page = self.api.get(f"/api/public/payee/{token}/").data
        self.assertEqual(page["paypal_login"]["verified_as"], "school@example.com")

        def read(evidence):
            evidence.extracted = {"total": 340, "supplier": "Test School", "items": []}
            evidence.save()
        with mock.patch("mandates.services._extract", read), \
                mock.patch("mandates.services._intent_analyzer", return_value=quiet_ai), \
                mock.patch("payments.rails.for_payee") as for_payee:
            for_payee.return_value.pay.side_effect = fake_pay
            sent = self.api.post(f"/api/public/payee/{token}/send/", {
                "kind": "INVOICE", "mandate": str(self.school_fees.id), "amount": "340",
                "file": SimpleUploadedFile("i.png", PNG, content_type="image/png")}, format="multipart")
        self.assertEqual(sent.status_code, 201, sent.data)
        self.assertEqual(Request.objects.get().details["paypal_login"], "school@example.com")

    def test_a_paypal_account_no_family_pays_is_turned_away(self):
        r = self.login("stranger@example.com")
        self.assertIn("login=", r["Location"])
        self.assertNotIn("login=ok", r["Location"])
        self.assertFalse(self.api.get("/api/public/business/").data["verified"])

    def test_the_business_login_only_opens_its_own_pages(self):
        self.f.build_mandate()  # a mandate that pays another payee, the supplier
        supplier_link = services.payee_link_for(self.f.family, self.f.supplier)
        self.login("school@example.com")
        page = self.api.get(f"/api/public/payee/{supplier_link.token}/").data
        self.assertIsNone(page["paypal_login"]["verified_as"])
        self.assertEqual(page["requests"], [])

    def test_logout(self):
        self.login("school@example.com")
        self.api.post("/api/public/business/logout/")
        self.assertFalse(self.api.get("/api/public/business/").data["verified"])


class HomeEntryTests(TestCase):
    def setUp(self):
        self.f = Fixtures()
        grocer = Payee.objects.create(family=self.f.family, name="Test Grocer", kind=Payee.GROCER, verified=True,
                                      paypal_email="grocer@example.com", products=["groceries"],
                                      catalogue={"items": [{"id": "meal", "name": "Meal", "price": "8.50"}]})
        b = self.f.beneficiary
        b.allowed_products = ["groceries"]
        b.save()
        self.f.mandate(Mandate.ISIKHWAMA, [
            {"kind": "allowed_beneficiaries", "params": {"beneficiary_ids": [str(b.id)]}},
            {"kind": "allowed_products", "params": {"products": ["groceries"]}},
            {"kind": "allowed_payees", "params": {"payee_ids": [str(grocer.id)]}},
        ])
        self.link, self.pin = services.set_shop_link(self.f.family, b, self.f.owner, enabled=True)
        self.api = APIClient(enforce_csrf_checks=True)

    def test_phone_and_pin_open_the_shop_on_this_phone(self):
        r = self.api.post("/api/public/home/", {"phone": "0770000099", "pin": self.pin}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["shop"], self.link.token)
        self.assertTrue(self.api.get(f"/api/public/shop/{self.link.token}/").data["unlocked"])

    def test_unknown_number_and_wrong_pin_get_the_same_answer(self):
        wrong = "0000" if self.pin != "0000" else "1111"
        a = self.api.post("/api/public/home/", {"phone": "+447700900000", "pin": self.pin}, format="json")
        b = self.api.post("/api/public/home/", {"phone": "+263770000099", "pin": wrong}, format="json")
        self.assertEqual((a.status_code, b.status_code), (400, 400))
        self.assertEqual(a.data["detail"], b.data["detail"])
        self.link.refresh_from_db()
        self.assertEqual(self.link.failed_attempts, 1)  # the wrong PIN still counts

    def test_five_wrong_pins_still_turn_the_link_off(self):
        wrong = "0000" if self.pin != "0000" else "1111"
        for _ in range(5):
            r = self.api.post("/api/public/home/", {"phone": "+263770000099", "pin": wrong}, format="json")
        self.assertIn("now off", r.data["detail"])
        self.link.refresh_from_db()
        self.assertFalse(self.link.active)


class PublicAssistantTests(TestCase):
    def setUp(self):
        cache.clear()
        self.api = APIClient(enforce_csrf_checks=True)

    def ask(self, text="How does a school send an invoice?"):
        return self.api.post("/api/public/assistant/", {"messages": [{"role": "user", "content": text}]}, format="json")

    def test_answers_without_tools_or_family_data(self):
        with mock.patch("agent.llm.chat", return_value={"content": "Use Send an invoice.", "tool_calls": []}) as chat:
            r = self.ask()
        self.assertEqual(r.data["reply"], "Use Send an invoice.")
        args, kwargs = chat.call_args
        self.assertNotIn("tools", kwargs)
        self.assertEqual(len(args), 1)  # messages only: no tools are offered
        self.assertIn("cannot see any family", args[0][0]["content"])

    def test_falls_back_when_the_model_is_unavailable(self):
        from agent.llm import LLMError
        with mock.patch("agent.llm.chat", side_effect=LLMError("down")):
            self.assertIn("Send an invoice", self.ask().data["reply"])

    def test_limited_per_visitor(self):
        with mock.patch("agent.llm.chat", return_value={"content": "ok", "tool_calls": []}):
            codes = [self.ask().status_code for _ in range(31)]
        self.assertEqual(codes[-1], 429)
        self.assertEqual(codes.count(200), 30)
