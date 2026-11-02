import { useState, type FormEvent } from "react";
import { api, money, when } from "../api";
import Icon from "../components/Icon";
import { Avatar, ErrorNote, Notice, Skeleton } from "../components/ui";
import { useAction, useApi } from "../hooks";

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
  const { busy, error, run } = useAction();

  const give = (e: FormEvent) => {
    e.preventDefault();
    void run(() => api.post(`/public/pools/${encodeURIComponent(token)}/contribute/`, { name, amount, message }));
  };

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

            <form className="card stack" onSubmit={give} style={{ gap: 16 }}>
              <h2>Give to this pool</h2>
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
                <input id="g-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="So the family knows who gave" required />
              </div>
              <div className="field">
                <label htmlFor="g-msg">A message to the family <span className="muted">(optional)</span></label>
                <input id="g-msg" value={message} onChange={(e) => setMessage(e.target.value)} />
              </div>
              <button className="btn primary lg" disabled={busy || !name.trim() || Number(amount) <= 0}>
                {busy ? <span className="spinner" /> : null}Give {money(amount || 0)} with PayPal
              </button>
              {error && (error.includes("opens soon")
                ? <Notice tone="info" icon="clock">PayPal checkout for pools is being switched on. Please try again soon.</Notice>
                : <ErrorNote error={error} />)}
              <span className="xs muted row" style={{ gap: 6 }}><Icon name="lock" size={14} />
                Paid securely with PayPal. The money can only be spent the way the family agreed, and every payment is recorded.</span>
            </form>

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
