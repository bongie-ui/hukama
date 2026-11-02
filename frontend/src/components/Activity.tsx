import { money, when } from "../api";
import type { PayRequest } from "../types";
import { Empty, firstName, paymentSummary, productLabel, Skeleton, StatusPill, Who } from "./ui";

export function requestTitle(r: PayRequest) {
  const what = productLabel(r.product);
  if (r.beneficiary_name) return `${what[0].toUpperCase()}${what.slice(1)} for ${firstName(r.beneficiary_name)}`;
  if (r.payee_name) return `${what[0].toUpperCase()}${what.slice(1)} to ${r.payee_name}`;
  return what;
}

export function ActivityItem({ r, showMandate = true }: { r: PayRequest; showMandate?: boolean }) {
  const pay = r.status === "PAID" ? paymentSummary(r.payment) : null;
  return (
    <a className="list-item" href={`#/requests/${r.id}`}>
      <Who name={r.requester} />
      <div className="main">
        <span className="title">{requestTitle(r)}</span>
        <span className="sub">
          {r.requester} · {when(r.created_at)}{showMandate ? ` · ${r.mandate_title}` : ""}
        </span>
      </div>
      <div className="end">
        <span className="num" style={{ fontWeight: 700 }}>{money(r.amount, r.currency)}</span>
        {pay ? <span className={`pill ${pay[1]}`}>{pay[0]}</span> : <StatusPill status={r.status} />}
      </div>
    </a>
  );
}

export function ActivityList({ items, loading, showMandate = true, empty = "Nothing yet" }:
  { items: PayRequest[] | null; loading?: boolean; showMandate?: boolean; empty?: string }) {
  if (loading && !items) {
    return <div className="card flush"><div className="stack" style={{ padding: 18 }}>{[0, 1, 2].map((i) => <Skeleton key={i} h={44} />)}</div></div>;
  }
  if (!items || items.length === 0) return <div className="card"><Empty icon="clock" title={empty} /></div>;
  return (
    <div className="card flush">
      <div className="list">{items.map((r) => <ActivityItem key={r.id} r={r} showMandate={showMandate} />)}</div>
    </div>
  );
}
