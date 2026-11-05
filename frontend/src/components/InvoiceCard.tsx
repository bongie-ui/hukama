import { useState } from "react";
import { api, money, when } from "../api";
import type { PayRequest, RequestDetail } from "../types";
import Icon from "./Icon";
import PayPalButton from "./PayPalButton";
import { Avatar, ErrorNote, Notice } from "./ui";
import { useAction } from "../hooks";

interface Line { name: string; size?: string; quantity: number; line_total: string }

/** A shopping list the support fund could not cover: any funder it was sent to can pay it with PayPal.
 * The first payment pays the store; the others are told. */
export default function InvoiceCard({ r, onDone }: { r: PayRequest; onDone: () => void }) {
  const items = (r.details?.items ?? []) as Line[];
  const fee = r.details?.delivery_fee as string | undefined;
  const [paid, setPaid] = useState<RequestDetail | null>(null);
  const [note, setNote] = useState("");
  const { busy, error, run } = useAction();
  const who = r.beneficiary_name?.split(" ")[0] ?? "Someone";

  const decline = () => run(async () => {
    await api.post(`/requests/${r.id}/approval/`, { action: "REJECT", note });
    onDone();
  });

  return (
    <article className="card stack" style={{ borderColor: "var(--primary)" }}>
      <div className="row between" style={{ flexWrap: "nowrap", alignItems: "flex-start" }}>
        <div className="row" style={{ flexWrap: "nowrap", minWidth: 0 }}>
          <Avatar name={r.beneficiary_name ?? r.requester} />
          <div className="stack-sm" style={{ gap: 2, minWidth: 0 }}>
            <h3>{who}'s shopping list</h3>
            <span className="small muted">{r.payee_name} · {r.fulfilment === "DELIVERY" ? "delivery" : "collect"} · {when(r.created_at)}</span>
          </div>
        </div>
        <span className="amount md">{money(r.amount, r.currency)}</span>
      </div>
      <div className="notice info"><Icon name="wallet" size={18} />
        <div>The support fund can't cover this right now. {r.invoice_to_name ? `${who} asked you to pay it.` : `It was sent to everyone; the first to pay covers it.`}</div>
      </div>
      {items.length > 0 && (
        <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
          {items.map((i) => <li key={i.name + i.size}>{i.quantity} × {i.name}{i.size ? ` (${i.size})` : ""} · {money(i.line_total, r.currency)}</li>)}
          {fee && <li>Delivery · {money(fee, r.currency)}</li>}
        </ul>
      )}
      {paid ? (
        <Notice tone="ok" icon="check">Paid. {paid.status === "APPROVED" || paid.status === "PAID" ? "The store is paid with PayPal and the family is told." : paid.decision?.reason}</Notice>
      ) : (
        <>
          <PayPalButton
            createOrder={async () => (await api.post<{ order_id: string }>(`/requests/${r.id}/invoice/create-order/`)).order_id}
            onApprove={async (orderId) => {
              setPaid(await api.post<RequestDetail>(`/requests/${r.id}/invoice/capture/`, { order_id: orderId }));
              onDone();
            }}
          />
          <div className="row" style={{ flexWrap: "nowrap" }}>
            <input className="input" aria-label="Note if you decline" placeholder="Note if you decline (optional)" value={note} onChange={(e) => setNote(e.target.value)} style={{ minWidth: 0 }} />
            <button className="btn outline" disabled={busy} onClick={decline}>Decline</button>
          </div>
        </>
      )}
      <ErrorNote error={error} />
    </article>
  );
}
