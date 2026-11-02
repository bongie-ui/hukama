from django.test import SimpleTestCase, TestCase, override_settings

from .phones import find_phones, normalize_phone


@override_settings(DEFAULT_PHONE_COUNTRY_CODE="263")
class PhoneTests(SimpleTestCase):
    def test_normalize(self):
        self.assertEqual(normalize_phone("0771234567"), "+263771234567")
        self.assertEqual(normalize_phone("+263 77 123 4567"), "+263771234567")
        self.assertEqual(normalize_phone("00447700900123"), "+447700900123")
        self.assertIsNone(normalize_phone("12"))
        self.assertIsNone(normalize_phone(""))

    def test_find_phones_ignores_amounts_and_codes(self):
        text = "Please send $150 to 0771234567 or 077-123-4568, code 482193, ref 2026"
        self.assertEqual(find_phones(text), ["+263771234567", "+263771234568"])

    def test_find_phones_international(self):
        self.assertEqual(find_phones("call me on +27 82 555 0100"), ["+27825550100"])


class HealthTests(TestCase):
    def test_health(self):
        resp = self.client.get("/api/health/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")


class SeedDemoTests(TestCase):
    """The seed must produce valid, signed, funded mandates and be safely re-runnable."""

    def test_seed_and_reset(self):
        from io import StringIO

        from django.core.management import call_command
        from django.core.management.base import CommandError

        from accounts.models import Family
        from core.management.commands import seed_demo
        from mandates import services, signing
        from mandates.models import Mandate, Request

        call_command("seed_demo", stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command("seed_demo", stdout=StringIO())
        call_command("seed_demo", "--reset", stdout=StringIO())
        out = StringIO()
        call_command("seed_demo", "--sync", stdout=out)
        self.assertIn("up to date", out.getvalue())
        Family.objects.update(seed_version=0)  # an older seed is rebuilt by --sync
        call_command("seed_demo", "--sync", stdout=StringIO())
        self.assertEqual(Family.objects.get().seed_version, seed_demo.SEED_VERSION)

        mandates = list(Mandate.objects.all())
        self.assertEqual(len(mandates), 4)
        for m in mandates:
            self.assertTrue(signing.verify(m))
            self.assertGreater(services.mandate_balance(m), 0)
        history = Request.objects.filter(status=Request.PAID)
        self.assertGreaterEqual(history.count(), 3)  # AMOUNT_SPIKE needs a baseline
        self.assertFalse(history.filter(created_at__gte=services.timezone.now().replace(day=1)).exists())


class PostmanCollectionTests(SimpleTestCase):
    """Every request in the published collection must hit a real route."""

    def test_every_request_resolves(self):
        import re

        from django.urls import Resolver404, resolve

        from core.management.commands.export_postman import all_requests, collection

        uuid = "00000000-0000-0000-0000-000000000000"
        for item in all_requests(collection()["item"]):
            raw = item["request"]["url"]["raw"].replace("{{baseUrl}}", "").split("?")[0]
            path = re.sub(r"\{\{[A-Za-z]+\}\}", uuid, raw)
            try:
                resolve(path)
            except Resolver404:
                self.fail(f"{item['name']}: {path} is not a route")
