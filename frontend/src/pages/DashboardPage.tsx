import { lazy, Suspense, useState } from "react";
import Icon from "../components/Icon";
import { ErrorNote, Skeleton } from "../components/ui";
import type { DashboardTables } from "../dashboard/report";
import { useApi } from "../hooks";

const Dashboard = lazy(() => import("../dashboard/Dashboard"));

export default function DashboardPage() {
  const tables = useApi<DashboardTables>("/dashboard/data/");
  const [editing, setEditing] = useState(false);

  return (
    <div className="page wide">
      <header className="page-head">
        <div>
          <h1>Dashboard</h1>
          <p>Where the family's money went, who gave what, and every fraud alert. Ask the assistant to build new charts.</p>
        </div>
        <div className="row">
          <button className="btn outline" onClick={() => void tables.reload()} disabled={tables.loading}>Refresh data</button>
          <button className={`btn ${editing ? "primary" : "outline"}`} onClick={() => setEditing(!editing)} aria-pressed={editing}>
            <Icon name="sparkle" size={18} />{editing ? "Done editing" : "Build with AI"}
          </button>
        </div>
      </header>
      {editing && (
        <div className="ai-note">
          <Icon name="sparkle" size={18} />
          <span>Open the assistant panel on the right and describe the chart you want, for example "chart cash paid per month". It can add and change charts. It cannot move money.</span>
        </div>
      )}
      <ErrorNote error={tables.error} />
      {tables.data ? (
        <Suspense fallback={<Skeleton h={640} r={18} />}>
          <Dashboard tables={tables.data} editing={editing} />
        </Suspense>
      ) : (
        !tables.error && <Skeleton h={640} r={18} />
      )}
    </div>
  );
}
