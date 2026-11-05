import { useEffect, useRef, useState } from "react";
import { api, money, when } from "../api";
import Icon from "../components/Icon";
import { ErrorNote, Notice, Skeleton } from "../components/ui";
import { useAction, useApi } from "../hooks";

interface PayeeMandate { id: string; title: string; type: string; currency: string; needs: string[] }
interface PayeeRequest {
  id: string; mandate: string; amount: string; currency: string; status: string; state: string;
  can_add_files: boolean; to_fix: string[]; created_at: string;
}
interface PayeeView { payee: string; family: string; mandates: PayeeMandate[]; requests: PayeeRequest[] }

const KINDS: [string, string][] = [["INVOICE", "Invoice"], ["QUOTE", "Quote"], ["MILESTONE_PHOTO", "Progress photo"]];
const TONE: Record<string, string> = { PAID: "ok", APPROVED: "ok", REFUSED: "warn", CONFIRMED_FRAUD: "warn", FAILED: "warn" };

function newKey() {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/** A payee's private upload link: a school or builder with no account sends invoices, quotes and photos. */
export default function Supplier({ token }: { token: string }) {
  const base = `/public/payee/${encodeURIComponent(token)}`;
  const view = useApi<PayeeView>(`${base}/`);
  const [mandateId, setMandateId] = useState("");
  const [kind, setKind] = useState("INVOICE");
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [addingTo, setAddingTo] = useState<PayeeRequest | null>(null);
  const [result, setResult] = useState<PayeeRequest | null>(null);
  const key = useRef(newKey());
  const fileInput = useRef<HTMLInputElement>(null);
  const { busy, error, setError, run } = useAction();

  const mandates = view.data?.mandates ?? [];
  useEffect(() => {
    if (!mandateId && mandates.length) setMandateId(mandates[0].id);
  }, [mandates, mandateId]);
  const chosen = mandates.find((m) => m.id === mandateId);

  const reset = () => {
    setAmount(""); setNote(""); setFile(null); setAddingTo(null);
    if (fileInput.current) fileInput.current.value = "";
    key.current = newKey();
  };

  const send = () => run(async () => {
    if (!file) { setError("Choose a photo of the document first"); return; }
    if (!addingTo && !(Number(amount) > 0)) { setError("Enter the amount to be paid"); return; }
    const form = new FormData();
    form.append("file", file);
    form.append("kind", kind);
    form.append("idempotency_key", key.current);
    if (note.trim()) form.append("note", note.trim());
    if (addingTo) form.append("request", addingTo.id);
    else { form.append("mandate", mandateId); form.append("amount", amount); }
    setResult(await api.post<PayeeRequest>(`${base}/send/`, form));
    reset();
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
        {view.data && (
          <>
            <section className="give-hero">
              <span className="eyebrow">{view.data.payee}</span>
              <h1>Send to {view.data.family}</h1>
              <p>Send a photo of your invoice, quote or progress on site. It is checked against the family's rules, and approved payments come straight to your PayPal account.</p>
            </section>

            {result && (
              <Notice tone={TONE[result.state] ?? "info"} icon={TONE[result.state] === "ok" ? "check" : "clock"}>
                <strong>{money(result.amount, result.currency)} for {result.mandate}: {result.status}.</strong>
                {result.to_fix.length > 0 && <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>{result.to_fix.map((x) => <li key={x}>{x}</li>)}</ul>}
              </Notice>
            )}

            {mandates.length === 0 ? (
              <div className="card"><span className="small muted">There is nothing to send for right now.</span></div>
            ) : (
              <div className="card stack" style={{ gap: 16 }}>
                <h2>{addingTo ? "Add a file to your request" : "Send a document"}</h2>
                {addingTo ? (
                  <div className="row between" style={{ flexWrap: "nowrap" }}>
                    <span className="small ink-2">{addingTo.mandate} · {money(addingTo.amount, addingTo.currency)}</span>
                    <button className="linkbtn small" onClick={() => setAddingTo(null)}>Send a new one instead</button>
                  </div>
                ) : (
                  <>
                    {mandates.length > 1 && (
                      <div className="field">
                        <label htmlFor="s-mandate">What is it for?</label>
                        <select id="s-mandate" value={mandateId} onChange={(e) => setMandateId(e.target.value)}>
                          {mandates.map((m) => <option key={m.id} value={m.id}>{m.title}</option>)}
                        </select>
                      </div>
                    )}
                    {chosen && (
                      <div className="stack-sm">
                        <span className="small"><strong>{chosen.title}</strong> needs:</span>
                        {chosen.needs.length ? (
                          <ul className="small ink-2" style={{ margin: 0, paddingLeft: 18 }}>{chosen.needs.map((n) => <li key={n}>{n}</li>)}</ul>
                        ) : <span className="small ink-2">Your invoice or quote.</span>}
                      </div>
                    )}
                  </>
                )}
                <div className="field">
                  <span className="label">What are you sending?</span>
                  <div className="row" style={{ gap: 8 }}>
                    {KINDS.map(([k, label]) => (
                      <button type="button" key={k} className={`btn sm ${kind === k ? "primary" : "outline"}`} onClick={() => setKind(k)}>{label}</button>
                    ))}
                  </div>
                </div>
                {!addingTo && (
                  <div className="field">
                    <label htmlFor="s-amount">Amount to be paid</label>
                    <div className="money-input" style={{ maxWidth: 200 }}>
                      <span aria-hidden>$</span>
                      <input id="s-amount" className="input" type="number" min="1" step="0.01" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
                    </div>
                  </div>
                )}
                <div className="field">
                  <label htmlFor="s-file">Photo of the document</label>
                  <input id="s-file" ref={fileInput} type="file" accept="image/*" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
                  <span className="xs muted">A clear photo or screenshot (JPEG or PNG), up to 8 MB.</span>
                </div>
                <div className="field">
                  <label htmlFor="s-note">A note to the family <span className="muted">(optional)</span></label>
                  <input id="s-note" value={note} onChange={(e) => setNote(e.target.value)} />
                </div>
                <button className="btn primary" disabled={busy} onClick={send}><Icon name="send" size={18} />{busy ? "Checking…" : "Send"}</button>
                <ErrorNote error={error} />
                <span className="xs muted row" style={{ gap: 6 }}><Icon name="lock" size={14} />
                  Payments go only to {view.data.payee}'s PayPal account, and only when the family's rules are met.</span>
              </div>
            )}

            {view.data.requests.length > 0 && (
              <section className="card stack">
                <h3>Your requests</h3>
                <div className="list">
                  {view.data.requests.map((r) => (
                    <div key={r.id} className="list-item" style={{ paddingInline: 0, alignItems: "flex-start" }}>
                      <div className="main">
                        <span className="title">{r.mandate} · {money(r.amount, r.currency)}</span>
                        <span className="sub">{when(r.created_at)} · {r.status}</span>
                        {r.to_fix.length > 0 && <span className="xs ink-2">{r.to_fix.join(" · ")}</span>}
                      </div>
                      {r.can_add_files && (
                        <button className="btn outline sm" onClick={() => { setAddingTo(r); setResult(null); window.scrollTo(0, 0); }}>
                          <Icon name="clip" size={16} />Add a file
                        </button>
                      )}
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
