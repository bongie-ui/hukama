"""Groceries for someone at home: baskets priced by the store, collect in store or delivery to the
registered address, paid to the grocer, with a simulated last mile."""

from datetime import timedelta
from decimal import Decimal


from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from agent import chat
from agent.models import ChatMessage, Conversation
from agent.tests.fakes import ScriptedChat, call, fake_rails, say, tools
from core.testing import Fixtures
from mandates import services
from mandates.models import LedgerEntry, Mandate, Payee, Request
from payments import last_mile
from payments.models import RailTransaction
from payments.payouts import apply_rail_status

CATALOGUE = {"delivery_fee": "3.00", "baskets": [
    {"id": "basic", "name": "Basic hamper", "price": "30.00", "items": ["Maize meal 10 kg", "Cooking oil 2 L"]},
    {"id": "big", "name": "Big shop", "price": "90.00", "items": ["Everything"]},
]}


class GroceryTests(TestCase):
    def setUp(self):
        self.f = Fixtures()
        patcher, self.for_payee = fake_rails()
        self.addCleanup(patcher.stop)
        self.f.provider.products = ["airtime", "bundles", "cash"]
        self.f.provider.save()
        self.grocer = Payee.objects.create(family=self.f.family, name="Test Grocer", kind=Payee.GROCER,
                                           paypal_email="grocer@example.com", verified=True, products=["groceries"],
                                           catalogue=CATALOGUE)
        self.f.beneficiary.address = "1 Test Street, Hometown"
        self.f.beneficiary.allowed_products = ["airtime", "bundles", "cash", "groceries"]
        self.f.beneficiary.save()
        self.mandate = self.f.mandate(Mandate.ISIKHWAMA, [
            {"kind": "allowed_beneficiaries", "params": {"beneficiary_ids": [str(self.f.beneficiary.id)]}},
            {"kind": "allowed_products", "params": {"products": ["airtime", "bundles", "cash", "groceries"]}},
            {"kind": "allowed_payees", "params": {"payee_ids": [str(self.f.provider.id), str(self.grocer.id)]}},
            {"kind": "min_interval", "params": {"hours": 72, "product": "groceries"}},
        ])
        self.client = APIClient()
        self.client.force_authenticate(self.f.owner)

    def order(self, basket="basic", fulfilment="DELIVERY", **extra):
        return self.client.post("/api/requests/", {"mandate": str(self.mandate.id), "product": "groceries",
                                                   "beneficiary": str(self.f.beneficiary.id), "basket_id": basket,
                                                   "fulfilment": fulfilment, **extra}, format="json")

    def test_each_product_goes_to_the_payee_that_supplies_it(self):
        self.assertEqual(services.sole_payee(self.mandate, "groceries"), self.grocer)
        self.assertEqual(services.sole_payee(self.mandate, "bundles"), self.f.provider)

    def test_store_price_and_registered_address_are_used(self):
        r = self.order(amount="1.00")  # a client-sent amount is ignored
        self.assertEqual(r.status_code, 201)
        self.assertEqual(Decimal(r.data["amount"]), Decimal("33.00"))  # 30 + 3 delivery
        self.assertEqual(r.data["payee_name"], "Test Grocer")
        self.assertEqual(r.data["fulfilment"], "DELIVERY")
        self.assertEqual(r.data["details"]["address"], "1 Test Street, Hometown")
        self.assertEqual(r.data["details"]["items"], ["Maize meal 10 kg", "Cooking oil 2 L"])
        self.assertEqual(r.data["status"], Request.APPROVED)

    def test_collect_has_no_delivery_fee(self):
        self.assertEqual(Decimal(self.order(fulfilment="COLLECT").data["amount"]), Decimal("30.00"))

    def test_bad_orders_are_refused_plainly(self):
        self.assertIn("no basket", self.order(basket="caviar").data["detail"])
        self.assertIn("collect in store or home delivery", self.order(fulfilment="DRONE").data["detail"])
        self.f.beneficiary.address = ""
        self.f.beneficiary.save()
        self.assertIn("registered address", self.order().data["detail"])

    def test_second_grocery_order_within_72_hours_is_refused(self):
        self.order()
        self.client.force_authenticate(self.f.funders[1])
        r = self.order(fulfilment="COLLECT")
        self.assertEqual(r.data["status"], Request.REFUSED)
        self.assertIn("Funder1", r.data["decision"]["reason"])

    def test_home_delivery_steps_and_notices(self):
        req = Request.objects.get(pk=self.order().data["id"])
        tx = apply_rail_status(req.rail_transactions.get(), RailTransaction.SUCCESS)
        tx.refresh_from_db()
        self.assertEqual(tx.last_mile_status, RailTransaction.PREPARING)
        started = timezone.now()
        tx = last_mile.advance(tx, now=started + timedelta(seconds=last_mile.PREPARING_SECONDS + 1))
        self.assertEqual(tx.last_mile_status, RailTransaction.OUT_FOR_DELIVERY)
        tx = last_mile.advance(tx, now=started + timedelta(seconds=last_mile.PREPARING_SECONDS
                                                         + last_mile.ON_THE_ROAD_SECONDS + 1))
        self.assertEqual(tx.last_mile_status, RailTransaction.DELIVERED)
        self.assertTrue(LedgerEntry.objects.filter(request=req, event=LedgerEntry.DELIVERED).exists())
        notices = list(ChatMessage.objects.filter(linked_request=req).values_list("text", flat=True))
        self.assertTrue(any("packing" in n and "1 Test Street" in n for n in notices))
        self.assertTrue(any("on the way" in n for n in notices))
        self.assertTrue(any("delivered" in n for n in notices))

    def test_collect_in_store_gets_a_code(self):
        req = Request.objects.get(pk=self.order(fulfilment="COLLECT").data["id"])
        tx = apply_rail_status(req.rail_transactions.get(), RailTransaction.SUCCESS)
        tx.refresh_from_db()
        self.assertEqual(tx.last_mile_status, RailTransaction.AWAITING_COLLECTION)
        notice = ChatMessage.objects.filter(linked_request=req).latest("created_at").text
        self.assertIn("Test Grocer", notice)
        self.assertIn(tx.collection_code, notice)
        self.assertEqual(last_mile.collect(tx, code=tx.collection_code).last_mile_status, RailTransaction.COLLECTED)

    def test_assistant_orders_a_basket_at_the_store_price(self):
        conversation = Conversation.objects.create(family=self.f.family, participant_phone=self.f.beneficiary.phone)
        script = ScriptedChat(
            tools(call("get_mandates")),
            lambda m: tools(call("create_request", mandate_id=str(self.mandate.id), product="groceries", amount=1,
                                 payee_id=None, beneficiary_id=None, summary_en="Groceries delivered",
                                 attachments=[], basket_id="basic", fulfilment="DELIVERY")),
            say("Done."))
        chat.run_turn(conversation, "Ngicela ukudla, deliver please", llm_chat=script)
        baskets = script.tool_results()[0][0]["grocery_baskets"]
        self.assertEqual([b["basket_id"] for b in baskets], ["basic", "big"])
        req = Request.objects.get(channel=Request.CHAT)
        self.assertEqual((req.amount, req.payee, req.fulfilment), (Decimal("33.00"), self.grocer, "DELIVERY"))

    def test_api_lists_catalogue_and_address(self):
        payees = self.client.get("/api/payees/").data
        grocer = next(p for p in payees if p["name"] == "Test Grocer")
        self.assertEqual(grocer["catalogue"]["baskets"][0]["price"], "30.00")
        self.assertEqual(self.client.get("/api/beneficiaries/").data[0]["address"], "1 Test Street, Hometown")


