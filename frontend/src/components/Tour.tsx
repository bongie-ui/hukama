import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import Icon from "./Icon";

export interface TourStep {
  /** data-tour value of the element to point at; omitted = a centred card. */
  target?: string;
  title: string;
  body: string;
}

export const MAIN_TOUR: TourStep[] = [
  { title: "Welcome to Hukama", body: "Hukama sends money home with rules attached. The family agrees how money may be spent, and Hukama pays the school, builder, shop or mobile money directly, only when those rules are met. This takes one minute." },
  { target: "nav-home", title: "Home", body: "What is available to spend, what is waiting for you, and every mandate your family has set up." },
  { target: "new-mandate", title: "Mandates: money with a purpose", body: "A mandate is one purpose with its rules: school fees paid only to the school, building materials under a price limit, or support for someone at home with monthly limits. Describe it in plain words; the assistant drafts the rules, you check them and sign." },
  { target: "nav-inbox", title: "Approvals", body: "Possible scams are held here until someone calls home on the registered number. You also see requests over a limit, and shopping lists the fund couldn't cover. The first person to pay covers it, and the others are told." },
  { target: "nav-people", title: "People", body: "Who you support at home, who can be paid, and your family. Give a school or builder an upload link to send invoices (they log in with PayPal), and give someone at home a shop link with a PIN." },
  { target: "nav-chat", title: "Assistant", body: "Ask in any language: \"How much is left for bundles this month?\" or send a photo of a quote. It can record requests, but it can never pay, approve or change rules." },
  { target: "nav-dashboard", title: "Dashboard", body: "Where the money came from and where it went, by person, mandate and category. Ask the AI to build a chart for you." },
  { title: "The rule that keeps money safe", body: "The AI suggests, the rules decide, and PayPal pays. Nobody, not even the assistant, can pay someone the rules don't allow. You can replay this tour any time from \"Take the tour\"." },
];

function visible(target: string) {
  return [...document.querySelectorAll<HTMLElement>(`[data-tour="${target}"]`)]
    .find((el) => el.offsetParent !== null && el.getBoundingClientRect().width > 0) ?? null;
}

/** A step-by-step walkthrough that spotlights parts of the app. Esc or Skip closes it. */
export default function Tour({ steps, onClose }: { steps: TourStep[]; onClose: () => void }) {
  const [i, setI] = useState(0);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const next = useRef<HTMLButtonElement>(null);
  const step = steps[i];
  const last = i === steps.length - 1;

  const measure = useCallback(() => {
    const el = step.target ? visible(step.target) : null;
    if (el) el.scrollIntoView({ block: "nearest" });
    setRect(el ? el.getBoundingClientRect() : null);
  }, [step]);

  useLayoutEffect(measure, [measure]);
  useEffect(() => {
    next.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight" && !last) setI((n) => n + 1);
      if (e.key === "ArrowLeft" && i > 0) setI((n) => n - 1);
    };
    window.addEventListener("resize", measure);
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("resize", measure); window.removeEventListener("keydown", onKey); };
  }, [measure, onClose, last, i]);

  // Put the card beside the target (below it, or above when there is no room), kept inside the screen.
  const pad = 8;
  const width = Math.min(340, window.innerWidth - 32);
  let style: React.CSSProperties = { width, left: "50%", top: "50%", transform: "translate(-50%, -50%)" };
  if (rect) {
    const left = Math.max(16, Math.min(window.innerWidth - width - 16, rect.left + rect.width / 2 - width / 2));
    const roomBelow = window.innerHeight - rect.bottom;
    style = roomBelow > 230
      ? { width, left, top: rect.bottom + pad + 6 }
      : { width, left, bottom: window.innerHeight - rect.top + pad + 6 };
    if (rect.right + width + 24 < window.innerWidth && rect.left < 260) {
      style = { width, left: rect.right + pad + 10, top: Math.max(16, Math.min(window.innerHeight - 260, rect.top - 8)) };
    }
  }

  return (
    <div className="tour" role="dialog" aria-modal="true" aria-labelledby="tour-title">
      {rect ? (
        <div className="tour-spot" style={{ left: rect.left - pad, top: rect.top - pad, width: rect.width + pad * 2, height: rect.height + pad * 2 }} />
      ) : <div className="tour-dim" />}
      <div className="tour-card card stack" style={style}>
        <div className="row between" style={{ flexWrap: "nowrap" }}>
          <span className="xs muted">{i + 1} of {steps.length}</span>
          <button className="btn ghost icon-only sm" onClick={onClose} aria-label="Close the tour"><Icon name="x" size={18} /></button>
        </div>
        <h3 id="tour-title">{step.title}</h3>
        <p className="small ink-2" style={{ margin: 0 }}>{step.body}</p>
        <div className="tour-dots" aria-hidden>{steps.map((_, n) => <span key={n} className={n === i ? "on" : ""} />)}</div>
        <div className="row between">
          {i > 0 ? <button className="btn outline sm" onClick={() => setI(i - 1)}>Back</button> : <button className="linkbtn small" onClick={onClose}>Skip</button>}
          <button ref={next} className="btn primary sm" onClick={() => (last ? onClose() : setI(i + 1))}>{last ? "Get started" : "Next"}</button>
        </div>
      </div>
    </div>
  );
}
