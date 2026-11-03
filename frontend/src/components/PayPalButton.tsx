// PayPal button on the PayPal JavaScript SDK v6 (one-time payments). The server creates and captures the
// order (Orders v2 via the PayPal Server SDK); the browser only shows PayPal and returns the approved order id.
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { ErrorNote, Skeleton } from "./ui";

interface PayPalConfig {
  enabled: boolean;
  client_id: string;
  sdk_url: string;
  environment: "sandbox" | "live";
}

/* eslint-disable @typescript-eslint/no-explicit-any */
type Session = { start: (options: { presentationMode: string }, order: Promise<{ orderId: string }>) => Promise<void> };
type Instance = {
  findEligibleMethods: () => Promise<{ isEligible: (method: string) => boolean }>;
  createPayPalOneTimePaymentSession: (callbacks: {
    onApprove: (data: { orderId: string }) => Promise<void>;
    onCancel: () => void;
    onError: (error: Error) => void;
  }) => Session;
};

let configPromise: Promise<PayPalConfig> | null = null;
let scriptPromise: Promise<void> | null = null;
let instancePromise: Promise<Instance> | null = null;

function loadScript(src: string) {
  scriptPromise ??= new Promise((resolve, reject) => {
    const tag = document.createElement("script");
    tag.src = src;
    tag.async = true;
    tag.onload = () => resolve();
    tag.onerror = () => {
      scriptPromise = null;
      reject(new Error("PayPal could not load. Check your connection and try again."));
    };
    document.head.append(tag);
  });
  return scriptPromise;
}

/** One SDK instance per page, shared by every button. */
async function paypal(): Promise<Instance> {
  configPromise ??= api.get<PayPalConfig>("/config/paypal/");
  const config = await configPromise;
  if (!config.enabled || !config.client_id) throw new Error("PayPal is not set up on this server yet.");
  instancePromise ??= loadScript(config.sdk_url).then(() =>
    (window as any).paypal.createInstance({ clientId: config.client_id, components: ["paypal-payments"] }));
  return instancePromise;
}
/* eslint-enable @typescript-eslint/no-explicit-any */

export default function PayPalButton({ createOrder, onApprove, validate, disabled }: {
  /** Ask our server for a PayPal order; resolves to its id. */
  createOrder: () => Promise<string>;
  /** Called with the approved order id: capture it on our server. */
  onApprove: (orderId: string) => Promise<void>;
  /** Return a message to stop before opening PayPal (e.g. a missing name). */
  validate?: () => string | null;
  disabled?: boolean;
}) {
  const box = useRef<HTMLDivElement>(null);
  const handlers = useRef({ createOrder, onApprove, validate });
  handlers.current = { createOrder, onApprove, validate };
  const [state, setState] = useState<"loading" | "ready" | "unavailable" | "working">("loading");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let button: HTMLElement | null = null;
    (async () => {
      try {
        const sdk = await paypal();
        const eligible = (await sdk.findEligibleMethods()).isEligible("paypal");
        if (cancelled) return;
        if (!eligible) {
          setState("unavailable");
          setError("PayPal isn't available in this browser.");
          return;
        }
        const session = sdk.createPayPalOneTimePaymentSession({
          onApprove: async ({ orderId }) => {
            setState("working");
            try {
              await handlers.current.onApprove(orderId);
              setError(null);
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setState("ready");
            }
          },
          onCancel: () => setState("ready"),
          onError: (e) => {
            setState("ready");
            setError(e?.message ? `PayPal: ${e.message}` : "PayPal could not complete the payment.");
          },
        });
        button = document.createElement("paypal-button");
        button.setAttribute("type", "pay");
        button.addEventListener("click", () => {
          const problem = handlers.current.validate?.();
          if (problem) {
            setError(problem);
            return;
          }
          setError(null);
          // Start immediately (not awaited) so the PayPal window keeps the click's user activation.
          const order = handlers.current.createOrder().then((orderId) => ({ orderId }));
          order.catch((e) => setError((e as Error).message));
          void session.start({ presentationMode: "auto" }, order).catch(() => undefined);
        });
        box.current?.replaceChildren(button);
        setState("ready");
      } catch (e) {
        if (!cancelled) {
          setState("unavailable");
          setError((e as Error).message);
        }
      }
    })();
    return () => {
      cancelled = true;
      button?.remove();
    };
  }, []);

  return (
    <div className="paypal-slot" aria-busy={state === "loading" || state === "working"}>
      {state === "loading" && <Skeleton h={45} r={999} />}
      <div ref={box} className="paypal-box" style={{ opacity: disabled || state === "working" ? 0.5 : 1,
        pointerEvents: disabled || state === "working" ? "none" : "auto" }} />
      {state === "working" && <span className="xs muted">Confirming your payment with PayPal…</span>}
      <ErrorNote error={error} />
    </div>
  );
}
