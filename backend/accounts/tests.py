"""Starting a new family from the sign-up page."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import Family, Membership

GOOD = {"first_name": "Rudo", "last_name": "Moyo", "email": "Rudo@Example.com", "password": "a-long-family-pass-42",
        "family_name": "Moyo family", "country": "gb", "phone": "+447700900123"}


class SignupTests(TestCase):
    def setUp(self):
        self.api = APIClient(enforce_csrf_checks=True)

    def test_a_new_family_with_its_admin_signed_in(self):
        r = self.api.post("/api/auth/signup/", GOOD, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data["new_family"])
        m = Membership.objects.get(user__email="rudo@example.com")
        self.assertEqual((m.role, m.family.name, m.country, m.phone), (Membership.ADMIN, "Moyo family", "GB",
                                                                       "+447700900123"))
        me = self.api.get("/api/auth/me/").data
        self.assertTrue(me["authenticated"])
        self.assertEqual(me["user"]["family"]["name"], "Moyo family")
        self.assertEqual(self.api.get("/api/mandates/").data, [])  # a fresh family sees only its own data

    def test_the_same_email_cannot_sign_up_twice(self):
        self.api.post("/api/auth/signup/", GOOD, format="json")
        r = APIClient().post("/api/auth/signup/", {**GOOD, "email": "rudo@example.com"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("email", r.data)
        self.assertEqual(Family.objects.count(), 1)

    def test_weak_passwords_and_missing_names_are_refused(self):
        r = self.api.post("/api/auth/signup/", {**GOOD, "password": "123", "first_name": "", "family_name": "",
                                                "last_name": ""}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertTrue({"password", "first_name", "family_name"} <= set(r.data))
        self.assertFalse(get_user_model().objects.exists())

    def test_family_name_defaults_from_the_surname(self):
        r = self.api.post("/api/auth/signup/", {**GOOD, "family_name": ""}, format="json")
        self.assertEqual(r.data["family"]["name"], "Moyo family")
