import { useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "../api";
import Icon from "./Icon";

interface Msg { role: "user" | "assistant"; content: string }

const STARTERS = ["What is Hukama?", "I'm a school: how do I send an invoice?", "How do I shop with my PIN?"];

/** "Ask Hukama": a guide for anyone on the public pages. It sees no family's data and can't pay or change anything. */
export default function PublicAssistant() {
  const [open, setOpen] = useState(false);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [msgs, open]);

  const ask = async (q: string) => {
    if (!q.trim() || busy) return;
    const next: Msg[] = [...msgs, { role: "user", content: q.trim() }];
    setMsgs(next);
    setText("");
    setBusy(true);
    try {
      const r = await api.post<{ reply: string }>("/public/assistant/", { messages: next });
      setMsgs([...next, { role: "assistant", content: r.reply }]);
    } catch (e) {
      setMsgs([...next, { role: "assistant", content: (e as Error).message }]);
    } finally {
      setBusy(false);
    }
  };
  const submit = (e: FormEvent) => { e.preventDefault(); void ask(text); };

  if (!open) {
    return <button className="ask-fab" onClick={() => setOpen(true)} aria-label="Ask Hukama"><Icon name="chat" size={20} />Ask Hukama</button>;
  }
  return (
    <section className="ask-panel card" role="dialog" aria-label="Ask Hukama">
      <div className="row between" style={{ flexWrap: "nowrap" }}>
        <strong className="row" style={{ gap: 8 }}><img src="/favicon.svg" alt="" width={24} height={24} />Ask Hukama</strong>
        <button className="btn ghost icon-only sm" onClick={() => setOpen(false)} aria-label="Close"><Icon name="x" size={18} /></button>
      </div>
      <div className="ask-msgs" aria-live="polite">
        {msgs.length === 0 && (
          <div className="stack-sm">
            <span className="small ink-2">Questions about Hukama, sending an invoice or shopping from home. I can't see any family's money.</span>
            {STARTERS.map((s) => <button key={s} className="btn outline sm" style={{ alignSelf: "flex-start" }} onClick={() => void ask(s)}>{s}</button>)}
          </div>
        )}
        {msgs.map((m, i) => <div key={i} className={`ask-msg ${m.role}`}>{m.content.replace(/\*\*/g, "")}</div>)}
        {busy && <div className="ask-msg assistant"><span className="spinner" /></div>}
        <div ref={end} />
      </div>
      <form className="row" style={{ flexWrap: "nowrap", gap: 8 }} onSubmit={submit}>
        <input className="input" aria-label="Your question" placeholder="Ask a question" value={text} onChange={(e) => setText(e.target.value)} maxLength={1000} style={{ minWidth: 0 }} />
        <button className="btn primary" disabled={busy || !text.trim()} aria-label="Send"><Icon name="send" size={18} /></button>
      </form>
    </section>
  );
}
