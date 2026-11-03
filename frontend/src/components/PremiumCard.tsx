import { useEffect, useState } from "react";
import { api, money, when } from "../api";
import { useAction, useApi, useSession } from "../hooks";
import { query, usePath } from "../router";
import type { Mandate } from "../types";
import Icon from "./Icon";
import { Avatar, ErrorNote, Notice } from "./ui";

interface Premium {
  id: string;
  amount: string;
  status: "APPROVAL_PENDING" | "ACTIVE" | "SUSPENDED" | "CANCELLED" | "EXPIRED";
  status_label: string;
  funder: string;
  funder_id: number;
  activated_at: string | null;
  cancelled_at: string | null;
  created_at: string;
}

const TONE: Record<Premium["status"], string> = {
  ACTIVE: "ok", APPROVAL_PENDING: "warn", SUSPENDED: "warn", CANCELLED: "", EXPIRED: "",
};

/** Monthly premium by PayPal subscription. PayPal collects it; the rules then pay the cover provider. */
export default function PremiumCard({ mandate, onChange }: { mandate: Mandate; onChange: () => void }) {
  const { session } = useSession();
  const path = usePath();
  const info = useApi<{ amount: string; subscriptions: Premium[] }>(`/mandates/${mandate.id}/premium/`);
  const { busy, error, run } = useAction();
  const [note, setNote] = useState<string | null>(null);
  const active = info.data?.subscriptions.find((s) => s.status === "ACTIVE");
  const returned = query(path).get("premium");
  const cancelledAtPayPal = query(path).get("cancelled");

  // Back from PayPal: confirm with PayPal (activation can take a few seconds), then tidy the address.
  useEffect(() => {
    if (!returned) return;
    if (cancelledAtPayPal) {
      setNote("You left PayPal before approving. Nothing was set up.");
      window.location.hash = `/mandates/${mandate.id}`;
      return;
    }
    void run(async () => {
      for (let attempt = 0; attempt < 6; attempt++) {
        const p = await api.post<Premium>(`/premiums/${returned}/sync/`);
        if (p.status === "ACTIVE") {
          setNote(`Monthly premium of ${money(p.amount, mandate.currency)} is active. The first payment covers this month.`);
          break;
        }
        await new Promise((r) => setTimeout(r, 2500));
      }
      await info.reload();
      onChange();
      window.location.hash = `/mandates/${mandate.id}`;
    });
  }, [returned]); // eslint-disable-line react-hooks/exhaustive-deps

  const start = () => run(async () => {
    const r = await api.post<Premium & { approve_url: string }>(`/mandates/${mandate.id}/premium/start/`);
    window.location.href = r.approve_url; // approve on PayPal; PayPal sends the funder back here
  });
  const stop = (p: Premium) => run(async () => {
    await api.post(`/premiums/${p.id}/cancel/`);
    setNote("The monthly premium is stopped. The cover runs to the end of the period already paid.");
    await info.reload();
    onChange();
  });

  return (
    <section className="card stack" aria-labelledby="premium-h" style={{ gap: 16 }}>
      <div className="row between">
        <div className="stack-sm" style={{ gap: 2 }}>
          <h2 id="premium-h">Monthly premium</h2>
          <span className="small muted">Paid by PayPal subscription, then passed to the cover provider by the rules.</span>
        </div>
        <span className="amount lg">{money(mandate.premium ?? 0, mandate.currency)}<span className="small muted"> /month</span></span>
      </div>

      {active ? (
        <div className="row between" style={{ padding: 14, borderRadius: 12, background: "var(--ok-soft)" }}>
          <div className="row" style={{ flexWrap: "nowrap" }}>
            <Avatar name={active.funder} />
            <div className="stack-sm" style={{ gap: 0 }}>
              <strong style={{ color: "var(--ok)" }}>Active, paid by {active.funder}</strong>
              <span className="xs muted">Since {active.activated_at ? when(active.activated_at) : when(active.created_at)} · renews monthly through PayPal</span>
            </div>
          </div>
          {active.funder_id === session.user?.id && (
            <button className="btn outline sm" disabled={busy} onClick={() => stop(active)}>Stop premium</button>
          )}
        </div>
      ) : (
        <div className="stack" style={{ gap: 10 }}>
          <Notice tone="warn" icon="alert">No monthly premium is set up, so the cover may lapse.</Notice>
          <button className="btn primary lg" disabled={busy || !mandate.premium} onClick={start}>
            {busy ? <span className="spinner" /> : <Icon name="lock" size={18} />}
            Start monthly premium with PayPal
          </button>
          <span className="xs muted">You approve it on PayPal and come straight back. You can stop it any time here.</span>
        </div>
      )}

      {busy && returned && <span className="small muted row" style={{ gap: 8 }}><span className="spinner" />Confirming with PayPal…</span>}
      {note && <Notice tone="ok" icon="check">{note}</Notice>}
      <ErrorNote error={error} />

      {(info.data?.subscriptions.length ?? 0) > 1 && (
        <div className="stack-sm">
          <span className="eyebrow">History</span>
          {info.data!.subscriptions.filter((s) => s !== active).map((s) => (
            <span key={s.id} className="small row" style={{ gap: 8 }}>
              <span className={`pill ${TONE[s.status]}`}>{s.status_label}</span>{s.funder} · started {when(s.created_at)}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}
