import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import type { AgReportState } from "ag-studio";
import { api } from "../api";
import Icon from "../components/Icon";
import { ErrorNote, Skeleton } from "../components/ui";
import type { DashboardTables } from "../dashboard/report";
import { useApi } from "../hooks";

const Dashboard = lazy(() => import("../dashboard/Dashboard"));
const SAVE_DELAY_MS = 1200;

type Saving = "idle" | "saving" | "saved" | "error";

export default function DashboardPage() {
  const tables = useApi<DashboardTables>("/dashboard/data/");
  const layout = useApi<{ state: AgReportState | null }>("/dashboard/layout/");
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState<Saving>("idle");
  const [version, setVersion] = useState(0); // remounts Studio after a reset
  const timer = useRef<number | undefined>(undefined);
  const pending = useRef<AgReportState | null>(null);

  const flush = useCallback(async () => {
    const state = pending.current;
    if (!state) return;
    pending.current = null;
    setSaving("saving");
    try {
      await api.put("/dashboard/layout/", { state });
      setSaving("saved");
    } catch {
      setSaving("error");
    }
  }, []);

  // Studio reports every change; save the latest one once changes pause, and before leaving the page.
  const onChange = useCallback((state: AgReportState) => {
    pending.current = state;
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(flush, SAVE_DELAY_MS);
  }, [flush]);
  useEffect(() => () => {
    window.clearTimeout(timer.current);
    void flush();
  }, [flush]);

  const reset = async () => {
    window.clearTimeout(timer.current);
    pending.current = null;
    await api.delete("/dashboard/layout/");
    await layout.reload();
    setSaving("idle");
    setVersion((v) => v + 1);
  };

  const ready = tables.data && !layout.loading;

  return (
    <div className="page wide">
      <header className="page-head">
        <div>
          <h1>Dashboard</h1>
          <p>Where the family's money went, who gave what, and every fraud alert. Changes are saved for the whole family.</p>
        </div>
        <div className="row head-actions">
          <span className="xs muted" aria-live="polite">
            {saving === "saving" ? "Saving…" : saving === "saved" ? "Saved for the family" : saving === "error" ? "Could not save" : ""}
          </span>
          <button className="btn ghost sm" onClick={reset} title="Go back to the default dashboard">Reset layout</button>
          <button className="btn outline sm" onClick={() => void tables.reload()} disabled={tables.loading}>Refresh data</button>
          <button className={`btn sm ${editing ? "primary" : "outline"}`} onClick={() => setEditing(!editing)} aria-pressed={editing}>
            <Icon name="sparkle" size={18} />{editing ? "Done editing" : "Build with AI"}
          </button>
        </div>
      </header>
      {editing && (
        <div className="ai-note">
          <Icon name="sparkle" size={18} />
          <span>Open the assistant panel on the right and describe the chart you want, for example "show a money flow of who funded what". It can add and change charts. It cannot move money.</span>
        </div>
      )}
      <ErrorNote error={tables.error ?? layout.error} />
      {ready ? (
        <Suspense fallback={<Skeleton h={640} r={18} />}>
          <Dashboard key={version} tables={tables.data!} editing={editing} saved={layout.data?.state ?? null} onChange={onChange} />
        </Suspense>
      ) : (
        !tables.error && <Skeleton h={640} r={18} />
      )}
    </div>
  );
}
