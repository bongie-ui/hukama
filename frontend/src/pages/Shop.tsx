import { useEffect, useRef, useState } from "react";
import { api, money, when } from "../api";
import Icon from "../components/Icon";
import ItemPicker, { type Cart, cartLines, cartTotal } from "../components/ItemPicker";
import { ErrorNote, Notice, Skeleton } from "../components/ui";
import { useAction, useApi } from "../hooks";
import type { GroceryItem } from "../types";

interface Store { id: string; name: string; items: GroceryItem[]; delivery_fee: string }
interface ShopMandate {
  id: string; title: string; currency: string; allowance: { left: string; period: string } | null;
  funders: { id: string; name: string }[]; stores: Store[];
}
interface ShopOrder {
  id: string; amount: string; currency: string; state: string; status: string; store: string; fulfilment: string;
  items: { name: string; size: string; quantity: number }[]; to_fix: string[]; delivery: string | null;
  collection_code: string | null; created_at: string;
}
interface ShopView {
  name: string; family: string; unlocked: boolean; address?: string; mandates?: ShopMandate[]; orders?: ShopOrder[];
}

const TONE: Record<string, string> = { APPROVED: "ok", PAID: "ok", INVOICED: "info", REFUSED: "warn", FAILED: "warn" };

function newKey() {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/** A beneficiary's own shop: choose items, collect or delivery, and who to ask if the support fund is short. */
export default function Shop({ token }: { token: string }) {
  const base = `/public/shop/${encodeURIComponent(token)}`;
  const view = useApi<ShopView>(`${base}/`);
  const [mandateId, setMandateId] = useState("");
  const [storeId, setStoreId] = useState("");
  const [cart, setCart] = useState<Cart>({});
  const [fulfilment, setFulfilment] = useState<"COLLECT" | "DELIVERY">("COLLECT");
  const [ask, setAsk] = useState("all");
  const [result, setResult] = useState<ShopOrder | null>(null);
  const key = useRef(newKey());
  const { busy, error, run } = useAction();

  const mandates = view.data?.mandates ?? [];
  const [pin, setPin] = useState("");
  const unlock = useAction();
  const enterPin = (e: React.FormEvent) => {
    e.preventDefault();
    void unlock.run(async () => {
      await api.post(`${base}/unlock/`, { pin });
      setPin("");
      await view.reload();
    });
  };
  useEffect(() => {
    if (!mandateId && mandates.length) setMandateId(mandates[0].id);
  }, [mandates, mandateId]);
  const mandate = mandates.find((m) => m.id === mandateId);
  const store = mandate?.stores.find((s) => s.id === storeId) ?? mandate?.stores[0];
  const lines = cartLines(cart);
  const subtotal = store ? cartTotal(store.items, cart) : 0;
  const fee = fulfilment === "DELIVERY" && store ? Number(store.delivery_fee) : 0;
  const total = lines.length ? subtotal + fee : 0;
  const hasAddress = !!view.data?.address;

  const send = () => run(async () => {
    const r = await api.post<ShopOrder>(`${base}/order/`, {
      mandate: mandate!.id, store: store!.id, items: lines, fulfilment, ask, idempotency_key: key.current,
    });
    setResult(r);
    setCart({});
    key.current = newKey();
    window.scrollTo(0, 0);
    void view.reload();
  });

  return (
    <div className="give">
      <header className="give-top">
        <span className="brand"><img src="/favicon.svg" alt="" /><span>Hukama</span></span>
      </header>
      <main className="give-main">
        {view.error && (
          <div className="card"><div className="empty"><span className="icon-circle"><Icon name="lock" size={24} /></span>
            <strong>This link isn't active</strong><span className="small">Ask the family for a new link.</span></div></div>
        )}
        {!view.data && !view.error && <Skeleton h={420} r={24} />}
        {view.data && !view.data.unlocked && (
          <>
            <section className="give-hero">
              <span className="eyebrow">{view.data.family}</span>
              <h1>Hello {view.data.name}</h1>
              <p>Enter the PIN your family gave you on the phone. You only need to do this once on this phone.</p>
            </section>
            <form className="card stack" style={{ gap: 14 }} onSubmit={enterPin}>
              <div className="field">
                <label htmlFor="sh-pin">Your PIN</label>
                <input id="sh-pin" className="input" inputMode="numeric" autoComplete="one-time-code" maxLength={8}
                  style={{ fontSize: 28, letterSpacing: ".4em", textAlign: "center" }} value={pin}
                  onChange={(e) => setPin(e.target.value.replace(/\D/g, ""))} />
              </div>
              <button className="btn primary block lg" disabled={unlock.busy || pin.length < 4}>{unlock.busy ? <span className="spinner" /> : null}Open my shop</button>
              <ErrorNote error={unlock.error} />
              <span className="xs muted row" style={{ gap: 6 }}><Icon name="lock" size={14} />
                Your family will never ask you for this PIN. If someone calls asking for it, hang up and call your family.</span>
            </form>
          </>
        )}
        {view.data?.unlocked && (
          <>
            <section className="give-hero">
              <span className="eyebrow">{view.data.family}</span>
              <h1>Hello {view.data.name}</h1>
              <p>Choose what you need from the shop. If your support fund can pay, the shop is paid straight away. If not, your list goes to the family to pay.</p>
              {mandate?.allowance && (
                <div><span className="amount xl">{money(mandate.allowance.left, mandate.currency)}</span>
                  <div className="small">left for groceries this {mandate.allowance.period}</div></div>
              )}
            </section>

            {result && (
              <Notice tone={TONE[result.state] ?? "info"} icon={TONE[result.state] === "ok" ? "check" : "clock"}>
                <strong>{money(result.amount, result.currency)} at {result.store}: {result.status}.</strong>
                {result.state === "INVOICED" && <> You'll see here when someone pays.</>}
                {result.to_fix.length > 0 && <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>{result.to_fix.map((x) => <li key={x}>{x}</li>)}</ul>}
              </Notice>
            )}

            {!mandate || !store ? (
              <div className="card"><span className="small muted">There is no shop set up for you yet. Ask the family.</span></div>
            ) : (
              <div className="card stack" style={{ gap: 18 }}>
                <div className="row between">
                  <h2>Shop at {store.name}</h2>
                  {mandate.stores.length > 1 && (
                    <select aria-label="Shop" value={store.id} onChange={(e) => { setStoreId(e.target.value); setCart({}); }}>
                      {mandate.stores.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                    </select>
                  )}
                </div>
                {mandates.length > 1 && (
                  <div className="field">
                    <label htmlFor="sh-m">Pay from</label>
                    <select id="sh-m" value={mandate.id} onChange={(e) => { setMandateId(e.target.value); setStoreId(""); setCart({}); }}>
                      {mandates.map((m) => <option key={m.id} value={m.id}>{m.title}</option>)}
                    </select>
                  </div>
                )}

                <ItemPicker items={store.items} cart={cart} onChange={setCart} currency={mandate.currency} />

                <fieldset className="fulfil">
                  <legend className="label">How do you get it?</legend>
                  <label className={`choice ${fulfilment === "COLLECT" ? "on" : ""}`}>
                    <input type="radio" name="sh-fulfil" checked={fulfilment === "COLLECT"} onChange={() => setFulfilment("COLLECT")} />
                    <Icon name="groceries" size={18} />
                    <span><strong>Collect at the shop</strong> <span className="muted">free</span>
                      <span className="xs muted" style={{ display: "block" }}>You get a code to show at the till</span></span>
                  </label>
                  <label className={`choice ${fulfilment === "DELIVERY" ? "on" : ""} ${hasAddress ? "" : "disabled"}`}>
                    <input type="radio" name="sh-fulfil" checked={fulfilment === "DELIVERY"} disabled={!hasAddress} onChange={() => setFulfilment("DELIVERY")} />
                    <Icon name="home" size={18} />
                    <span><strong>Deliver to my home</strong> <span className="muted">+{money(store.delivery_fee, mandate.currency)}</span>
                      <span className="xs muted" style={{ display: "block" }}>{view.data.address || "No home address registered"}</span></span>
                  </label>
                </fieldset>

                <div className="field">
                  <label htmlFor="sh-ask">If the support fund is short, ask</label>
                  <select id="sh-ask" value={ask} onChange={(e) => setAsk(e.target.value)}>
                    <option value="all">Everyone ({mandate.funders.map((f) => f.name).join(", ")})</option>
                    {mandate.funders.map((f) => <option key={f.id} value={f.id}>Only {f.name}</option>)}
                  </select>
                  <span className="xs muted">The first one to pay covers it, and the others are told.</span>
                </div>

                <ErrorNote error={error} />
                <div className="cart-bar">
                  <div className="stack-sm" style={{ gap: 0 }}>
                    <span className="small">{lines.length ? `${lines.reduce((s, l) => s + l.quantity, 0)} items${fee ? " + delivery" : ""}` : "Nothing chosen yet"}</span>
                    <span className="amount md" style={{ color: "#fff" }}>{money(total, mandate.currency)}</span>
                  </div>
                  <button className="btn" style={{ background: "#fff", color: "var(--plum)" }} disabled={busy || !lines.length} onClick={send}>
                    <Icon name="send" size={18} />{busy ? "Sending…" : "Send my list"}
                  </button>
                </div>
              </div>
            )}

            {(view.data.orders ?? []).length > 0 && (
              <section className="card stack">
                <h3>My shopping</h3>
                <div className="list">
                  {(view.data.orders ?? []).map((o) => (
                    <div key={o.id} className="list-item" style={{ paddingInline: 0, alignItems: "flex-start" }}>
                      <div className="main">
                        <span className="title">{money(o.amount, o.currency)} · {o.store}</span>
                        <span className="sub">{when(o.created_at)} · {o.status}{o.delivery ? ` · ${o.delivery}` : ""}</span>
                        {o.items.length > 0 && <span className="xs muted">{o.items.map((i) => `${i.quantity} × ${i.name}`).join(", ")}</span>}
                        {o.to_fix.length > 0 && <span className="xs ink-2">{o.to_fix.join(" · ")}</span>}
                      </div>
                      {o.collection_code && <span className="pill ok num" title="Show this code at the till">Code {o.collection_code}</span>}
                    </div>
                  ))}
                </div>
              </section>
            )}
          </>
        )}
      </main>
    </div>
  );
}
