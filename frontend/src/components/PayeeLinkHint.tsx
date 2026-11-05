import { useState } from "react";
import { useApi } from "../hooks";
import type { Mandate, Payee } from "../types";
import Icon from "./Icon";
import LinkPanel from "./LinkPanel";

/** On a mandate page: the payee can send its quote, invoice or photo itself through its own upload link,
 * after logging in with its PayPal account, instead of a family member filling in the form. */
export default function PayeeLinkHint({ mandate }: { mandate: Mandate }) {
  const payees = useApi<Payee[]>("/payees/");
  const ids = mandate.rules.filter((r) => r.kind === "allowed_payees")
    .flatMap((r) => ((r.params.payee_ids as string[] | undefined) ?? []).map(String));
  const list = (payees.data ?? []).filter((p) => ids.includes(p.id) && p.rail !== "LOCAL_MOBILE_MONEY");
  const [open, setOpen] = useState<string | null>(null);
  if (!list.length) return null;

  return (
    <section className="card stack" style={{ gap: 12, background: "var(--plum-tint)", borderColor: "var(--plum-soft)", boxShadow: "none" }}>
      <div className="row" style={{ gap: 10, flexWrap: "nowrap", alignItems: "flex-start" }}>
        <span className="icon-circle"><Icon name="send" size={20} /></span>
        <div className="stack-sm" style={{ gap: 2 }}>
          <strong>Let {list.length === 1 ? list[0].name : "the payee"} send it themselves</strong>
          <span className="small ink-2">Share their private upload link. They log in with their own PayPal account, so only the business that gets paid can ask for the money, then send a photo of the quote, invoice or progress. The rules check it the same way.</span>
        </div>
      </div>
      {list.map((p) => (
        <div key={p.id} className="row" style={{ flexWrap: "wrap" }}>
          {list.length > 1 && <span className="small" style={{ flex: 1 }}>{p.name}</span>}
          {open === p.id ? (
            <LinkPanel token={p.upload_link} route="supplier" endpoint={`/payees/${p.id}/upload-link/`} onChange={payees.reload}
              intro={`Send this to ${p.name} on WhatsApp or by SMS. They log in with PayPal (${p.paypal_email}) before they can send anything.`}
              empty={`${p.name} has no upload link yet.`} />
          ) : (
            <button className="btn primary sm" onClick={() => setOpen(p.id)}><Icon name="clip" size={16} />{p.upload_link ? "Copy upload link" : "Create upload link"}</button>
          )}
        </div>
      ))}
    </section>
  );
}
