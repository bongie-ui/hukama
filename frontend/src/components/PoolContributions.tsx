import { money, when } from "../api";
import { useApi } from "../hooks";
import type { Mandate } from "../types";
import { Avatar, Skeleton } from "./ui";

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
export default function PoolContributions({ mandate }: { mandate: Mandate }) {
  const fundings = useApi<FundingRow[]>(`/mandates/${mandate.id}/fundings/`);
  const rows = fundings.data?.filter((f) => f.status === "CAPTURED") ?? [];

  return (
    <section className="card stack" aria-labelledby="pool-h" style={{ gap: 16 }}>
      <div className="stack-sm">
        <h2 id="pool-h">Contributions</h2>
        <span className="small muted">Family and friends add to this pool with PayPal.</span>
      </div>
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
