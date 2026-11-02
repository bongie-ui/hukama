import { useState } from "react";
import { api, money, when } from "../api";
import { useAction, useApi, usePoll, useSession } from "../hooks";
import type { Mandate } from "../types";
import Icon from "./Icon";
import { Avatar, ErrorNote, MoneyInput, Notice } from "./ui";

export interface FundingRow {
  id: string;
  amount: string;
  status: "CREATED" | "CAPTURED" | "FAILED";
  rail: "PAYPAL" | "PAYNOW_INBOUND";
  rail_label: string;
  contributor_name: string;
  contributor_phone: string;
  failure_reason: string;
  funder: string | null;
  created_at: string;
  instructions?: string;
}

const STATE: Record<FundingRow["status"], [string, string]> = {
  CREATED: ["Waiting for approval on the phone", "info"],
  CAPTURED: ["Received", "ok"],
  FAILED: ["Not paid", "bad"],
};

/** Pools (e.g. funeral) take money from family abroad by PayPal and from relatives at home by mobile money. */
export default function LocalContributions({ mandate, onFunded }: { mandate: Mandate; onFunded: () => void }) {
  const { session } = useSession();
  const fundings = useApi<FundingRow[]>(`/mandates/${mandate.id}/fundings/`);
  const [form, setForm] = useState({ name: "", phone: "", amount: "10" });
  const [started, setStarted] = useState<FundingRow | null>(null);
  const { busy, error, run } = useAction();
  const waiting = started?.status === "CREATED";

  usePoll(async () => {
    if (!started) return;
    const latest = await api.get<FundingRow>(`/fundings/${started.id}/`);
    setStarted({ ...latest, instructions: started.instructions });
    if (latest.status !== "CREATED") {
      void fundings.reload();
      onFunded();
    }
  }, 4000, waiting);

  const start = () => run(async () => {
    setStarted(await api.post<FundingRow>(`/mandates/${mandate.id}/contribute/local/`, form));
    void fundings.reload();
  });

  const rows = fundings.data?.filter((f) => f.status !== "FAILED" || f.rail === "PAYNOW_INBOUND") ?? [];

  return (
    <section className="card stack" aria-labelledby="pool-h" style={{ gap: 16 }}>
      <div className="stack-sm">
        <h2 id="pool-h">Contributions</h2>
        <span className="small muted">Family abroad adds funds with PayPal. Relatives at home can add from mobile money and approve it on their own phone.</span>
      </div>

      <div className="card" style={{ background: "var(--plum-tint)", borderColor: "var(--plum-soft)", boxShadow: "none" }}>
        <div className="stack" style={{ gap: 12 }}>
          <strong className="row" style={{ gap: 8 }}><Icon name="phone" size={18} />Ask a relative at home to contribute</strong>
          <div className="form-grid">
            <div className="field"><label htmlFor="lc-name">Their name</label>
              <input id="lc-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Auntie Nomsa" /></div>
            <div className="field"><label htmlFor="lc-phone">Mobile money number</label>
              <input id="lc-phone" inputMode="tel" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} placeholder="0771 234 567" /></div>
            <div className="field"><label htmlFor="lc-amount">Amount</label>
              <MoneyInput id="lc-amount" label="Amount in US dollars" value={form.amount} onChange={(v) => setForm({ ...form, amount: v })} /></div>
          </div>
          <div className="row between">
            <span className="xs muted">They get a prompt on their phone and approve with their PIN. Their PIN never touches Hukama.</span>
            <button className="btn primary" disabled={busy || waiting || !form.name || !form.phone || Number(form.amount) <= 0} onClick={start}>
              {busy ? <span className="spinner" /> : null}Send request to their phone
            </button>
          </div>
          {session.demo_mode && (
            <span className="xs muted">Test mode numbers: 0771111111 pays, 0772222222 pays after a delay, 0773333333 is cancelled, 0774444444 has no balance.</span>
          )}
          {started && (
            <Notice tone={STATE[started.status][1]} icon={started.status === "CAPTURED" ? "check" : started.status === "FAILED" ? "alert" : "clock"}>
              <strong>{started.contributor_name}: {STATE[started.status][0]}</strong>
              {started.status === "CREATED" && started.instructions ? <div>{started.instructions}</div> : null}
              {started.failure_reason ? <div>{started.failure_reason}</div> : null}
            </Notice>
          )}
          <ErrorNote error={error} />
        </div>
      </div>

      <div className="list">
        {rows.map((f) => {
          const name = f.funder ?? f.contributor_name ?? "Contributor";
          const [label, tone] = STATE[f.status];
          return (
            <div key={f.id} className="list-item" style={{ paddingInline: 0 }}>
              <Avatar name={name} />
              <div className="main">
                <span className="title">{name}</span>
                <span className="sub">{f.rail === "PAYPAL" ? "PayPal" : "Local mobile money (test mode)"} · {when(f.created_at)}</span>
              </div>
              <div className="end">
                <span className="num" style={{ fontWeight: 700 }}>{money(f.amount, mandate.currency)}</span>
                <span className={`pill ${tone}`}>{label}</span>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
