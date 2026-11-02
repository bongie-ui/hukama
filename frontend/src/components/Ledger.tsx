import { useState } from "react";
import { money, when } from "../api";
import { useApi } from "../hooks";
import type { LedgerEntry } from "../types";
import { ErrorNote, Skeleton } from "./ui";

const EVENTS: Record<string, [string, string]> = {
  FUNDED: ["Funds added", "ok"],
  REQUESTED: ["Request received", ""],
  ASSESSED: ["Checked for fraud", ""],
  DECIDED: ["Rules decided", "brand"],
  APPROVED_BY_FUNDER: ["Funder approved", "ok"],
  PAID: ["Paid out", "ok"],
  DELIVERED: ["Delivered", "ok"],
  FAILED: ["Payment failed", "bad"],
  FRAUD_HELD: ["Held as possible fraud", "bad"],
  FRAUD_CONFIRMED: ["Reported as fraud", "bad"],
  RULES_CHANGED: ["Rules signed", "brand"],
};

function detail(e: LedgerEntry): string {
  const d = e.data as Record<string, unknown>;
  if (e.event === "DECIDED") return String(d.reason ?? d.outcome ?? "");
  if (e.event === "ASSESSED") return `Risk ${String(d.level ?? "").toLowerCase()}, score ${d.score ?? 0}`;
  if (e.event === "RULES_CHANGED") return `Version ${d.version}`;
  if (e.event === "FUNDED") return "Through PayPal";
  if (e.event === "DELIVERED") return d.collected ? "Cash collected at an agent" : `${d.product ?? ""} arrived`;
  if (e.event === "FRAUD_CONFIRMED") return Array.isArray(d.blocked) && d.blocked.length ? `Blocked ${d.blocked.join(", ")}` : "";
  return String(d.product ?? "");
}

function tone(e: LedgerEntry, base: string) {
  if (e.event !== "DECIDED") return base;
  const o = String((e.data as Record<string, unknown>).outcome ?? "");
  return o === "APPROVE" ? "ok" : o === "REFUSE" || o === "HOLD_FRAUD" ? "bad" : o === "ESCALATE" ? "warn" : base;
}

/** Append-only audit trail, newest first. */
export default function Ledger({ query, limit }: { query: string; limit?: number }) {
  const { data, error, loading } = useApi<LedgerEntry[]>(`/ledger/?${query}`);
  const [all, setAll] = useState(false);
  if (loading && !data) return <div className="stack">{[0, 1, 2].map((i) => <Skeleton key={i} h={36} />)}</div>;
  const shown = data && limit && !all ? data.slice(0, limit) : data;
  return (
    <>
      <ErrorNote error={error} />
      <ol className="timeline">
        {shown?.map((e) => {
          const [label, base] = EVENTS[e.event] ?? [e.event, ""];
          return (
            <li key={e.id}>
              <span className={`dot ${tone(e, base)}`} aria-hidden />
              <div style={{ minWidth: 0 }}>
                <div className="what">{label}{e.amount ? <span className="num"> · {money(e.amount)}</span> : null}</div>
                <div className="detail">{e.actor_name}{detail(e) ? ` · ${detail(e)}` : ""}</div>
                {e.request && !query.startsWith("request=") && <a className="xs" href={`#/requests/${e.request}`}>View request</a>}
              </div>
              <span className="when">{when(e.created_at)}</span>
            </li>
          );
        })}
      </ol>
      {data?.length === 0 && <p className="small muted">Nothing recorded yet.</p>}
      {limit && data && data.length > limit && !all && (
        <button className="linkbtn small" style={{ marginTop: 12 }} onClick={() => setAll(true)}>Show all {data.length} events</button>
      )}
    </>
  );
}
