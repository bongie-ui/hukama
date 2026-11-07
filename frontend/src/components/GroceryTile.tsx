import { useState } from "react";
import { api, money, newKey, when } from "../api";
import { useAction } from "../hooks";
import type { Beneficiary, Coverage, Mandate, Payee, RequestDetail } from "../types";
import Icon from "./Icon";
import ItemPicker, { type Cart, cartLines, cartTotal } from "./ItemPicker";
import { Avatar, ErrorNote, firstName, Notice, StatusPill } from "./ui";

/** Choose items from the family's store, to collect in store or have delivered to the registered address.
 * Prices come from the store; the server works out the amount. */
export default function GroceryTile({ c, mandate, beneficiary, grocer, onDone }:
  { c: Coverage; mandate: Mandate; beneficiary: Beneficiary; grocer: Payee; onDone: () => void }) {
  const items = grocer.catalogue.items ?? [];
  const fee = Number(grocer.catalogue.delivery_fee ?? 0);
  const [cart, setCart] = useState<Cart>({});
  const [choosing, setChoosing] = useState(false);
  const [fulfilment, setFulfilment] = useState<"DELIVERY" | "COLLECT">(beneficiary.address ? "DELIVERY" : "COLLECT");
  const [result, setResult] = useState<RequestDetail | null>(null);
  const { busy, error, run } = useAction();
  const lines = cartLines(cart);
  const subtotal = cartTotal(items, cart);
  const total = subtotal + (lines.length && fulfilment === "DELIVERY" ? fee : 0);
  const cap = c.cap !== null ? Number(c.cap) : null;
  const used = Number(c.used);
  const latest = c.covered_by[0];
  const recently = !!(latest && c.min_interval_hours &&
    Date.now() - new Date(latest.at).getTime() < c.min_interval_hours * 3600 * 1000);

  const send = () => run(async () => {
    const r = await api.post<RequestDetail>("/requests/", {
      mandate: mandate.id, beneficiary: beneficiary.id, product: "groceries", payee: grocer.id, items: lines, fulfilment,
      idempotency_key: newKey(),
    });
    setResult(r);
    setCart({});
    setChoosing(false);
    onDone();
  });

  return (
    <div className="card tile grocery" style={{ gridColumn: "1 / -1" }}>
      <div className="head">
        <span className="type-icon coral" style={{ width: 38, height: 38 }}><Icon name="groceries" size={20} /></span>
        <div className="stack-sm" style={{ gap: 0, flex: 1 }}>
          <strong>Groceries from {grocer.name}</strong>
          {cap !== null && <span className="xs muted num">{money(Math.max(0, cap - used))} left this {c.period}</span>}
        </div>
      </div>
      {cap !== null && (
        <div className="meter thin"><span style={{ width: `${Math.min(100, (used / cap) * 100)}%`, background: "var(--primary)" }} /></div>
      )}
      <div className="who">
        {latest
          ? <span className="row" style={{ gap: 8, flexWrap: "nowrap" }}><Avatar name={latest.by} size="sm" /><span>{firstName(latest.by)} sent groceries ({money(latest.amount)}) · {when(latest.at)}</span></span>
          : <span className="muted">Nobody has sent groceries yet this {c.period}.</span>}
        {recently && <span className="xs" style={{ display: "block", marginTop: 4, color: "var(--warn)", fontWeight: 700 }}>Already sent in the last {c.min_interval_hours} hours</span>}
      </div>

      {choosing ? (
        <div className="stack-sm">
          <span className="label">Choose what {firstName(beneficiary.name)} needs</span>
          <ItemPicker items={items} cart={cart} onChange={setCart} currency={mandate.currency} />
        </div>
      ) : (
        <button className="btn outline" onClick={() => setChoosing(true)}><Icon name="plus" size={18} />Choose items ({items.length} in store)</button>
      )}

      <fieldset className="fulfil">
        <legend className="label">How does {firstName(beneficiary.name)} get it?</legend>
        <label className={`choice ${fulfilment === "DELIVERY" ? "on" : ""} ${beneficiary.address ? "" : "disabled"}`}>
          <input type="radio" name={`fulfil-${mandate.id}`} checked={fulfilment === "DELIVERY"} disabled={!beneficiary.address}
            onChange={() => setFulfilment("DELIVERY")} />
          <Icon name="home" size={18} />
          <span><strong>Deliver home</strong> <span className="muted">+{money(fee)}</span>
            <span className="xs muted" style={{ display: "block" }}>{beneficiary.address || "No registered address yet"}</span></span>
        </label>
        <label className={`choice ${fulfilment === "COLLECT" ? "on" : ""}`}>
          <input type="radio" name={`fulfil-${mandate.id}`} checked={fulfilment === "COLLECT"} onChange={() => setFulfilment("COLLECT")} />
          <Icon name="groceries" size={18} />
          <span><strong>Collect in store</strong> <span className="muted">free</span>
            <span className="xs muted" style={{ display: "block" }}>{firstName(beneficiary.name)} gets a code by phone</span></span>
        </label>
      </fieldset>

      <div className="row between">
        <span><span className="xs muted">Total </span><span className="amount md">{money(total)}</span></span>
        <button className="btn primary" disabled={busy || !lines.length} onClick={send}>
          {busy ? <span className="spinner" /> : <Icon name="groceries" size={18} />}Send groceries
        </button>
      </div>
      <span className="xs muted">The store is paid directly with PayPal. Delivery only ever goes to the registered address.</span>
      {result && (
        result.status === "APPROVED" || result.status === "PAID"
          ? <Notice tone="ok" icon="check">Sent. {result.fulfilment === "DELIVERY" ? "The store is packing it for delivery." : "She'll get a collection code."} <a href={`#/requests/${result.id}`}>Track it</a></Notice>
          : <div className="result"><div className="row between"><StatusPill status={result.status} /><a href={`#/requests/${result.id}`} className="small">Details</a></div>
              {result.decision && <span className="muted">{result.decision.reason.replace(/^Refused: /, "")}</span>}</div>
      )}
      <ErrorNote error={error} />
    </div>
  );
}
