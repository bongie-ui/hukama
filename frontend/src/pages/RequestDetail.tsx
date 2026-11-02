import { api, money, uploadUrl, when } from "../api";
import { requestTitle } from "../components/Activity";
import { ApprovalActions, FraudCard, RiskDetails } from "../components/Approval";
import Icon from "../components/Icon";
import Ledger from "../components/Ledger";
import { Avatar, ErrorNote, Notice, PageLoading, riskTone, SimTag, StatusPill, Who } from "../components/ui";
import { useAction, useApi, usePoll, useSession } from "../hooks";
import type { RequestDetail as Detail } from "../types";

const KIND: Record<string, string> = {
  QUOTE: "Quote", INVOICE: "Invoice", MILESTONE_PHOTO: "Progress photo", RECEIPT: "Receipt", OTHER: "File",
};

type Step = { label: string; sub: string; state: "done" | "current" | "stop" | "hold" | "" };

function steps(r: Detail): Step[] {
  const risk = r.risk;
  const tx = r.payment;
  const s = r.status;
  const decided: Step = s === "REFUSED" ? { label: "Rules", sub: "Refused", state: "stop" }
    : s === "ESCALATED" ? { label: "Rules", sub: "Needs a funder", state: "hold" }
    : s === "HELD_FRAUD" ? { label: "Rules", sub: "Held for a call home", state: "hold" }
    : s === "CONFIRMED_FRAUD" ? { label: "Rules", sub: "Reported as scam", state: "stop" }
    : ["APPROVED", "PAID", "FAILED"].includes(s) ? { label: "Rules", sub: "All rules passed", state: "done" }
    : { label: "Rules", sub: "Checking", state: "current" };
  const paid: Step = !tx ? { label: "PayPal payout", sub: "Not sent", state: "" }
    : tx.status === "SUCCESS" ? { label: "PayPal payout", sub: tx.simulated ? "Sent (simulated)" : "Sent", state: "done" }
    : tx.status === "PENDING" ? { label: "PayPal payout", sub: "Processing", state: "current" }
    : { label: "PayPal payout", sub: tx.status.toLowerCase(), state: "stop" };
  const lm = tx?.last_mile_status;
  const delivered: Step = !tx || tx.status !== "SUCCESS" ? { label: "Received", sub: "", state: "" }
    : lm === "DELIVERING" ? { label: "Received", sub: "Delivering to phone", state: "current" }
    : lm === "AWAITING_COLLECTION" ? { label: "Received", sub: "Ready to collect", state: "current" }
    : lm === "DELIVERED" ? { label: "Received", sub: "Delivered", state: "done" }
    : lm === "COLLECTED" ? { label: "Received", sub: "Cash collected", state: "done" }
    : { label: "Received", sub: `By ${r.payee_name ?? "payee"}`, state: "done" };
  return [
    { label: "Requested", sub: `By ${r.requester}`, state: "done" },
    { label: "Fraud check", sub: risk ? `${risk.level.toLowerCase()} risk` : "Running", state: risk ? (risk.level === "HIGH" ? "stop" : risk.level === "MEDIUM" ? "hold" : "done") : "current" },
    decided, paid, delivered,
  ];
}

