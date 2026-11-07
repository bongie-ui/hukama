import { useState } from "react";
import { api, money, when } from "../api";
import { useAction } from "../hooks";
import type { PayRequest, RequestDetail } from "../types";
import Icon from "./Icon";
import { ErrorNote, firstName, productLabel } from "./ui";

const FLAG_LABEL: Record<string, string> = {
  URGENCY_PRESSURE: "Urgency pressure",
  IMPERSONATION: "Pretending to be family",
  THIRD_PARTY_PAYMENT: "Asks to pay someone else",
  EMERGENCY_STORY: "Emergency story",
  CREDENTIAL_REQUEST: "Asks for a PIN or code",
  REVERSAL_SCAM: "Reversal scam",
  PRIZE_SCAM: "Prize scam",
  STYLE_MISMATCH: "Doesn't sound like them",
  PURPOSE_MISMATCH: "Not what the money is for",
  OTHER: "Something else",
};

/** The card every funder sees when a request is held for possible fraud. */
export function FraudCard({ r, children }: { r: PayRequest; children?: React.ReactNode }) {
  const risk = r.risk!;
  return (
    <article className="fraud" aria-labelledby={`fraud-${r.id}`}>
      <div className="fraud-head">
        <Icon name="alert" size={22} />
        <h3 id={`fraud-${r.id}`}>Possible scam. Nothing has been paid.</h3>
        <span className="score">Risk {risk.score}/100</span>
      </div>
      <div className="fraud-body">
        <div className="stack-sm">
          <span className="small muted">
            {r.requester_phone || r.requester} asked for <strong className="num" style={{ color: "var(--ink)" }}>{money(r.amount, r.currency)}</strong> {productLabel(r.product)}
            {r.beneficiary_name ? ` for ${firstName(r.beneficiary_name)}` : ""} · {when(r.created_at)}
          </span>
          {r.message_text && <blockquote className="quote">“{r.message_text}”</blockquote>}
        </div>
        <div className="verify">
          <Icon name="phone" size={20} />
          <div><strong>Before anyone pays</strong>{risk.suggested_verification}</div>
        </div>
        <RiskDetails r={r} />
        {children}
      </div>
    </article>
  );
}

export function RiskDetails({ r }: { r: PayRequest }) {
  const risk = r.risk!;
  return (
    <div className="split" style={{ gap: 20 }}>
      {risk.signals.length > 0 && (
        <div className="stack-sm">
          <span className="eyebrow">Checks that fired</span>
          <ul className="signals">
            {risk.signals.map((s) => <li key={s.signal}><span className="w">+{s.weight}</span><span>{s.detail}</span></li>)}
          </ul>
        </div>
      )}
      {risk.ai_flags.length > 0 && (
        <div className="stack-sm">
          <span className="eyebrow row" style={{ gap: 6 }}><Icon name="sparkle" size={14} />What the assistant noticed</span>
          <div className="flags">
            {risk.ai_flags.map((f, i) => (
              <div key={i} className="flag">
                <strong>{FLAG_LABEL[f.flag] ?? f.flag}</strong>
                <span className="ink-2">{f.reason}</span>
                {f.quote && <q>{f.quote}</q>}
              </div>
            ))}
          </div>
        </div>
      )}
      {risk.signals.length === 0 && risk.ai_flags.length === 0 && <p className="small muted">Nothing unusual about this request.</p>}
    </div>
  );
}

/** Approve or reject an escalation; verify or report a fraud hold. Only actions the backend allows are shown. */
export function ApprovalActions({ r, onDone }:
  { r: PayRequest & { allowed_actions?: string[] }; onDone: (r: RequestDetail) => void }) {
  const [note, setNote] = useState("");
  const [confirmReport, setConfirmReport] = useState(false);
  const { busy, error, run } = useAction();
  const allowed = r.allowed_actions ?? (r.status === "HELD_FRAUD" ? ["VERIFIED_SAFE", "REJECT", "REPORT_FRAUD"]
    : r.status === "ESCALATED" ? ["APPROVE", "REJECT", "REPORT_FRAUD"] : []);
  if (allowed.length === 0) return null;
  const held = r.status === "HELD_FRAUD";

  const act = (action: string) => run(async () => {
    onDone(await api.post<RequestDetail>(`/requests/${r.id}/approval/`, { action, note }));
  });

  if (confirmReport) {
    return (
      <div className="stack" style={{ padding: 14, borderRadius: 12, background: "var(--bad-soft)" }}>
        <strong style={{ color: "var(--bad)" }}>Report this as a scam?</strong>
        <span className="small ink-2">The request is cancelled and every unregistered number in it is blocked for your family.</span>
        <div className="row">
          <button className="btn danger" disabled={busy} onClick={() => act("REPORT_FRAUD")}>{busy ? <span className="spinner" /> : null}Yes, report scam</button>
          <button className="btn outline" disabled={busy} onClick={() => setConfirmReport(false)}>Go back</button>
        </div>
        <ErrorNote error={error} />
      </div>
    );
  }

  return (
    <div className="stack">
      <div className="field">
        <label htmlFor={`note-${r.id}`}>{held ? "How did you check?" : "Note for the family (optional)"}</label>
        <input id={`note-${r.id}`} value={note} onChange={(e) => setNote(e.target.value)}
          placeholder={held ? "e.g. Called them on the registered number; they asked for this" : ""} />
        {held && <span className="hint">Paying a held request needs a note saying how you confirmed it.</span>}
      </div>
      <div className="row">
        {allowed.includes("REPORT_FRAUD") && held && (
          <button className="btn danger" disabled={busy} onClick={() => setConfirmReport(true)}><Icon name="alert" size={18} />Report scam</button>
        )}
        {allowed.includes("APPROVE") && <button className="btn primary" disabled={busy} onClick={() => act("APPROVE")}><Icon name="check" size={18} />Approve and pay</button>}
        {allowed.includes("VERIFIED_SAFE") && (
          <button className="btn outline" disabled={busy || !note.trim()} onClick={() => act("VERIFIED_SAFE")}>I confirmed it, pay</button>
        )}
        {allowed.includes("REJECT") && <button className="btn outline" disabled={busy} onClick={() => act("REJECT")}>Decline</button>}
        {allowed.includes("REPORT_FRAUD") && !held && (
          <button className="btn ghost" disabled={busy} onClick={() => setConfirmReport(true)}>Report scam</button>
        )}
      </div>
      <span className="xs muted">Paying still re-checks every rule and the balance. A refusal by the rules can never be overridden.</span>
      <ErrorNote error={error} />
    </div>
  );
}
