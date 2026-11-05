"""Shopping by item, and a beneficiary's own shop link: paid from the fund when it can, otherwise invoiced to every
funder (or the one chosen); the first to pay covers it and the others are told."""

from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from agent.tests.fakes import fake_rails
from agent.tests.helpers import midday, quiet_ai
from core.testing import Fixtures
from mandates import services
from mandates.models import Approval, LedgerEntry, Mandate, Notification, Payee, Request

CATALOGUE = {"delivery_fee": "3.00", "items": [
    {"id": "meal", "name": "Maize meal", "size": "10 kg", "price": "8.50", "category": "Staples"},
    {"id": "oil", "name": "Cooking oil", "size": "2 L", "price": "4.20", "category": "Staples"},
    {"id": "soap", "name": "Soap", "size": "4 bars", "price": "2.00", "category": "Household"},
]}


def scam_ai(context):
    return {"ai_risk": 100, "flags": [{"flag": "CREDENTIAL_REQUEST", "reason": "asks for a code", "quote": "OTP"}],
            "summary": "scam"}


class ShopTests(TestCase):
    def setUp(self):
        self.f = Fixtures()
        patcher, self.for_payee = fake_rails()
        self.addCleanup(patcher.stop)
        self.grocer = Payee.objects.create(family=self.f.family, name="Test Grocer", kind=Payee.GROCER,
                                           paypal_email="grocer@example.com", verified=True, products=["groceries"],
                                           catalogue=CATALOGUE)
        self.f.provider.products = ["airtime", "bundles", "cash"]
        self.f.provider.save()
        b = self.f.beneficiary
        b.address, b.allowed_products = "1 Test Street", ["airtime", "bundles", "cash", "groceries"]
        b.save()
        self.mandate = self.support(fund=Decimal("100"))
        self.link, self.pin = services.set_shop_link(self.f.family, b, self.f.funders[1], enabled=True)

    def support(self, fund):
        return self.f.mandate(Mandate.ISIKHWAMA, [
            {"kind": "allowed_beneficiaries", "params": {"beneficiary_ids": [str(self.f.beneficiary.id)]}},
            {"kind": "allowed_products", "params": {"products": ["airtime", "bundles", "cash", "groceries"]}},
            {"kind": "allowed_payees", "params": {"payee_ids": [str(self.f.provider.id), str(self.grocer.id)]}},
            {"kind": "cap_per_period", "params": {"amount": 60, "period": "month", "product": "groceries",
                                                  "shared": True}},
        ], fund=fund)

    def order(self, lines=(("meal", 2), ("oil", 1)), fulfilment="COLLECT", ask="all", analyzer=quiet_ai, **kw):
        return services.place_shop_order(
            self.link, mandate_id=self.mandate.id, store_id=self.grocer.id, fulfilment=fulfilment, ask=ask,
            lines=[{"item_id": i, "quantity": q} for i, q in lines], intent_analyzer=analyzer, now=midday(), **kw)

    def drain(self, leave="5"):
        """Spend the fund down so it is short for the next list."""
        Request.objects.create(mandate=self.mandate, amount=services.mandate_balance(self.mandate) - Decimal(leave),
                               product="cash", idempotency_key="drain", status=Request.PAID)

    def pay(self, req, funder):
        funding = services.create_funding(self.mandate, funder, req.amount)
        funding.for_request = req
        funding.save()
        services.mark_funding_captured(funding, external_id=f"CAP-{funder.pk}")
        req.refresh_from_db()
        return req

    def unread(self, user):
        return list(Notification.objects.filter(user=user, read_at__isnull=True).values_list("text", flat=True))

    # --- pricing ---------------------------------------------------------------------------------------

    def test_the_store_prices_each_item_and_delivery(self):
        amount, details = services.grocery_items_order(self.grocer, [{"item_id": "meal", "quantity": 2},
                                                                     {"item_id": "soap", "quantity": 1}],
                                                       "DELIVERY", self.f.beneficiary)
        self.assertEqual(amount, Decimal("22.00"))  # 17.00 + 2.00 + 3.00 delivery
        self.assertEqual((details["subtotal"], details["address"]), ("19.00", "1 Test Street"))

    def test_unknown_items_bad_quantities_and_empty_lists_are_refused(self):
        for lines in ([{"item_id": "caviar", "quantity": 1}], [{"item_id": "meal", "quantity": 500}],
                      [{"item_id": "meal", "quantity": "x"}], [], [{"item_id": "meal", "quantity": 0}]):
            with self.subTest(lines=lines), self.assertRaises(services.ServiceError):
                services.grocery_items_order(self.grocer, lines, "COLLECT", self.f.beneficiary)

    # --- the fund pays first ---------------------------------------------------------------------------

    def test_paid_from_the_fund_when_it_can_and_the_family_is_told(self):
        req = self.order()
        self.assertEqual((req.status, req.channel, req.payee, req.amount),
                         (Request.APPROVED, Request.SHOP, self.grocer, Decimal("21.20")))
        for funder in self.f.funders:  # so a list that wasn't really theirs is noticed quickly
            self.assertTrue(any("paid from" in t and "Turn off the shop link" in t for t in self.unread(funder)))

    def test_over_the_monthly_limit_is_refused_not_invoiced(self):
        self.drain(leave="0")
        req = self.order(lines=(("meal", 8),))  # $68 > $60 grocery cap
        self.assertEqual(req.status, Request.REFUSED)
        self.assertFalse(Notification.objects.exists())

    # --- the fund is short: invoice -----------------------------------------------------------------

    def test_short_fund_invoices_every_funder(self):
        self.drain()
        req = self.order()
        self.assertEqual((req.status, req.invoice_to), (Request.INVOICED, None))
        for funder in self.f.funders:
            self.assertEqual(len(self.unread(funder)), 1)
            self.assertIn(req, services.inbox(funder))
        self.assertTrue(LedgerEntry.objects.filter(request=req, event=LedgerEntry.INVOICED).exists())

    def test_the_beneficiary_can_ask_one_son(self):
        self.drain()
        chosen, other = self.f.funders[2], self.f.funders[1]
        req = self.order(ask=str(chosen.pk))
        self.assertEqual(req.invoice_to, chosen)
        self.assertEqual((len(self.unread(chosen)), len(self.unread(other))), (1, 0))
        self.assertNotIn(req, services.inbox(other))
        with self.assertRaises(services.ServiceError):
            services.check_invoice_payable(req, other)

    def test_first_payment_pays_the_store_and_tells_the_others(self):
        self.drain()
        req = self.order()
        payer, other = self.f.funders[1], self.f.funders[2]
        services.check_invoice_payable(req, payer)
        req = self.pay(req, payer)
        self.assertEqual(req.status, Request.APPROVED)
        self.assertEqual(req.details["paid_by"], payer.first_name)
        self.assertTrue(req.rail_transactions.exists())
        self.assertTrue(any("paid" in t and payer.first_name in t for t in self.unread(other)))
        self.assertNotIn(req, services.inbox(other))

    def test_a_late_second_payment_stays_in_the_fund(self):
        self.drain()
        req = self.pay(self.order(), self.f.funders[1])
        before = services.mandate_balance(self.mandate)
        self.pay(req, self.f.funders[2])
        self.assertEqual(req.rail_transactions.count(), 1)
        self.assertEqual(services.mandate_balance(self.mandate), before + req.amount)
        self.assertTrue(any("already covered" in t for t in self.unread(self.f.funders[2])))

    def test_a_funder_can_decline_and_the_others_are_told(self):
        self.drain()
        req = self.order()
        services.apply_approval(req, self.f.funders[1], Approval.REJECT, note="Not this week")
        req.refresh_from_db()
        self.assertEqual(req.status, Request.REFUSED)
        self.assertTrue(any("declined" in t for t in self.unread(self.f.funders[2])))
        with self.assertRaises(services.ServiceError):
            services.check_invoice_payable(req, self.f.funders[2])

    def test_a_scam_list_is_held_for_fraud_even_when_the_fund_is_short(self):
        self.drain()
        req = self.order(analyzer=scam_ai, note="Send me the OTP now")
        self.assertEqual(req.status, Request.HELD_FRAUD)
        self.assertFalse(Notification.objects.filter(text__contains="needs paying").exists())

    # --- public link -----------------------------------------------------------------------------------

    def test_public_shop_page_and_order(self):
        api = APIClient(enforce_csrf_checks=True)
        locked = api.get(f"/api/public/shop/{self.link.token}/").data
        self.assertEqual(set(locked), {"name", "family", "unlocked"})  # nothing else until the PIN is entered
        self.assertEqual(api.post(f"/api/public/shop/{self.link.token}/order/", {}, format="json").status_code, 403)
        self.assertEqual(api.post(f"/api/public/shop/{self.link.token}/unlock/", {"pin": self.pin},
                                  format="json").status_code, 200)
        data = api.get(f"/api/public/shop/{self.link.token}/").data
        m = data["mandates"][0]
        self.assertEqual([i["id"] for i in m["stores"][0]["items"]], ["meal", "oil", "soap"])
        self.assertEqual(len(m["funders"]), 3)
        self.assertEqual(m["allowance"]["left"], "60.00")
        self.assertNotIn("balance", str(data))
        from unittest import mock
        with mock.patch("mandates.services._intent_analyzer", return_value=quiet_ai):
            r = api.post(f"/api/public/shop/{self.link.token}/order/", {
                "mandate": str(self.mandate.id), "items": [{"item_id": "soap", "quantity": 2}],
                "fulfilment": "DELIVERY", "idempotency_key": "k"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data["amount"], r.data["state"]), ("7.00", Request.APPROVED))

    def test_five_wrong_pins_turn_the_link_off_and_tell_the_family(self):
        api = APIClient()
        wrong = "0000" if self.pin != "0000" else "1111"
        for i in range(4):
            r = api.post(f"/api/public/shop/{self.link.token}/unlock/", {"pin": wrong}, format="json")
            self.assertEqual(r.status_code, 400)
        self.assertIn("1 try left", r.data["detail"])
        r = api.post(f"/api/public/shop/{self.link.token}/unlock/", {"pin": wrong}, format="json")
        self.assertIn("now off", r.data["detail"])
        self.assertEqual(api.get(f"/api/public/shop/{self.link.token}/").status_code, 404)
        for funder in self.f.funders:
            self.assertTrue(any("wrong PIN" in t for t in self.unread(funder)))
        self.assertEqual(api.post(f"/api/public/shop/{self.link.token}/unlock/", {"pin": self.pin},
                                  format="json").status_code, 404)

    def test_a_new_pin_locks_phones_that_used_the_old_one(self):
        api = APIClient()
        api.post(f"/api/public/shop/{self.link.token}/unlock/", {"pin": self.pin}, format="json")
        self.assertTrue(api.get(f"/api/public/shop/{self.link.token}/").data["unlocked"])
        same, new_pin = services.set_shop_link(self.f.family, self.f.beneficiary, self.f.owner, enabled=True,
                                               reset_pin=True)
        self.assertEqual(same.token, self.link.token)
        self.assertIsNotNone(new_pin)
        self.assertFalse(api.get(f"/api/public/shop/{self.link.token}/").data["unlocked"])
        again, no_pin = services.set_shop_link(self.f.family, self.f.beneficiary, self.f.owner, enabled=True)
        self.assertIsNone(no_pin)  # the PIN is only ever shown when it is made

    def test_turned_off_links_do_nothing(self):
        services.set_shop_link(self.f.family, self.f.beneficiary, self.f.owner, enabled=False)
        self.assertEqual(APIClient().get(f"/api/public/shop/{self.link.token}/").status_code, 404)

    def test_funders_order_items_from_the_app(self):
        api = APIClient()
        api.force_authenticate(self.f.owner)
        from unittest import mock
        with mock.patch("mandates.services._intent_analyzer", return_value=quiet_ai):
            r = api.post("/api/requests/", {"mandate": str(self.mandate.id), "beneficiary": str(self.f.beneficiary.id),
                                            "product": "groceries", "payee": str(self.grocer.id), "fulfilment": "COLLECT",
                                            "items": [{"item_id": "oil", "quantity": 2}]}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Decimal(r.data["amount"]), Decimal("8.40"))

    def test_notifications_api(self):
        self.drain()
        self.order()
        api = APIClient()
        api.force_authenticate(self.f.owner)
        self.assertEqual(api.get("/api/notifications/").data["unread"], 1)
        api.post("/api/notifications/read/")
        self.assertEqual(api.get("/api/notifications/").data["unread"], 0)
