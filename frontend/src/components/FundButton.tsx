import { useRef, useState } from "react";
import { api, money } from "../api";
import type { Mandate } from "../types";
import PayPalButton from "./PayPalButton";
import { Notice } from "./ui";

/** Add money to a mandate with PayPal checkout. The money counts only after PayPal confirms the capture. */
export default function FundButton({ mandate, onFunded }: { mandate: Mandate; onFunded: () => void }) {
  const [amount, setAmount] = useState("50");
  const [done, setDone] = useState<string | null>(null);
  const amountRef = useRef(amount);
  amountRef.current = amount;

  return (
    <div className="stack-sm fund">
      <div className="money-input" style={{ width: "100%" }}>
        <span aria-hidden style={{ color: "rgb(255 255 255 / .7)" }}>$</span>
        <input className="input" type="number" min="1" step="1" value={amount} aria-label="Amount to add, in US dollars"
          onChange={(e) => { setAmount(e.target.value); setDone(null); }} />
      </div>
      {mandate.status === "ACTIVE" && (
        <PayPalButton
          validate={() => (Number(amountRef.current) >= 1 ? null : "Enter an amount of at least $1")}
          createOrder={async () =>
            (await api.post<{ order_id: string }>(`/mandates/${mandate.id}/fund/create-order/`, { amount: amountRef.current })).order_id}
          onApprove={async (orderId) => {
            await api.post(`/mandates/${mandate.id}/fund/capture/`, { order_id: orderId });
            setDone(money(amountRef.current, mandate.currency));
            onFunded();
          }}
        />
      )}
      {done && <Notice tone="ok" icon="check">Added {done} with PayPal. Thank you.</Notice>}
    </div>
  );
}
