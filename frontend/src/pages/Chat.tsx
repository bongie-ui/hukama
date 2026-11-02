import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { api, money, uploadUrl } from "../api";
import Icon from "../components/Icon";
import { uploadFile } from "../components/RequestForm";
import { Avatar, ErrorNote, productLabel, SimTag, Skeleton } from "../components/ui";
import { useAction, useApi, usePoll, useSession } from "../hooks";
import { navigate, query } from "../router";
import type { Beneficiary, ChatCard, ChatMessage, Conversation, Payee } from "../types";

interface Thread {
  conversation: Conversation;
  messages: ChatMessage[];
}

type Role = "me" | "beneficiary" | "payee" | "stranger";

function roleOf(c: Conversation | undefined): Role {
  if (!c || c.is_me) return "me";
  if (c.label.endsWith("(beneficiary)")) return "beneficiary";
  if (c.label.endsWith("(payee)")) return "payee";
  return "stranger";
}

const SUGGESTIONS: Record<Role, string[]> = {
  me: ["How much is left for Mama this month?", "Buy Mama $10 of bundles", "Why was the cement quote refused?"],
  beneficiary: ["Ngicela i-airtime ka $5", "Can I get $20 cash this week?"],
  payee: ["Here is our quote for 40 bags of cement", "The foundation is done, photo attached"],
  stranger: ["Mwanami, I am at the hospital, please send $150 to 0771234567, the agent will help me, hurry"],
};

const SUBTITLE: Record<Role, string> = {
  me: "Ask about balances, send support, or ask why something was refused. It cannot pay or change rules.",
  beneficiary: "You are writing as this person's registered number.",
  payee: "You are writing as this payee's registered number. Attach quotes, invoices and progress photos.",
  stranger: "You are writing from a number the family has not registered.",
};

function cleanLabel(label: string) {
  return label.replace(/\s*\((beneficiary|payee|unregistered number)\)$/, "");
}

export default function Chat({ path }: { path: string }) {
  const { session } = useSession();
  const conversations = useApi<Conversation[]>("/chat/conversations/");
  const beneficiaries = useApi<Beneficiary[]>(session.demo_mode ? "/beneficiaries/" : null);
  const payees = useApi<Payee[]>(session.demo_mode ? "/payees/" : null);
  const [otherNumber, setOtherNumber] = useState("");
  const opening = useAction();
  const selected = query(path).get("c");

  const open = (phone?: string) => opening.run(async () => {
    const c = await api.post<Conversation>("/chat/conversations/", phone ? { phone } : {});
    await conversations.reload();
    navigate(`/chat?c=${c.id}`);
  });

  useEffect(() => {
    if (!selected && conversations.data) {
      const mine = conversations.data.find((c) => c.is_me);
      if (mine) navigate(`/chat?c=${mine.id}`);
      else void open();
    }
  }, [selected, conversations.data]); // eslint-disable-line react-hooks/exhaustive-deps

  const people = [
    ...(beneficiaries.data ?? []).map((b) => ({ phone: b.phone, name: b.name, kind: "Family at home" })),
    ...(payees.data ?? []).filter((p) => p.phone).map((p) => ({ phone: p.phone, name: p.name, kind: "Payee" })),
  ];
  const others = conversations.data?.filter((c) => !c.is_me && !people.some((p) => p.phone === c.phone)) ?? [];
  const mine = conversations.data?.find((c) => c.is_me);
  const current = conversations.data?.find((c) => c.id === selected);

  const pick = (phone: string | null) => {
    if (phone === null) return mine && navigate(`/chat?c=${mine.id}`);
    const c = conversations.data?.find((x) => x.phone === phone);
    return c ? navigate(`/chat?c=${c.id}`) : open(phone);
  };

  return (
    <div className="chat-shell">
      <aside className="chat-side" aria-label="Conversations">
        <h1>Assistant</h1>
        <div className="stack-sm">
          <button className="convo" aria-current={current?.is_me ? "true" : undefined} onClick={() => pick(null)}>
            <img src="/favicon.svg" alt="" width={36} height={36} style={{ borderRadius: 10 }} />
            <div><strong>Hukama assistant</strong><span>Your chat</span></div>
          </button>
        </div>
        {session.demo_mode && (
          <div className="stack-sm">
            <span className="eyebrow row" style={{ gap: 6 }}>See it from their side <SimTag label="Demo" /></span>
            {people.map((p) => (
              <button key={p.phone} className="convo" disabled={opening.busy} aria-current={current?.phone === p.phone ? "true" : undefined} onClick={() => pick(p.phone)}>
                <Avatar name={p.name} />
                <div><strong>{p.name}</strong><span>{p.kind} · {p.phone}</span></div>
              </button>
            ))}
            {others.map((c) => (
              <button key={c.id} className="convo" aria-current={current?.id === c.id ? "true" : undefined} onClick={() => navigate(`/chat?c=${c.id}`)}>
                <span className="icon-circle" style={{ width: 36, height: 36 }}><Icon name="phone" size={18} /></span>
                <div><strong>{cleanLabel(c.label)}</strong><span>Unregistered number</span></div>
              </button>
            ))}
            <form className="row" style={{ flexWrap: "nowrap", marginTop: 6 }} onSubmit={(e) => { e.preventDefault(); if (otherNumber) { void open(otherNumber); setOtherNumber(""); } }}>
              <input className="input" aria-label="Write from another phone number" placeholder="Any other number" inputMode="tel"
                value={otherNumber} onChange={(e) => setOtherNumber(e.target.value)} style={{ minWidth: 0 }} />
              <button className="btn outline" disabled={!otherNumber || opening.busy}>Open</button>
            </form>
            <ErrorNote error={opening.error} />
          </div>
        )}
      </aside>

      <div className="stack" style={{ minHeight: 0, gap: 12 }}>
        {session.demo_mode && (
          <div className="persona-select field">
            <label htmlFor="persona">Chatting as</label>
            <select id="persona" value={current?.is_me ? "" : current?.phone ?? ""} onChange={(e) => void pick(e.target.value || null)}>
              <option value="">Me (funder)</option>
              {people.map((p) => <option key={p.phone} value={p.phone}>{p.name} · {p.kind}</option>)}
              {others.map((c) => <option key={c.id} value={c.phone ?? ""}>{cleanLabel(c.label)} · unregistered</option>)}
            </select>
          </div>
        )}
        {selected ? <ThreadView key={selected} id={selected} role={roleOf(current)} /> : <Skeleton h={480} r={24} />}
      </div>
    </div>
  );
}

