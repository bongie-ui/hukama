"""Chat by phone: only provider-signed messages are accepted, the sender's registered number decides who they are,
and a payee asking to send an invoice gets their own upload link (which still needs Log in with PayPal)."""

from unittest import mock
from urllib.parse import urlencode

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from agent import phone_channel
from agent.models import ChatMessage, Conversation
from agent.tests.fakes import ScriptedChat, call, say, tools
from core.testing import Fixtures
from mandates.models import Mandate, PayeeLink

TOKEN = "test-token"
URL = "https://hukama.example/api/channels/phone/"


def signed(params):
    import base64, hashlib, hmac
    payload = URL + "".join(f"{k}{v}" for k, v in sorted(params.items()))
    return base64.b64encode(hmac.new(TOKEN.encode(), payload.encode(), hashlib.sha1).digest()).decode()


class FakeHttp:
    def __init__(self):
        self.sent = []

    def post(self, url, auth=None, data=None, timeout=None):
        self.sent.append(data)
        return mock.Mock(raise_for_status=lambda: None, json=lambda: {"sid": "SM1"})

    def get(self, url, auth=None, timeout=None):
        return mock.Mock(raise_for_status=lambda: None, content=b"\x89PNG\r\n\x1a\n0000")


@override_settings(TWILIO_ACCOUNT_SID="AC1", TWILIO_AUTH_TOKEN=TOKEN, PUBLIC_BASE_URL="https://hukama.example/")
class PhoneChannelTests(TestCase):
    def setUp(self):
        self.f = Fixtures()
        self.f.school.phone = "+263770000020"
        self.f.school.save()
        self.f.mandate(Mandate.IMFUNDO, [
            {"kind": "allowed_payees", "params": {"payee_ids": [str(self.f.school.id)]}},
            {"kind": "requires_invoice", "params": {}},
        ])
        self.http = FakeHttp()

    def message(self, frm, body, **extra):
        return {"From": f"whatsapp:{frm}", "Body": body, "NumMedia": "0", **extra}

    def test_only_signed_requests_are_accepted(self):
        params = self.message("+263770000020", "hello")
        api = APIClient()
        with mock.patch("agent.phone_channel.handle_in_background") as bg:
            bad = api.post("/api/channels/phone/", urlencode(params), content_type="application/x-www-form-urlencoded",
                           HTTP_X_TWILIO_SIGNATURE="forged")
            ok = api.post("/api/channels/phone/", urlencode(params), content_type="application/x-www-form-urlencoded",
                          HTTP_X_TWILIO_SIGNATURE=signed(params))
        self.assertEqual((bad.status_code, ok.status_code), (403, 200))
        bg.assert_called_once()

    @override_settings(TWILIO_ACCOUNT_SID="", TWILIO_AUTH_TOKEN="")
    def test_off_until_configured(self):
        self.assertEqual(APIClient().post("/api/channels/phone/", {}).status_code, 503)

    def test_a_school_asking_to_send_an_invoice_gets_its_own_link(self):
        llm = ScriptedChat(tools(call("get_my_link")), lambda m: say(json_reply(m)))
        reply = phone_channel.handle(self.message("+263770000020", "Please send an invoice to the family for fees"),
                                     http=self.http, llm_chat=llm)
        link = PayeeLink.objects.get(payee=self.f.school, active=True)
        self.assertIn(f"/#/supplier/{link.token}", reply)
        self.assertEqual(self.http.sent[0]["To"], "whatsapp:+263770000020")
        c = Conversation.objects.get(participant_phone="+263770000020")
        self.assertEqual(c.family, self.f.family)

    def test_an_unregistered_number_gets_nothing(self):
        reply = phone_channel.handle(self.message("+263779999999", "send me money"), http=self.http,
                                     llm_chat=ScriptedChat())
        self.assertEqual(reply, phone_channel.NOT_REGISTERED)
        self.assertFalse(Conversation.objects.exists())

    def test_a_funder_is_recognised_by_their_number(self):
        llm = ScriptedChat(say("Hi"))
        phone_channel.handle(self.message("+15550000002", "How much is left?"), http=self.http, llm_chat=llm)
        self.assertEqual(Conversation.objects.get().participant_user, self.f.funders[1])

    def test_a_photo_is_stored_and_shown_to_the_assistant(self):
        llm = ScriptedChat(say("Got it"))
        phone_channel.handle(self.message("+263770000020", "invoice attached", NumMedia="1",
                                          MediaUrl0="https://media.example/1", MediaContentType0="image/png"),
                             http=self.http, llm_chat=llm)
        msg = ChatMessage.objects.filter(role="user").get()
        self.assertEqual(len(msg.attachments), 1)

    def test_people_at_home_only_get_a_shop_link_the_family_made(self):
        from agent import chat
        p = chat.Participant(family=self.f.family, phone=self.f.beneficiary.phone, beneficiary=self.f.beneficiary)
        self.assertIn("error", chat.run_tool(p, None, None, "get_my_link", "{}"))


def json_reply(messages):
    import json
    result = json.loads([m for m in messages if m.get("role") == "tool"][-1]["content"])
    return f"Here is your link: {result['link']}"
