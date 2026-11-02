import { useState } from "react";
import { api, money, when } from "../api";
import { useAction, useApi, useSession } from "../hooks";
import type { Mandate } from "../types";
import Icon from "./Icon";
import { Avatar, ErrorNote, Skeleton } from "./ui";

export interface FundingRow {
  id: string;
  amount: string;
  status: "CREATED" | "CAPTURED" | "FAILED";
  rail: "PAYPAL";
  contributor_name: string;
  funder: string | null;
  created_at: string;
}

/** Everyone who has put money into a pool, all through PayPal. */
export default function PoolContributions({ mandate, onChange }: { mandate: Mandate; onChange: () => void }) {
  const { session } = useSession();
  const fundings = useApi<FundingRow[]>(`/mandates/${mandate.id}/fundings/`);
  const rows = fundings.data?.filter((f) => f.status === "CAPTURED") ?? [];
  const isOwner = mandate.funders.some((f) => f.role === "OWNER" && f.user_id === session.user?.id);
  const link = mandate.contribute_token ? `${window.location.origin}/#/give/${mandate.contribute_token}` : "";
  const [copied, setCopied] = useState(false);
  const { busy, error, run } = useAction();

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      (document.getElementById(`link-${mandate.id}`) as HTMLInputElement | null)?.select();
    }
  };
  const toggle = (on: boolean) => run(async () => {
    await (on ? api.post(`/mandates/${mandate.id}/contribution-link/`) : api.delete(`/mandates/${mandate.id}/contribution-link/`));
    onChange();
  });

  return (
    <section className="card stack" aria-labelledby="pool-h" style={{ gap: 16 }}>
      <div className="stack-sm">
        <h2 id="pool-h">Contributions</h2>
        <span className="small muted">Family and friends add to this pool with PayPal.</span>
      </div>

      {mandate.public_contributions && (
        <div className="card" style={{ background: "var(--plum-tint)", borderColor: "var(--plum-soft)", boxShadow: "none" }}>
          <div className="stack" style={{ gap: 10 }}>
            <strong className="row" style={{ gap: 8 }}><Icon name="send" size={18} />Share the pool</strong>
            {link ? (
              <>
                <span className="small ink-2">Anyone with this link can give with PayPal. No account needed. Send it on WhatsApp or by SMS.</span>
                <div className="row" style={{ flexWrap: "nowrap" }}>
                  <input id={`link-${mandate.id}`} className="input" readOnly value={link} onFocus={(e) => e.target.select()} style={{ minWidth: 0 }} />
                  <button className="btn primary" onClick={copy}>{copied ? "Copied" : "Copy link"}</button>
                </div>
                <div className="row between">
                  <a className="small" href={`#/give/${mandate.contribute_token}`} target="_blank" rel="noreferrer">Preview the page</a>
                  {isOwner && <button className="linkbtn small" disabled={busy} onClick={() => toggle(false)}>Turn off link</button>}
                </div>
              </>
            ) : isOwner ? (
              <div className="row between">
                <span className="small ink-2">Let relatives and friends outside the family give with PayPal.</span>
                <button className="btn primary sm" disabled={busy} onClick={() => toggle(true)}>Create a link</button>
              </div>
            ) : (
              <span className="small muted">The pool's owner can create a link for relatives and friends to give with PayPal.</span>
            )}
            <ErrorNote error={error} />
          </div>
        </div>
      )}
      {fundings.loading && !fundings.data && <Skeleton h={120} />}
      <div className="list">
        {rows.map((f) => {
          const name = f.funder ?? f.contributor_name ?? "Contributor";
          return (
            <div key={f.id} className="list-item" style={{ paddingInline: 0 }}>
              <Avatar name={name} />
              <div className="main">
                <span className="title">{name}</span>
                <span className="sub">{f.funder ? "Family funder" : "Gave through the pool link"} · PayPal · {when(f.created_at)}</span>
              </div>
              <div className="end">
                <span className="num" style={{ fontWeight: 700 }}>{money(f.amount, mandate.currency)}</span>
                <span className="pill ok">Received</span>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