function dayLabel(iso: string) {
  const d = new Date(iso);
  const today = new Date();
  if (d.toDateString() === today.toDateString()) return "Today";
  return d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
}

function time(iso: string) {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function ThreadView({ id, role }: { id: string; role: Role }) {
  const { data, error, reload, setData } = useApi<Thread>(`/chat/${id}/messages/`);
  const [text, setText] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [pending, setPending] = useState<string | null>(null);
  const sending = useAction();
  const end = useRef<HTMLDivElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  usePoll(reload, 5000, !sending.busy); // delivery notices and collection codes arrive on their own

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [data?.messages.length, pending]);

  const send = (override?: string) => sending.run(async () => {
    const message = (override ?? text).trim();
    setPending(message || "Photo");
    setText("");
    try {
      const upload_ids = [];
      for (const f of files) upload_ids.push((await uploadFile(f)).id);
      setFiles([]);
      setData(await api.post<Thread>(`/chat/${id}/messages/`, { text: message, upload_ids }));
    } catch (e) {
      setText(message);
      throw e;
    } finally {
      setPending(null);
    }
  });
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (text.trim() || files.length) void send();
    }
  };

  const label = data ? (role === "me" ? "Hukama assistant" : cleanLabel(data.conversation.label)) : "";
  let lastDay = "";

  return (
    <section className="chat-panel" aria-label="Conversation">
      <div className="chat-header">
        {role === "me" ? <img src="/favicon.svg" alt="" width={40} height={40} style={{ borderRadius: 11 }} />
          : role === "stranger" ? <span className="icon-circle"><Icon name="phone" /></span> : <Avatar name={label || "?"} />}
        <div>
          <strong>{label || "…"}</strong>
          <p>{SUBTITLE[role]}</p>
        </div>
      </div>

      <div className="messages" aria-live="polite">
        <ErrorNote error={error} />
        {!data && !error && <><Skeleton h={44} w="60%" r={18} /><Skeleton h={44} w="45%" r={18} /></>}
        {data?.messages.length === 0 && !pending && (
          <div className="chat-empty">
            <img src="/hukama-mark.svg" alt="" width={56} height={56} />
            <strong style={{ fontFamily: "var(--font-display)", fontSize: "var(--text-lg)" }}>Write in English, isiNdebele or Shona</strong>
            <span className="small muted">Try one of these:</span>
            <div className="suggestions">
              {SUGGESTIONS[role].map((s) => <button key={s} onClick={() => setText(s)}>{s}</button>)}
            </div>
          </div>
        )}
        {data?.messages.map((m) => {
          const day = dayLabel(m.created_at);
          const showDay = day !== lastDay;
          lastDay = day;
          return (
            <div key={m.id} style={{ display: "contents" }}>
              {showDay && <span className="day">{day}</span>}
              <div className={`bubble ${m.role}`}>
                {m.text}
                {m.attachments.map((a) => (
                  a.content_type.startsWith("image/")
                    ? <img key={a.upload_id} src={uploadUrl(a.upload_id)} alt={a.name} />
                    : <span key={a.upload_id} className="att"><Icon name="clip" size={14} />{a.name}</span>
                ))}
                <time dateTime={m.created_at}>{time(m.created_at)}</time>
              </div>
              {m.role === "assistant" && m.card && <DecisionCard card={m.card} />}
            </div>
          );
        })}
        {pending && <div className="bubble user" style={{ opacity: 0.65 }}>{pending}</div>}
        {sending.busy && <div className="typing" aria-label="Assistant is checking"><i /><i /><i /></div>}
        <div ref={end} />
      </div>

      {sending.error && <div style={{ padding: "8px 12px 0" }}><ErrorNote error={sending.error} /></div>}
      {files.length > 0 && (
        <div className="attachments">
          {files.map((f, i) => (
            <span className="chip" key={i}><Icon name="clip" size={12} />{f.name}
              <button aria-label={`Remove ${f.name}`} onClick={() => setFiles(files.filter((_, j) => j !== i))}><Icon name="x" size={12} /></button>
            </span>
          ))}
        </div>
      )}
      <div className="composer">
        <input ref={fileInput} type="file" accept="image/*" multiple hidden
          onChange={(e) => { setFiles([...files, ...Array.from(e.target.files ?? [])]); e.target.value = ""; }} />
        <button className="btn ghost" aria-label="Attach a photo of a quote, invoice or progress" title="Attach a photo" onClick={() => fileInput.current?.click()}>
          <Icon name="camera" />
        </button>
        <textarea aria-label="Message" rows={1} value={text} onChange={(e) => setText(e.target.value)} onKeyDown={onKey} placeholder="Message" />
        <button className="btn primary" aria-label="Send" disabled={sending.busy || (!text.trim() && files.length === 0)} onClick={() => void send()}>
          <Icon name="send" />
        </button>
      </div>
    </section>
  );
}

