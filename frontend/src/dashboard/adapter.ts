// AG Studio LLM adapter that answers each agent turn through our own backend, so the OpenAI key never
// reaches the browser. The server replies with the whole turn at once; we replay it as stream events.
import type { AgAiEvent, AgLlmAdapter, AgLlmRequest, AgLlmResponse } from "ag-studio";

function csrfToken() {
  const match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

async function post(request: AgLlmRequest, signal?: AbortSignal): Promise<AgLlmResponse> {
  const createdAt = Date.now();
  try {
    const res = await fetch("/api/dashboard/ai/turn/", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
      body: JSON.stringify(request),
      signal,
    });
    const body = await res.json();
    if (!res.ok) {
      return { id: `turn-${createdAt}`, createdAt, status: "failed", output: [],
        error: { code: `http_${res.status}`, message: body?.detail ?? "The assistant could not answer" } };
    }
    return { ...body, createdAt };
  } catch (e) {
    const aborted = (e as Error).name === "AbortError";
    return { id: `turn-${createdAt}`, createdAt, status: aborted ? "cancelled" : "failed", output: [],
      error: { code: aborted ? "cancelled" : "network", message: (e as Error).message } };
  }
}

function* eventsFor(response: AgLlmResponse): Generator<AgAiEvent> {
  for (const item of response.output) {
    if (item.type === "message") {
      const text = item.content.map((c) => (c.type === "text" ? c.text : c.refusal)).join("");
      yield { type: "TEXT_MESSAGE_START", messageId: item.id, role: "assistant" };
      yield { type: "TEXT_MESSAGE_CONTENT", messageId: item.id, delta: text };
      yield { type: "TEXT_MESSAGE_END", messageId: item.id };
    } else if (item.type === "function_call") {
      yield { type: "TOOL_CALL_START", toolCallId: item.callId, toolCallName: item.name };
      yield { type: "TOOL_CALL_ARGS", toolCallId: item.callId, delta: item.arguments };
      yield { type: "TOOL_CALL_END", toolCallId: item.callId };
    }
  }
}

export const hukamaAdapter: AgLlmAdapter = {
  executeTurn(request, options) {
    const complete = post(request, options?.signal);
    return {
      complete,
      stream: {
        async *[Symbol.asyncIterator]() {
          yield* eventsFor(await complete);
        },
      },
    };
  },
};
