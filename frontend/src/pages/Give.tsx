import { useRef, useState } from "react";
import { api, money, when } from "../api";
import Icon from "../components/Icon";
import PayPalButton from "../components/PayPalButton";
import { Avatar, Notice, Skeleton } from "../components/ui";
import { useApi } from "../hooks";

interface PublicPool {
  title: string;
  purpose: string;
  family: string;
  currency: string;
  raised: string;
  givers: number;
  recent: { name: string; amount: string; at: string }[];
}

const PRESETS = ["10", "25", "50", "100"];

/** What anyone with a pool's link sees. No account needed; they give with PayPal. */
export default function Give({ token }: { token: string }) {
  const pool = useApi<PublicPool>(`/public/pools/${encodeURIComponent(token)}/`);
  const [amount, setAmount] = useState("25");
  const [name, setName] = useState("");
  const [message, setMessage] = useState("");
  const [thanks, setThanks] = useState<string | null>(null);
  const form = useRef({ amount, name, message });
  form.current = { amount, name, message };
  const base = `/public/pools/${encodeURIComponent(token)}`;

  return (
    <div className="give">
      <header className="give-top">
        <span className="brand"><img src="/favicon.svg" alt="" /><span>Hukama</span></span>
      </header>
      <main className="give-main">
        {pool.error && (
          <div className="card"><div className="empty"><span className="icon-circle"><Icon name="lock" size={24} /></span>
            <strong>This link isn't active</strong><span className="small">Ask the family for a new link.</span></div></div>
        )}
        {!pool.data && !pool.error && <Skeleton h={420} r={24} />}
        {pool.data && (
          <>
            <section className="give-hero">
              <span className="eyebrow">{pool.data.family}</span>
              <h1>{pool.data.title}</h1>
              {pool.data.purpose && <p>{pool.data.purpose}</p>}
              <div className="row" style={{ gap: 24, marginTop: 8 }}>
                <div><span className="amount xl">{money(pool.data.raised, pool.data.currency)}</span><div className="small">raised</div></div>
                <div><span className="amount xl">{pool.data.givers}</span><div className="small">{pool.data.givers === 1 ? "person has" : "people have"} given</div></div>
              </div>
            </section>

            {thanks ? (
              <div className="card stack" style={{ gap: 12 }}>
                <Notice tone="ok" icon="check"><strong>Thank you, {thanks}.</strong> Your gift reached the family through PayPal.</Notice>
                <button className="btn outline" onClick={() => setThanks(null)}>Give again</button>
              </div>
            ) : (
            <div className="card stack" style={{ gap: 16 }}>
              <h2>Give to this pool</h2>
              <span className="small muted">Amount {money(amount || 0)}. You'll confirm it in PayPal.</span>
              <div className="field">
                <span className="label">Amount</span>
                <div className="row" style={{ gap: 8 }}>
                  {PRESETS.map((p) => (
                    <button type="button" key={p} className={`btn sm ${amount === p ? "primary" : "outline"}`} onClick={() => setAmount(p)}>{money(p)}</button>
                  ))}
                  <div className="money-input" style={{ width: 120 }}>
                    <span aria-hidden>$</span>
                    <input className="input" type="number" min="1" step="1" aria-label="Other amount" value={amount} onChange={(e) => setAmount(e.target.value)} />
                  </div>
                </div>
              </div>
              <div className="field">
                <label htmlFor="g-name">Your name</label>
                <input id="g-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="So the family knows who gave" />
              </div>
              <div className="field">
                <label htmlFor="g-msg">A message to the family <span className="muted">(optional)</span></label>
                <input id="g-msg" value={message} onChange={(e) => setMessage(e.target.value)} />
              </div>
              <PayPalButton
                validate={() => !form.current.name.trim() ? "Tell the family who is giving"
                  : Number(form.current.amount) >= 1 ? null : "Enter an amount of at least $1"}
                createOrder={async () => (await api.post<{ order_id: string }>(`${base}/contribute/`, form.current)).order_id}
                onApprove={async (orderId) => {
                  const r = await api.post<{ name: string }>(`${base}/capture/`, { order_id: orderId });
                  setThanks(r.name);
                  void pool.reload();
                }}
              />
              <span className="xs muted row" style={{ gap: 6 }}><Icon name="lock" size={14} />
                Paid securely with PayPal. The money can only be spent the way the family agreed, and every payment is recorded.</span>
            </div>
            )}

            {pool.data.recent.length > 0 && (
              <section className="card stack">
                <h3>Recent gifts</h3>
                <div className="list">
                  {pool.data.recent.map((g, i) => (
                    <div key={i} className="list-item" style={{ paddingInline: 0 }}>
                      <Avatar name={g.name} />
                      <div className="main"><span className="title">{g.name}</span><span className="sub">{when(g.at)}</span></div>
                      <span className="num" style={{ fontWeight: 700 }}>{money(g.amount, pool.data!.currency)}</span>
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
