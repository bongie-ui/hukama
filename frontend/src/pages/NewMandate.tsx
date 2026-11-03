import { useEffect, useState } from "react";
import { api } from "../api";
import Icon, { TYPE_ICON } from "../components/Icon";
import { Avatar, ErrorNote, splitType } from "../components/ui";
import { useAction, useApi, useSession } from "../hooks";
import { navigate } from "../router";
import type { Draft, Family, Mandate, Rule } from "../types";

const EXAMPLES = [
  { label: "Build a house", icon: "build", text: "Up to $600 for cement and bricks for the house back home. Pay the hardware store directly, only after a photo shows the foundation is done. Cement no more than $11 a bag." },
  { label: "School fees", icon: "school", text: "Pay the term fees directly to the school, only on the school's invoice, up to $400 a term." },
  { label: "Support a parent", icon: "heart", text: "We share our mother's airtime, data bundles and cash. Bundles up to $30 a month and not twice in one day, airtime $20 a month, cash $100 a month. Anything over $50 needs one of us to approve." },
];
const NUMBER_PARAMS: Record<string, string> = { amount: "Amount ($)", max_unit_price: "Max price each ($)", hours: "Hours" };

export default function NewMandate() {
  const { session } = useSession();
  const family = useApi<Family>("/family/");
  const [text, setText] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [title, setTitle] = useState("");
  const [rules, setRules] = useState<Rule[]>([]);
  const [errors, setErrors] = useState<string[]>([]);
  const [coFunders, setCoFunders] = useState<number[]>([]);
  const drafting = useAction();
  const saving = useAction();

  const makeDraft = () => drafting.run(async () => {
    const d = await api.post<Draft>("/mandates/draft/", { text });
    setDraft(d);
    setTitle(d.title);
    setRules(d.rules);
    setErrors(d.errors);
  });

  // Re-validate and re-describe whenever the funder edits the rules.
  const ruleKey = JSON.stringify(rules.map((r) => [r.kind, r.params]));
  useEffect(() => {
    if (!draft) return;
    const t = window.setTimeout(async () => {
      try {
        const res = await api.post<{ errors: string[]; rules: Rule[] }>("/mandates/preview-rules/", {
          type: draft.type, rules: rules.map(({ kind, params }) => ({ kind, params })),
        });
        setErrors(res.errors);
        setRules((current) => current.map((r, i) => ({ ...r, text: res.rules[i]?.text ?? r.text })));
      } catch {
        /* signing reports errors too */
      }
    }, 350);
    return () => window.clearTimeout(t);
  }, [draft, ruleKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const setParam = (i: number, name: string, value: string) =>
    setRules((rs) => rs.map((r, j) => (j === i ? { ...r, params: { ...r.params, [name]: Number(value) } } : r)));
  const removeRule = (i: number) => setRules((rs) => rs.filter((_, j) => j !== i));

  const confirm = () => saving.run(async () => {
    const m = await api.post<Mandate>("/mandates/", {
      type: draft!.type, title, purpose_text: draft!.purpose_text,
      rules: rules.map(({ kind, params }) => ({ kind, params })), co_funder_ids: coFunders,
    });
    navigate(`/mandates/${m.id}`);
  });

  const others = family.data?.members.filter((m) => m.user_id !== session.user?.id) ?? [];
  const stage = draft ? 2 : 1;
  const [typeName, typeKind] = draft ? splitType(draft.type_label) : ["", ""];

  return (
    <div className="page narrow">
      <a href="#/" className="back"><Icon name="back" size={16} />Home</a>
      <header className="page-head">
        <div>
          <h1>New mandate</h1>
          <div className="steps-mini" aria-label="Steps">
            <span className={stage === 1 ? "on" : ""}>1 Describe</span><i /><span className={stage === 2 ? "on" : ""}>2 Review rules</span><i /><span>3 Sign</span>
          </div>
        </div>
      </header>

      <section className="card stack" style={{ gap: 16 }}>
        <div className="field">
          <label htmlFor="purpose">In your own words: what is the money for, and how may it be spent?</label>
          <textarea id="purpose" rows={4} value={text} onChange={(e) => setText(e.target.value)}
            placeholder="e.g. Up to $600 for cement for the house. Pay the hardware store directly after a photo of the foundation." />
        </div>
        {!text && (
          <div className="stack-sm">
            <span className="xs muted">Or start from an example</span>
            <div className="row" style={{ gap: 8 }}>
              {EXAMPLES.map((ex) => (
                <button key={ex.label} className="btn outline sm" onClick={() => setText(ex.text)}><Icon name={ex.icon} size={16} />{ex.label}</button>
              ))}
            </div>
          </div>
        )}
        <div className="row between">
          <span className="xs muted row" style={{ gap: 6 }}><Icon name="sparkle" size={14} />The assistant drafts; nothing is saved until you sign.</span>
          <button className="btn primary" disabled={drafting.busy || text.trim().length < 10} onClick={makeDraft}>
            {drafting.busy ? <><span className="spinner" />Drafting rules…</> : draft ? "Draft again" : <>Draft the rules<Icon name="chevron" size={16} /></>}
          </button>
        </div>
        <ErrorNote error={drafting.error} />
      </section>

      {draft && (
        <section className="card stack" style={{ gap: 18 }} aria-labelledby="review-h">
          <div className="row" style={{ flexWrap: "nowrap" }}>
            <span className="type-icon"><Icon name={TYPE_ICON[draft.type] ?? "wallet"} size={22} /></span>
            <div className="stack-sm" style={{ gap: 2 }}>
              <span className="eyebrow">{typeName} · {typeKind}</span>
              <h2 id="review-h">Review the rules</h2>
            </div>
          </div>
          {draft.explanation && <div className="ai-note"><Icon name="sparkle" size={18} /><span>{draft.explanation}</span></div>}

          <div className="field">
            <label htmlFor="title">Name</label>
            <input id="title" value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>

          <div>
            {rules.map((r, i) => (
              <div key={i} className="draft-rule">
                <span className="rule-dot"><Icon name="check" size={14} stroke={2.4} /></span>
                <div className="body">
                  <span>{r.text}</span>
                  {Object.keys(r.params).some((k) => k in NUMBER_PARAMS) && (
                    <div className="params">
                      {Object.entries(r.params).filter(([k]) => k in NUMBER_PARAMS).map(([k, v]) => (
                        <div className="field" key={k}>
                          <label htmlFor={`p-${i}-${k}`} className="xs">{NUMBER_PARAMS[k]}</label>
                          <input id={`p-${i}-${k}`} type="number" min="0" step="any" value={String(v)} onChange={(e) => setParam(i, k, e.target.value)} />
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                <button className="btn ghost sm" onClick={() => removeRule(i)} aria-label={`Remove rule: ${r.text}`}><Icon name="x" size={16} /></button>
              </div>
            ))}
          </div>

          {draft.questions.length > 0 && (
            <div className="notice info"><Icon name="sparkle" size={18} /><div><strong>The assistant needs to know</strong>
              <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>{draft.questions.map((q) => <li key={q}>{q}</li>)}</ul></div></div>
          )}
          {errors.length > 0 && (
            <div className="notice warn"><Icon name="alert" size={18} /><div><strong>Fix before signing</strong>
              <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>{errors.map((e) => <li key={e}>{e}</li>)}</ul></div></div>
          )}

          {others.length > 0 && (
            <div className="field">
              <span className="label">Who funds it with you?</span>
              <div className="checks">
                {others.map((m) => (
                  <label key={m.user_id} className="check">
                    <input type="checkbox" checked={coFunders.includes(m.user_id)}
                      onChange={(e) => setCoFunders((c) => (e.target.checked ? [...c, m.user_id] : c.filter((x) => x !== m.user_id)))} />
                    <Avatar name={m.name} size="sm" />{m.name}
                  </label>
                ))}
              </div>
            </div>
          )}

          <hr className="divider" />
          <div className="stack-sm">
            <button className="btn primary lg" disabled={saving.busy || errors.length > 0 || !title.trim()} onClick={confirm}>
              {saving.busy ? <span className="spinner" /> : <Icon name="lock" size={18} />}Sign and create mandate
            </button>
            <span className="xs muted">Signing locks these rules. Any later change needs the owner and creates a new signed version.</span>
          </div>
          <ErrorNote error={saving.error} />
        </section>
      )}
    </div>
  );
}
