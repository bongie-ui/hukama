import { api, money, when } from "../api";
import { ActivityList } from "../components/Activity";
import Icon, { TYPE_ICON } from "../components/Icon";
import { Avatar, Empty, ErrorNote, firstName, LoadingCards, Money, splitType } from "../components/ui";
import { useApi, useSession } from "../hooks";
import { useState } from "react";
import type { Beneficiary, Family, Mandate, Payee, PayRequest } from "../types";

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
        <a className="btn primary" href="#/mandates/new" data-tour="new-mandate"><Icon name="plus" />New mandate</a>
      </div>

      <GettingStarted mandates={mandates.data} />
      <Attention items={inbox.data} />
      <Notifications />

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

/** For a new family: the five steps to the first payment. Hidden once done (or dismissed on this device). */
function GettingStarted({ mandates }: { mandates: Mandate[] | null }) {
  const { session } = useSession();
  const beneficiaries = useApi<Beneficiary[]>("/beneficiaries/");
  const payees = useApi<Payee[]>("/payees/");
  const family = useApi<Family>("/family/");
  const key = `hukama-start-hidden-${session.user?.id}`;
  const [hidden, setHidden] = useState(() => { try { return !!localStorage.getItem(key); } catch { return false; } });
  if (!mandates || !beneficiaries.data || !payees.data || !family.data || hidden) return null;
  const funded = mandates.find((m) => Number(m.funded) > 0);
  const steps = [
    { done: beneficiaries.data.length > 0, title: "Add someone you support at home", sub: "Their registered phone number is the one Hukama trusts.", href: "#/people" },
    { done: payees.data.some((p) => !p.shared), title: "Add who gets paid", sub: "A school, builder or shop with a PayPal account. Hukama checks each payee before it can be paid.", href: "#/people" },
    { done: mandates.length > 0, title: "Create a mandate", sub: "Describe the purpose in plain words; the assistant drafts the rules.", href: "#/mandates/new" },
    { done: !!funded, title: "Fund it with PayPal", sub: "Money only counts once PayPal confirms it.", href: mandates[0] ? `#/mandates/${mandates[0].id}` : "#/mandates/new" },
    { done: family.data.members.length > 1, title: "Invite your family", sub: "Brothers and sisters abroad can fund the same mandate and share its limits.", href: "#/people" },
  ];
  const left = steps.filter((s) => !s.done).length;
  if (left === 0) return null;
  const hide = () => { setHidden(true); try { localStorage.setItem(key, "1"); } catch { /* ignore */ } };
  return (
    <section className="card stack" aria-labelledby="start-h" style={{ gap: 12 }}>
      <div className="row between">
        <div className="stack-sm" style={{ gap: 2 }}>
          <h2 id="start-h">Getting started</h2>
          <span className="small muted">{steps.length - left} of {steps.length} done. Five steps to your first payment.</span>
        </div>
        <button className="linkbtn small" onClick={hide}>Hide</button>
      </div>
      <div className="meter thin"><span style={{ width: `${((steps.length - left) / steps.length) * 100}%`, background: "var(--primary)" }} /></div>
      <ol className="checklist">
        {steps.map((s) => (
          <li key={s.title} className={s.done ? "done" : ""}>
            <a href={s.href}>
              <span className="tick">{s.done ? <Icon name="check" size={14} stroke={2.6} /> : null}</span>
              <span className="stack-sm" style={{ gap: 0, minWidth: 0 }}><span className="title" style={{ fontWeight: 700 }}>{s.title}</span><span className="xs muted">{s.sub}</span></span>
              {!s.done && <Icon name="chevron" size={16} />}
            </a>
          </li>
        ))}
      </ol>
    </section>
  );
}

interface NotificationList { unread: number; items: { id: string; text: string; request: string | null; read: boolean; created_at: string }[] }

/** In-app messages: shopping lists to pay, and when someone else covered one. */
function Notifications() {
  const n = useApi<NotificationList>("/notifications/");
  const unread = n.data?.items.filter((i) => !i.read) ?? [];
  if (!unread.length) return null;
  const markRead = async () => {
    await api.post("/notifications/read/");
    void n.reload();
  };
  return (
    <section className="card stack" aria-label="Notifications" style={{ gap: 10 }}>
      <div className="row between">
        <strong className="row" style={{ gap: 8 }}><Icon name="chat" size={18} />For you</strong>
        <button className="linkbtn small" onClick={markRead}>Mark as read</button>
      </div>
      <div className="list">
        {unread.slice(0, 5).map((i) => (
          <a key={i.id} className="list-item" style={{ paddingInline: 0 }} href={i.request ? `#/requests/${i.request}` : "#/inbox"}>
            <div className="main"><span className="title" style={{ fontWeight: 600 }}>{i.text}</span><span className="sub">{when(i.created_at)}</span></div>
          </a>
        ))}
      </div>
    </section>
  );
}

function Attention({ items }: { items: PayRequest[] | null }) {
  if (!items) return null;
  const fraud = items.filter((r) => r.status === "HELD_FRAUD").length;
  const lists = items.filter((r) => r.status === "INVOICED").length;
  const approvals = items.length - fraud - lists;
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
        <strong>{fraud ? `${fraud} possible scam${fraud > 1 ? "s" : ""} held`
          : approvals ? `${approvals} request${approvals > 1 ? "s" : ""} need${approvals > 1 ? "" : "s"} you`
          : `${lists} shopping list${lists > 1 ? "s" : ""} to pay`}</strong>
        <span className="small">
          {fraud ? "Nothing is paid until a funder calls home on the registered number."
            : approvals ? "Over an approval limit or flagged as unusual." : "The support fund couldn't cover it. The first to pay covers it."}
          {fraud && approvals ? ` Plus ${approvals} waiting for approval.` : ""}
          {(fraud || approvals) && lists ? ` Plus ${lists} shopping list${lists > 1 ? "s" : ""} to pay.` : ""}
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