export default function RequestDetail({ id }: { id: string }) {
  const { session } = useSession();
  const { data: r, error, reload, setData } = useApi<Detail>(`/requests/${id}/`);
  const collect = useAction();
  const moving = !!r && (r.status === "APPROVED" || r.payment?.status === "PENDING" || r.payment?.last_mile_status === "DELIVERING");
  usePoll(reload, 2500, moving);

  if (error) return <div className="page narrow"><ErrorNote error={error} /></div>;
  if (!r) return <PageLoading />;
  const decision = r.decisions[r.decisions.length - 1];
  const tx = r.payment;

  return (
    <div className="page narrow">
      <a href={`#/mandates/${r.mandate}`} className="back"><Icon name="back" size={16} />{r.mandate_title}</a>

      <header className="page-head">
        <div>
          <div className="row"><StatusPill status={r.status} />{r.payee_simulated && r.payment && <SimTag label={r.payment.simulated ? "Simulated rail" : "Simulated last mile"} />}</div>
          <h1>{requestTitle(r)}</h1>
          <div className="row small muted" style={{ gap: 8 }}>
            <Who name={r.requester} size="sm" />
            <span>{r.requester}{r.requester_phone && r.requester !== r.requester_phone ? ` · ${r.requester_phone}` : ""} · via {r.channel === "CHAT" ? "the assistant" : "the app"} · {when(r.created_at)}</span>
          </div>
        </div>
        <span className="amount lg">{money(r.amount, r.currency)}</span>
      </header>

      <div className="card"><ol className="stepper" aria-label="Progress">
        {steps(r).map((s) => (
          <li key={s.label} className={s.state}>
            <span className="bar" aria-hidden />
            <div><strong>{s.label}</strong><div className="s">{s.sub}</div></div>
          </li>
        ))}
      </ol></div>

      {r.status === "HELD_FRAUD" && r.risk && (
        <FraudCard r={r}><ApprovalActions r={r} onDone={setData} /></FraudCard>
      )}
      {r.status === "ESCALATED" && (
        <section className="card stack" style={{ borderColor: "var(--warn)" }}>
          <div className="row"><span className="icon-circle" style={{ background: "var(--warn-soft)", color: "var(--warn)" }}><Icon name="clock" /></span>
            <div className="stack-sm" style={{ gap: 2 }}><h3>Your decision is needed</h3><span className="small muted">{decision?.reason}</span></div></div>
          <ApprovalActions r={r} onDone={setData} />
        </section>
      )}
      {r.status === "CONFIRMED_FRAUD" && (
        <Notice tone="error" icon="shield">Reported as a scam. Nothing was paid, and the numbers involved are blocked for this family.</Notice>
      )}

      {tx && (
        <section className="card stack">
          <div className="row between">
            <h3>Payment</h3>
            {tx.simulated ? <SimTag /> : <span className="pill brand plain">PayPal Payout</span>}
          </div>
          {tx.last_mile_status === "AWAITING_COLLECTION" && (
            <div className="row between" style={{ padding: 14, borderRadius: 12, background: "var(--plum-tint)" }}>
              <div className="stack-sm" style={{ gap: 2 }}>
                <span className="small muted">Collection code sent to {r.beneficiary_name ?? "the beneficiary"}</span>
                <span className="amount lg" style={{ letterSpacing: ".12em" }}>{tx.collection_code}</span>
              </div>
              {session.demo_mode && (
                <button className="btn outline sm" disabled={collect.busy} onClick={() => collect.run(async () => {
                  await api.post(`/demo/last-mile/${tx.id}/collect/`, { code: tx.collection_code });
                  await reload();
                })}>Mark collected <SimTag label="Demo" /></button>
              )}
            </div>
          )}
          <dl className="kv">
            <dt>Paid to</dt><dd>{r.payee_name}</dd>
            <dt>Reference</dt><dd className="mono">{tx.reference}</dd>
            {tx.external_id && <><dt>PayPal batch</dt><dd className="mono">{tx.external_id}</dd></>}
          </dl>
          <ErrorNote error={collect.error} />
        </section>
      )}

      {decision && (
        <section className="card stack">
          <div className="row between">
            <h3>Why</h3>
            <span className="xs muted">{decision.decided_by === "POLICY" ? "Decided by the rules engine" : "After a funder's answer"}</span>
          </div>
          <p className="ink-2">{decision.reason}</p>
          <ul className="rules">
            {decision.rule_results.filter((x) => !(x.passed && x.detail.startsWith("Does not apply"))).map((x, i) => (
              <li key={i}>
                <span className={`rule-dot ${x.passed ? "pass" : "fail"}`}><Icon name={x.passed ? "check" : "x"} size={14} stroke={2.4} /></span>
                <span>{x.detail}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {r.message_text && r.status !== "HELD_FRAUD" && (
        <section className="card stack">
          <h3>Message</h3>
          <blockquote className="quote">“{r.message_text}”</blockquote>
          {r.summary_en && r.summary_en !== r.message_text && <span className="small muted">In English: {r.summary_en}</span>}
        </section>
      )}

      {r.evidence.length > 0 && (
        <section className="card stack">
          <div className="row" style={{ gap: 8 }}><Icon name="sparkle" size={18} /><h3>What the assistant read</h3></div>
          {r.evidence.map((e) => (
            <div key={e.id} className="evidence">
              {e.upload_id && e.content_type?.startsWith("image/")
                ? <a href={uploadUrl(e.upload_id)} target="_blank" rel="noreferrer"><img src={uploadUrl(e.upload_id)} alt={e.upload_name ?? KIND[e.kind]} /></a>
                : <span className="placeholder"><Icon name="doc" size={28} /></span>}
              <div className="stack-sm" style={{ minWidth: 0 }}>
                <strong>{KIND[e.kind] ?? e.kind}</strong>
                <Extracted data={e.extracted} ceilings={r.price_ceilings} />
              </div>
            </div>
          ))}
        </section>
      )}

      {r.risk && r.status !== "HELD_FRAUD" && (
        <section className="card stack">
          <div className="row between">
            <h3>Fraud check</h3>
            <span className={`pill ${riskTone(r.risk.level)}`}>{r.risk.level.toLowerCase()} risk · {r.risk.score}</span>
          </div>
          <RiskDetails r={r} />
        </section>
      )}

      {r.approvals.length > 0 && (
        <section className="card stack">
          <h3>Funder answers</h3>
          {r.approvals.map((a) => (
            <div key={a.id} className="row" style={{ alignItems: "flex-start", flexWrap: "nowrap" }}>
              <Avatar name={a.user_name} size="sm" />
              <div className="stack-sm" style={{ gap: 2 }}>
                <span className="small"><strong>{a.user_name}</strong> · {a.action.replace(/_/g, " ").toLowerCase()} · <span className="muted">{when(a.created_at)}</span></span>
                {a.note && <span className="small ink-2">“{a.note}”</span>}
              </div>
            </div>
          ))}
        </section>
      )}

      <section className="card stack">
        <h3>Audit trail</h3>
        <Ledger key={`${r.status}-${tx?.status}-${tx?.last_mile_status}`} query={`request=${r.id}`} />
      </section>
    </div>
  );
}

type Line = { name: string; key?: string; quantity?: number; unit_price?: number };

/** Same matching as the policy engine's price_ceiling rule: item key, or a keyword in the line's name. */
function overCeiling(line: Line, ceilings: Detail["price_ceilings"]) {
  return ceilings.some((c) => (line.key === c.item || c.keywords.some((k) => line.name?.toLowerCase().includes(k.toLowerCase())))
    && line.unit_price != null && line.unit_price > Number(c.max_unit_price));
}

function Extracted({ data, ceilings }: { data: Record<string, unknown>; ceilings: Detail["price_ceilings"] }) {
  if (!data || Object.keys(data).length === 0) {
    return <span className="small" style={{ color: "var(--warn)", fontWeight: 600 }}>Could not be read, so rules that need it fail. Send a clearer photo.</span>;
  }
  if ("verdict" in data) {
    const tone = data.verdict === "matches" ? "ok" : data.verdict === "unclear" ? "warn" : "bad";
    return (
      <div className="stack-sm small">
        <span className={`pill ${tone}`} style={{ alignSelf: "flex-start" }}>{data.verdict === "matches" ? "Matches the milestone" : String(data.verdict).replace(/_/g, " ")}</span>
        <span className="ink-2">Saw: {String(data.observed ?? "")}</span>
        {data.expected ? <span className="muted">Expected: {String(data.expected)}</span> : null}
      </div>
    );
  }
  const items = (data.items as Line[]) ?? [];
  return (
    <div className="stack-sm small">
      {data.supplier ? <span className="muted">From {String(data.supplier)}{data.date ? ` · ${String(data.date)}` : ""}</span> : null}
      <table className="lineitems">
        <tbody>
          {items.map((it, i) => (
            <tr key={i} className={overCeiling(it, ceilings) ? "over" : ""}>
              <td>{it.quantity ? `${it.quantity} × ` : ""}{it.name}</td>
              <td>{it.unit_price != null ? money(it.unit_price) : ""}</td>
            </tr>
          ))}
          {data.total != null && <tr><td><strong>Total</strong></td><td><strong>{money(data.total as number)}</strong></td></tr>}
        </tbody>
      </table>
    </div>
  );
}
