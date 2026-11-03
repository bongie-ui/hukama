"""A pool's public link: anyone can see it and give with PayPal; only the owner controls it."""

from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from core.testing import Fixtures
from mandates import services
from mandates.models import Mandate


class PoolLinkTests(TestCase):
    def setUp(self):
        self.f = Fixtures()
        self.pool = self.f.mandate(Mandate.ISILILO, [
            {"kind": "allowed_payees", "params": {"payee_ids": [str(self.f.supplier.id)]}},
            {"kind": "requires_invoice", "params": {}}], fund=Decimal("100"))
        self.client = APIClient()
        self.client.force_authenticate(self.f.owner)

    def share(self, user=None):
        if user:
            self.client.force_authenticate(user)
        return self.client.post(f"/api/mandates/{self.pool.id}/contribution-link/")

    def test_only_the_owner_shares_and_only_pools_can(self):
        self.assertEqual(self.share(self.f.funders[1]).status_code, 400)
        r = self.share(self.f.owner)
        self.assertTrue(r.data["contribute_token"])
        self.assertTrue(r.data["public_contributions"])
        support = self.f.support_mandate()
        self.assertIn("Only pools", self.client.post(f"/api/mandates/{support.id}/contribution-link/").data["detail"])

    def test_anyone_with_the_link_sees_the_pool_without_signing_in(self):
        token = self.share().data["contribute_token"]
        local = services.create_funding(self.pool, None, Decimal("25"))
        local.contributor_name = "Example Person (Hometown)"
        local.save()
        services.mark_funding_captured(local)
        r = APIClient().get(f"/api/public/pools/{token}/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.data["raised"], r.data["givers"]), ("125.00", 2))
        self.assertIn("Example P.", [g["name"] for g in r.data["recent"]])  # place in brackets ignored  # first name and initial only
        self.assertNotIn("balance", r.data)

    def test_revoked_or_unknown_links_are_dead(self):
        token = self.share().data["contribute_token"]
        self.client.delete(f"/api/mandates/{self.pool.id}/contribution-link/")
        self.assertEqual(APIClient().get(f"/api/public/pools/{token}/").status_code, 404)
        self.assertEqual(APIClient().get("/api/public/pools/nope/").status_code, 404)

    def test_giving_needs_paypal_and_records_nothing_without_it(self):
        token = self.share().data["contribute_token"]
        r = APIClient().post(f"/api/public/pools/{token}/contribute/", {"name": "A", "amount": "10"}, format="json")
        self.assertEqual(r.status_code, 502)  # PayPal not configured in tests
        self.assertEqual(self.pool.fundings.count(), 1)  # nothing recorded until PayPal captures
