import { useState } from "react";
import { api, money, newKey, when } from "../api";
import { useAction, useApi } from "../hooks";
import type { Beneficiary, Coverage, Mandate, RequestDetail } from "../types";
import Icon from "./Icon";
import { Avatar, ErrorNote, firstName, MoneyInput, Skeleton, StatusPill } from "./ui";

const ACTION: Record<string, { verb: string; preset: string }> = {
  airtime: { verb: "Buy airtime", preset: "5" },
  bundles: { verb: "Buy bundles", preset: "10" },
  cash: { verb: "Send cash", preset: "20" },
};

/** Shared-support shortcuts: what each product has used this period, who covered it, and a one-tap request. */
export default function QuickActions({ mandate, beneficiary, onChange }:
  { mandate: Mandate; beneficiary: Beneficiary; onChange: () => void }) {
  const coverage = useApi<Coverage[]>(`/mandates/${mandate.id}/coverage/?beneficiary=${beneficiary.id}`);
  const refresh = () => {
    void coverage.reload();
    onChange();
  };
  return (
    <section className="section" aria-labelledby={`qa-${beneficiary.id}`}>
      <div className="row" style={{ gap: 12 }}>
        <Avatar name={beneficiary.name} size="lg" />
        <div className="stack-sm" style={{ gap: 2 }}>
          <h2 id={`qa-${beneficiary.id}`}>Support for {firstName(beneficiary.name)}</h2>
          <span className="small muted">Everyone sees the same limits, so nobody tops up twice.</span>
        </div>
      </div>
      <ErrorNote error={coverage.error} />
      <div className="quick">
        {coverage.loading && !coverage.data && [0, 1, 2].map((i) => <Skeleton key={i} h={210} r={18} />)}
        {coverage.data?.map((c) => (
          <ProductTile key={c.product} c={c} mandate={mandate} beneficiary={beneficiary} onDone={refresh} />
        ))}
      </div>
    </section>
  );
}

function ProductTile({ c, mandate, beneficiary, onDone }:
  { c: Coverage; mandate: Mandate; beneficiary: Beneficiary; onDone: () => void }) {
  const action = ACTION[c.product] ?? { verb: `Send ${c.product}`, preset: "10" };
  const [amount, setAmount] = useState(action.preset);
  const [result, setResult] = useState<RequestDetail | null>(null);
  const { busy, error, run } = useAction();
  const cap = c.cap !== null ? Number(c.cap) : null;
  const used = Number(c.used);
  const left = cap !== null ? Math.max(0, cap - used) : null;
  const latest = c.covered_by[0];
  const coveredRecently = !!(latest && c.min_interval_hours &&
    Date.now() - new Date(latest.at).getTime() < c.min_interval_hours * 3600 * 1000);

  const send = () => run(async () => {
    const r = await api.post<RequestDetail>("/requests/", {
      mandate: mandate.id, beneficiary: beneficiary.id, product: c.product, amount, idempotency_key: newKey(),
    });
    setResult(r);
    onDone();
  });

  return (
    <div className="card tile">
      <div className="head">
        <span className="type-icon coral" style={{ width: 38, height: 38 }}><Icon name={c.product} size={20} /></span>
        <div className="stack-sm" style={{ gap: 0, flex: 1 }}>
          <strong style={{ textTransform: "capitalize" }}>{c.product}</strong>
          {cap !== null && <span className="xs muted num">{money(left ?? 0)} left this {c.period}</span>}
        </div>
      </div>
      {cap !== null && (
        <div className="meter thin" aria-label={`${money(used)} of ${money(cap)} used`}>
          <span style={{ width: `${Math.min(100, (used / cap) * 100)}%`, background: used >= cap ? "var(--bad)" : "var(--primary)" }} />
        </div>
      )}
      <div className="who">
        {latest
          ? <span className="row" style={{ gap: 8, flexWrap: "nowrap" }}><Avatar name={latest.by} size="sm" /><span>{firstName(latest.by)} sent {money(latest.amount)} · {when(latest.at)}</span></span>
          : <span className="muted">Nobody has sent {c.product} yet this {c.period}.</span>}
        {coveredRecently
          ? <span className="xs" style={{ display: "block", marginTop: 4, color: "var(--warn)", fontWeight: 700 }}>Already covered in the last {c.min_interval_hours} hours</span>
          : c.min_interval_hours ? <span className="xs muted" style={{ display: "block", marginTop: 4 }}>Once every {c.min_interval_hours} hours</span> : null}
      </div>
      <div className="actions">
        <MoneyInput id={`amt-${c.product}`} label={`${c.product} amount`} value={amount} onChange={setAmount} />
        <button className="btn primary" disabled={busy || Number(amount) <= 0 || left === 0} onClick={send}>
          {busy ? <span className="spinner" /> : null}{left === 0 ? "Limit reached" : action.verb}
        </button>
      </div>
      {result && (
        <div className="result">
          <div className="row between"><StatusPill status={result.status} /><a href={`#/requests/${result.id}`} className="small">Details</a></div>
          {result.status !== "APPROVED" && result.status !== "PAID" && result.decision && <span className="muted">{result.decision.reason.replace(/^Refused: /, "")}</span>}
        </div>
      )}
      <ErrorNote error={error} />
    </div>
  );
}
