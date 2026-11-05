import { money, when } from "../api";
import { requestTitle } from "../components/Activity";
import { ApprovalActions, FraudCard } from "../components/Approval";
import Icon from "../components/Icon";
import InvoiceCard from "../components/InvoiceCard";
import { Avatar, Empty, ErrorNote, riskTone, Skeleton } from "../components/ui";
import { useApi } from "../hooks";
import type { PayRequest } from "../types";

/** Escalations and fraud holds on mandates this funder funds. Scams first. */
export default function Inbox() {
  const { data, error, loading, reload } = useApi<PayRequest[]>("/requests/?inbox=1");
  const sorted = [...(data ?? [])].sort((a, b) => Number(b.status === "HELD_FRAUD") - Number(a.status === "HELD_FRAUD"));

  return (
    <div className="page narrow">
      <header className="page-head">
        <div>
          <h1>Approvals</h1>
          <p>Requests the rules held back for the family: possible scams, anything over an approval limit, and shopping lists the fund couldn't cover.</p>
        </div>
      </header>
      <ErrorNote error={error} />
      {loading && !data && <div className="stack"><Skeleton h={260} r={18} /><Skeleton h={160} r={18} /></div>}
      {data?.length === 0 && (
        <div className="card"><Empty icon="shield" title="Nothing is waiting for you">When a request needs a funder, it appears here and on everyone's phone.</Empty></div>
      )}
      <div className="stack" style={{ gap: 20 }}>
        {sorted.map((r) =>
          r.status === "INVOICED" ? <InvoiceCard key={r.id} r={r} onDone={() => reload()} /> :
          r.status === "HELD_FRAUD" && r.risk ? (
            <FraudCard key={r.id} r={r}>
              <ApprovalActions r={r} onDone={() => reload()} />
              <a className="small" href={`#/requests/${r.id}`}>Open the full request</a>
            </FraudCard>
          ) : (
            <article key={r.id} className="card stack" style={{ borderColor: "var(--warn)" }}>
              <div className="row between" style={{ flexWrap: "nowrap", alignItems: "flex-start" }}>
                <div className="row" style={{ flexWrap: "nowrap", minWidth: 0 }}>
                  <Avatar name={r.requester} />
                  <div className="stack-sm" style={{ gap: 2, minWidth: 0 }}>
                    <h3>{requestTitle(r)}</h3>
                    <span className="small muted">{r.requester} · {r.mandate_title} · {when(r.created_at)}</span>
                  </div>
                </div>
                <span className="amount md">{money(r.amount, r.currency)}</span>
              </div>
              <div className="notice warn"><Icon name="clock" size={18} /><div>{r.decision?.reason}</div></div>
              {r.message_text && <blockquote className="quote">“{r.message_text}”</blockquote>}
              {r.risk && r.risk.level !== "LOW" && <span className={`pill ${riskTone(r.risk.level)}`} style={{ alignSelf: "flex-start" }}>{r.risk.level.toLowerCase()} risk · {r.risk.score}</span>}
              <ApprovalActions r={r} onDone={() => reload()} />
            </article>
          ),
        )}
      </div>
    </div>
  );
}
