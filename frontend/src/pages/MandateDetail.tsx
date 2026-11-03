import { money } from "../api";
import { ActivityList } from "../components/Activity";
import FundButton from "../components/FundButton";
import PoolContributions from "../components/PoolContributions";
import PremiumCard from "../components/PremiumCard";
import Icon, { TYPE_ICON } from "../components/Icon";
import Ledger from "../components/Ledger";
import QuickActions from "../components/QuickActions";
import RequestForm from "../components/RequestForm";
import { Avatar, ErrorNote, Money, PageLoading, splitType } from "../components/ui";
import { useApi } from "../hooks";
import type { Beneficiary, Mandate, PayRequest } from "../types";

export default function MandateDetail({ id }: { id: string }) {
  const mandate = useApi<Mandate>(`/mandates/${id}/`);
  const requests = useApi<PayRequest[]>(`/requests/?mandate=${id}`);
  const beneficiaries = useApi<Beneficiary[]>("/beneficiaries/");
  const m = mandate.data;

  const refresh = () => {
    void mandate.reload();
    void requests.reload();
  };

  if (mandate.error) return <div className="page narrow"><ErrorNote error={mandate.error} /></div>;
  if (!m) return <PageLoading />;
  const covered = beneficiaries.data?.filter((b) => m.beneficiary_ids.includes(b.id)) ?? [];
  const [name, kind] = splitType(m.type_label);
  const spent = Math.max(0, Number(m.funded) - Number(m.balance));
  const total = Number(m.funded) || 1;

  return (
    <div className="page">
      <a href="#/" className="back"><Icon name="back" size={16} />Home</a>

      <section className="mandate-hero" aria-labelledby="m-title">
        <div className="stack" style={{ gap: 16 }}>
          <div className="row" style={{ gap: 12 }}>
            <span className="type-icon" style={{ background: "rgb(255 255 255 / .12)", color: "#fff" }}>
              <Icon name={TYPE_ICON[m.type] ?? "wallet"} size={22} />
            </span>
            <div className="stack-sm" style={{ gap: 2 }}>
              <span className="eyebrow">{name} · {kind}</span>
              <h1 id="m-title">{m.title}</h1>
            </div>
          </div>
          {m.purpose_text && <p className="purpose">“{m.purpose_text}”</p>}
          <div className="stack-sm">
            <span className="small muted">Available</span>
            <Money value={m.balance} currency={m.currency} size="xl" />
          </div>
          <div className="stack-sm" style={{ maxWidth: 460 }}>
            <div className="meter"><span style={{ width: `${(spent / total) * 100}%`, background: "var(--coral)" }} /></div>
            <span className="small muted">{money(spent, m.currency)} spent of {money(m.funded, m.currency)} funded</span>
          </div>
        </div>
        <div className="stack" style={{ minWidth: 0 }}>
          <div className="contrib" aria-label="Contributions">
            {m.funders.map((f) => (
              <div key={f.user_id} className="contrib-row">
                <Avatar name={f.name} size="sm" />
                <span className="name">{f.name}{f.role === "OWNER" ? <span className="muted"> · owner</span> : null}</span>
                <span className="num" style={{ fontWeight: 700 }}>{money(f.contributed, m.currency)}</span>
              </div>
            ))}
          </div>
          {m.premium
            ? <span className="small muted">Funded by the monthly premium below.</span>
            : <FundButton mandate={m} onFunded={refresh} />}
        </div>
      </section>

      <div className="split">
        <div className="stack" style={{ gap: 28 }}>
          {covered.map((b) => <QuickActions key={b.id} mandate={m} beneficiary={b} onChange={refresh} />)}
          {m.premium && <PremiumCard mandate={m} onChange={refresh} />}
          {m.public_contributions && <PoolContributions mandate={m} onChange={refresh} />}
          {covered.length === 0 && !m.premium && <RequestForm mandate={m} />}

          <section className="section" aria-labelledby="req-h">
            <div className="section-head"><h2 id="req-h">Requests</h2></div>
            <ErrorNote error={requests.error} />
            <ActivityList items={requests.data} loading={requests.loading} showMandate={false}
              empty="No requests yet. Family, suppliers and schools can also ask through the assistant." />
          </section>
        </div>

        <div className="stack" style={{ gap: 16 }}>
          <section className="card" aria-labelledby="rules-h">
            <div className="row between" style={{ marginBottom: 14 }}>
              <h3 id="rules-h">The agreement</h3>
              <span className={`seal ${m.signature_valid ? "" : "broken"}`} title="The rules are signed; any change needs the owner and a new signature">
                <Icon name="lock" size={14} />{m.signature_valid ? `Signed · version ${m.version}` : "Signature broken"}
              </span>
            </div>
            <ul className="rules">
              {m.rules.map((r) => (
                <li key={r.id}><span className="rule-dot"><Icon name="check" size={14} stroke={2.4} /></span><span>{r.text}</span></li>
              ))}
            </ul>
            <div className="ai-note" style={{ marginTop: 16 }}>
              <Icon name="sparkle" size={18} />
              <span>The rules engine decides every payment. The assistant reads quotes and flags scams, but it can only make a decision stricter.</span>
            </div>
          </section>

          <section className="card" aria-labelledby="audit-h">
            <div className="stack-sm" style={{ marginBottom: 16 }}>
              <h3 id="audit-h">Audit trail</h3>
              <span className="small muted">Every event is recorded and can never be edited.</span>
            </div>
            <Ledger key={requests.data?.length ?? 0} query={`mandate=${m.id}`} limit={12} />
          </section>
        </div>
      </div>
    </div>
  );
}
