import { useState } from "react";
import { api } from "../api";
import { useAction } from "../hooks";
import type { Mandate } from "../types";
import { ErrorNote } from "./ui";

/**
 * Funding through PayPal checkout. The backend's create-order/capture endpoints are built with the PayPal
 * Server SDK; until they are switched on, the server answers with a readable message shown here.
 */
export default function FundButton({ mandate, onFunded }: { mandate: Mandate; onFunded: () => void }) {
  const [amount, setAmount] = useState("50");
  const { busy, error, run } = useAction();

  const fund = () => run(async () => {
    const order = await api.post<{ id: string }>(`/mandates/${mandate.id}/fund/create-order/`, { amount });
    await api.post(`/mandates/${mandate.id}/fund/capture/`, { order_id: order.id });
    onFunded();
  });

  return (
    <div className="stack-sm">
      <div className="row" style={{ flexWrap: "nowrap" }}>
        <div className="money-input" style={{ width: 110, flex: "none" }}>
          <span aria-hidden style={{ color: "rgb(255 255 255 / .7)" }}>$</span>
          <input className="input" type="number" min="1" step="1" value={amount} aria-label="Amount to add, in US dollars"
            onChange={(e) => setAmount(e.target.value)} />
        </div>
        <button className="btn primary" style={{ flex: 1 }} disabled={busy || Number(amount) <= 0 || mandate.status !== "ACTIVE"} onClick={fund}>
          {busy ? <span className="spinner" /> : null}Add funds with PayPal
        </button>
      </div>
      <ErrorNote error={error} />
    </div>
  );
}
