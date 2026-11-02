import { money } from "../api";
import { ActivityList } from "../components/Activity";
import Icon, { TYPE_ICON } from "../components/Icon";
import { Avatar, Empty, ErrorNote, firstName, LoadingCards, Money, splitType } from "../components/ui";
import { useApi, useSession } from "../hooks";
import type { Mandate, PayRequest } from "../types";

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

export default function Home() {
  const { session } = useSession();
  const mandates = useApi<Mandate[]>("/mandates/");
  const recent = useApi<PayRequest[]>("/requests/");
  const inbox = useApi<PayRequest[]>("/requests/?inbox=1");

  const available = mandates.data?.reduce((s, m) => s + Number(m.balance), 0) ?? 0;
  const funded = mandates.data?.reduce((s, m) => s + Number(m.funded), 0) ?? 0;
  const monthStart = new Date(new Date().getFullYear(), new Date().getMonth(), 1);
  const sentThisMonth = recent.data
    ?.filter((r) => (r.status === "PAID" || r.status === "APPROVED") && new Date(r.created_at) >= monthStart)
    .reduce((s, r) => s + Number(r.amount), 0) ?? 0;

  return (
    <div className="page">
      <div className="page-head">
        <div className="hello">
          <span className="eyebrow">{session.user?.family?.name}</span>
          <h1>{greeting()}, {firstName(session.user?.name ?? "")}</h1>
        </div>
        <a className="btn primary" href="#/mandates/new"><Icon name="plus" />New mandate</a>
      </div>

      <Attention items={inbox.data} />

      <div className="stats">
        <div className="card stat hero">
          <span className="eyebrow">Available to spend</span>
          <Money value={available} size="xl" />
          <span className="small muted">across {mandates.data?.length ?? 0} mandates, of {money(funded)} funded</span>
        </div>
        <div className="card stat">
          <span className="eyebrow">Sent this month</span>
          <Money value={sentThisMonth} size="lg" />
          <span className="small muted">paid out under your rules</span>
        </div>
        <div className="card stat">
          <span className="eyebrow">Family</span>
          <div className="avatars" style={{ marginTop: 4 }}>
            {unique(mandates.data?.flatMap((m) => m.funders.map((f) => f.name)) ?? []).map((n) => <Avatar key={n} name={n} title={n} />)}
          </div>
          <span className="small muted">supporting home together</span>
        </div>
      </div>

      <section className="section" aria-labelledby="mandates-h">
        <div className="section-head">
          <h2 id="mandates-h">Mandates</h2>
          <span className="small muted">Money set aside, with rules for how it may be spent</span>
        </div>
        <ErrorNote error={mandates.error} />
        {mandates.loading && !mandates.data && <LoadingCards />}
        {mandates.data?.length === 0 && (
          <div className="card"><Empty icon="sparkle" title="No mandates yet">
            Describe what the money is for and the assistant drafts the rules. <a href="#/mandates/new">Create one</a>
          </Empty></div>
        )}
        <div className="grid-cards">{mandates.data?.map((m) => <MandateCard key={m.id} m={m} />)}</div>
      </section>

      <section className="section" aria-labelledby="activity-h">
        <div className="section-head"><h2 id="activity-h">Recent activity</h2></div>
        <ErrorNote error={recent.error} />
        <ActivityList items={recent.data?.slice(0, 8) ?? null} loading={recent.loading} empty="No requests yet" />
      </section>
    </div>
  );
}

function unique<T>(xs: T[]) {
  return [...new Set(xs)];
}

function Attention({ items }: { items: PayRequest[] | null }) {
  if (!items) return null;
  const fraud = items.filter((r) => r.status === "HELD_FRAUD").length;
  const approvals = items.length - fraud;
  if (items.length === 0) {
    return (
      <div className="attention calm">
        <span className="icon-circle"><Icon name="check" /></span>
        <div><strong>All clear</strong><span className="small">Nothing needs your decision right now.</span></div>
      </div>
    );
  }
  return (
    <a className={`attention ${fraud ? "" : "warn"}`} href="#/inbox" style={{ textDecoration: "none" }}>
      <span className="icon-circle"><Icon name={fraud ? "alert" : "clock"} /></span>
      <div>
        <strong>{fraud ? `${fraud} possible scam${fraud > 1 ? "s" : ""} held` : `${approvals} request${approvals > 1 ? "s" : ""} need${approvals > 1 ? "" : "s"} you`}</strong>
        <span className="small">
          {fraud ? "Nothing is paid until a funder calls home on the registered number." : "Over an approval limit or flagged as unusual."}
          {fraud && approvals ? ` Plus ${approvals} waiting for approval.` : ""}
        </span>
      </div>
      <span className="btn sm" style={{ background: "var(--surface)" }}>Review<Icon name="chevron" size={16} /></span>
    </a>
  );
}

export function FunderMeter({ m }: { m: Mandate }) {
  const total = Number(m.funded) || 1;
  const spent = Math.max(0, Number(m.funded) - Number(m.balance));
  return (
    <div className="stack-sm">
      <div className="meter" aria-hidden>
        <span style={{ width: `${(spent / total) * 100}%`, background: "var(--coral)" }} />
      </div>
      <div className="row between xs muted">
        <span>{money(spent, m.currency)} spent</span>
        <span>{money(m.funded, m.currency)} funded</span>
      </div>
    </div>
  );
}

function MandateCard({ m }: { m: Mandate }) {
  const [name, kind] = splitType(m.type_label);
  return (
    <a className="card mandate-card" href={`#/mandates/${m.id}`}>
      <div className="mandate-top">
        <span className={`type-icon ${m.type === "ISIKHWAMA" ? "coral" : ""}`}><Icon name={TYPE_ICON[m.type] ?? "wallet"} size={22} /></span>
        <div style={{ minWidth: 0, flex: 1 }}>
          <span className="eyebrow">{name} · {kind}</span>
          <h3>{m.title}</h3>
        </div>
      </div>
      <div className="stack-sm">
        <span className="xs muted">Available</span>
        <Money value={m.balance} currency={m.currency} size="lg" />
      </div>
      <FunderMeter m={m} />
      <div className="foot">
        <div className="avatars">{m.funders.map((f) => <Avatar key={f.user_id} name={f.name} size="sm" title={f.name} />)}</div>
        {m.pending > 0 ? <span className="pill warn">{m.pending} waiting</span>
          : !m.signature_valid ? <span className="pill bad">Signature broken</span>
          : <span className="seal"><Icon name="lock" size={14} />Signed v{m.version}</span>}
      </div>
    </a>
  );
}
