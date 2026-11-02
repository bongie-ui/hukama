"""The dashboard's AI turn: AG Studio items <-> chat messages, through llm.py only."""

import json
from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from agent import dashboard_ai
from core.testing import Fixtures

TURN = {
    "instructions": "You build dashboards.",
    "input": [
        {"id": "1", "kind": "input", "type": "message", "role": "user", "status": "completed",
         "content": [{"type": "text", "text": "Chart spend by category"}]},
        {"id": "2", "kind": "output", "type": "function_call", "callId": "c1", "name": "view_schema",
         "arguments": "{}"},
        {"id": "3", "kind": "output", "type": "function_call", "callId": "c2", "name": "execute_query",
         "arguments": "{\"q\":1}"},
        {"type": "function_call_output", "callId": "c1", "output": "{\"tables\":[]}", "status": "completed"},
        {"type": "function_call_output", "callId": "c2", "output": "[]", "status": "completed"},
        {"id": "4", "kind": "output", "type": "reasoning", "summary": []},
    ],
    "tools": [{"name": "add_widget", "description": "Add a widget", "parameters": {"type": "object"}},
              {"name": "web_search", "description": "", "parameters": {}, "kind": "provided",
               "provider": {"type": "web_search"}}],
    "toolChoice": "auto",
    "responseFormat": {"type": "text"},
}


class TranslationTests(TestCase):
    def test_items_become_chat_messages(self):
        messages = dashboard_ai.to_messages(TURN["instructions"], TURN["input"])
        self.assertEqual([m["role"] for m in messages], ["system", "user", "assistant", "tool", "tool"])
        self.assertEqual([c["id"] for c in messages[2]["tool_calls"]], ["c1", "c2"])  # one assistant message
        self.assertEqual(messages[3]["tool_call_id"], "c1")

    def test_provider_hosted_tools_are_never_offered(self):
        self.assertEqual([t["function"]["name"] for t in dashboard_ai.to_tools(TURN["tools"])], ["add_widget"])

    def test_model_reply_becomes_output_items(self):
        fake = mock.Mock(return_value={"content": "Done", "model": "fake", "usage": {"input": 5, "output": 2},
                                       "tool_calls": [{"id": "c9", "name": "add_widget", "arguments": "{}"}]})
        result = dashboard_ai.run_turn(TURN, llm_chat=fake)
        self.assertEqual(result["status"], "completed")
        self.assertEqual([o["type"] for o in result["output"]], ["message", "function_call"])
        self.assertEqual(result["output"][1]["callId"], "c9")
        self.assertEqual(result["usage"], {"inputTokens": 5, "outputTokens": 2})
        self.assertEqual(fake.call_args.kwargs["tool_choice"], "auto")

    def test_unavailable_model_is_a_failed_turn_not_a_crash(self):
        from agent.llm import LLMError
        result = dashboard_ai.run_turn(TURN, llm_chat=mock.Mock(side_effect=LLMError("down")))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"]["code"], "llm_unavailable")

    def test_bad_items_are_rejected(self):
        with self.assertRaises(dashboard_ai.TurnError):
            dashboard_ai.to_messages("", [{"type": "telepathy"}])


class DashboardApiTests(TestCase):
    def setUp(self):
        self.f = Fixtures()
        self.client = APIClient()

    def test_turn_needs_a_family_member(self):
        self.assertEqual(self.client.post("/api/dashboard/ai/turn/", TURN, format="json").status_code, 403)

    def test_turn_goes_through_llm_wrapper(self):
        self.client.force_authenticate(self.f.owner)
        reply = {"content": "Hi", "tool_calls": [], "model": "fake", "usage": {}}
        with mock.patch("agent.llm.chat", return_value=reply) as chat:
            r = self.client.post("/api/dashboard/ai/turn/", TURN, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["output"][0]["content"][0]["text"], "Hi")
        chat.assert_called_once()

    def test_tables_and_summary(self):
        mandate = self.f.support_mandate()
        self.client.force_authenticate(self.f.owner)
        data = self.client.get("/api/dashboard/data/").data
        self.assertEqual(set(data), {"mandates", "fundings", "requests", "ledger"})
        self.assertEqual(data["mandates"][0]["mandate_id"], str(mandate.id))
        self.assertEqual(data["fundings"][0]["amount"], 1000.0)
        summary = self.client.get("/api/dashboard/summary/").data
        self.assertEqual((summary["funded"], summary["available"]), ("1000.00", "1000.00"))
        json.dumps(data)  # plain JSON for the browser