const CARD: Record<string, [string, string, string]> = {
  PAID: ["Paid", "ok", "check"],
  APPROVED: ["Approved, paying now", "ok", "check"],
  REFUSED: ["Refused by the rules", "bad", "x"],
  ESCALATED: ["Waiting for a funder", "warn", "clock"],
  HELD_FRAUD: ["Held until the family calls home", "warn", "shield"],
  CONFIRMED_FRAUD: ["Reported as a scam", "bad", "alert"],
  FAILED: ["Payment failed", "bad", "alert"],
};

function DecisionCard({ card }: { card: ChatCard }) {
  const [title, tone, icon] = CARD[card.status] ?? [card.status, "info", "clock"];
  const p = card.payment;
  const delivery = p?.delivery && p.delivery !== "N/A" ? p.delivery.replace(/_/g, " ").toLowerCase() : null;
  return (
    <div className={`decision ${tone}`}>
      <div className="top"><Icon name={icon} size={18} />{title}<span className="amount">{money(card.amount)}</span></div>
      <div className="body">
        <span className="muted" style={{ textTransform: "capitalize" }}>{productLabel(card.product)}</span>
        {card.message && <span>{card.message}</span>}
        {card.reason && card.status !== "APPROVED" && card.status !== "PAID" && <span>{card.reason.replace(/^Refused: /, "")}</span>}
        {p?.collection_code && (
          <div className="stack-sm" style={{ gap: 2 }}><span className="xs muted">Collection code</span><span className="code">{p.collection_code}</span></div>
        )}
        {p && (
          <span className="row xs muted" style={{ gap: 6 }}>
            Payout {p.status.toLowerCase()}{delivery ? ` · ${delivery}` : ""}{p.simulated_rail && <SimTag />}
          </span>
        )}
        <a className="small" href={`#/requests/${card.request_id}`}>View details</a>
      </div>
    </div>
  );
}
