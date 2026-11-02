"""Server side of the dashboard's AI adapter (AG Studio Agent Framework, Direct LLM Runner).

The browser sends one AgLlmRequest per turn; we translate it to a chat call through llm.py (so the key
stays on the server, with the same retries, logging and demo replay) and return an AgLlmResponse.
The dashboard's tools only read and lay out the family's own data: they cannot move money.
"""

import uuid

from . import llm

MAX_ITEMS = 200
MAX_TOOLS = 64


class TurnError(ValueError):
    """The request is not a valid AG Studio turn."""


def _text(content):
    parts = content if isinstance(content, list) else []
    return "\n".join(p.get("text", "") for p in parts if isinstance(p, dict) and p.get("type") == "text")


def to_messages(instructions, items):
    """AG Studio conversation items -> chat messages. Consecutive tool calls share one assistant message."""
    messages = [{"role": "system", "content": instructions}] if instructions else []
    for item in items[-MAX_ITEMS:]:
        kind = item.get("type")
        if kind == "message":
            role = item.get("role")
            if role not in ("user", "system", "assistant"):
                raise TurnError(f"unknown role {role!r}")
            messages.append({"role": role, "content": _text(item.get("content"))})
        elif kind == "function_call":
            call = {"id": item["callId"], "type": "function",
                    "function": {"name": item["name"], "arguments": item.get("arguments") or "{}"}}
            last = messages[-1] if messages else None
            if last and last["role"] == "assistant" and "tool_calls" in last and not last.get("content"):
                last["tool_calls"].append(call)
            else:
                messages.append({"role": "assistant", "content": None, "tool_calls": [call]})
        elif kind == "function_call_output":
            messages.append({"role": "tool", "tool_call_id": item["callId"], "content": str(item.get("output", ""))})
        elif kind == "reasoning":
            continue
        else:
            raise TurnError(f"unknown item type {kind!r}")
    return messages


def to_tools(tools):
    """Function tools only: provider-hosted tools are not offered (nothing leaves except via our own call)."""
    return [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""),
                                               "parameters": t.get("parameters") or {"type": "object"}}}
            for t in (tools or [])[:MAX_TOOLS] if t.get("kind", "client") != "provided"]


def to_tool_choice(choice):
    if choice in (None, "auto", "none", "required"):
        return choice
    if isinstance(choice, dict) and choice.get("name"):
        return {"type": "function", "function": {"name": choice["name"]}}
    raise TurnError("invalid toolChoice")


def to_response_format(fmt):
    if not fmt or fmt.get("type") == "text":
        return None
    return {"type": "json_schema", "json_schema": {"name": fmt.get("name") or "result", "schema": fmt["schema"],
                                                   "strict": False}}


def run_turn(payload, llm_chat=None):
    """AgLlmRequest dict -> AgLlmResponse dict."""
    llm_chat = llm_chat or llm.chat
    items = payload.get("input")
    if not isinstance(items, list):
        raise TurnError("input must be a list")
    tools = to_tools(payload.get("tools"))
    try:
        result = llm_chat(to_messages(payload.get("instructions"), items), tools or None,
                          tool_choice=to_tool_choice(payload.get("toolChoice")) if tools else None,
                          response_format=to_response_format(payload.get("responseFormat")))
    except llm.LLMError as exc:
        return {"id": f"turn-{uuid.uuid4()}", "status": "failed", "output": [],
                "error": {"code": "llm_unavailable", "message": str(exc)}}
    output = []
    if result["content"]:
        output.append({"id": f"msg-{uuid.uuid4()}", "kind": "output", "type": "message", "role": "assistant",
                       "status": "completed", "content": [{"type": "text", "text": result["content"],
                                                           "annotations": []}]})
    for call in result["tool_calls"]:
        output.append({"id": f"fc-{uuid.uuid4()}", "kind": "output", "type": "function_call", "callId": call["id"],
                       "name": call["name"], "arguments": call["arguments"], "status": "completed"})
    usage = result.get("usage") or {}
    return {"id": f"turn-{uuid.uuid4()}", "status": "completed", "output": output, "model": result.get("model"),
            "usage": {"inputTokens": usage.get("input", 0), "outputTokens": usage.get("output", 0)}}
