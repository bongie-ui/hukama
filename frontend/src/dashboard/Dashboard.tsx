// Family dashboard built on AG Studio, with its Agent Framework answering through our backend.
// Loaded lazily (it is large) from pages/DashboardPage.tsx.
import { AgStudioAiModule, createAiHarness, studioTheme, type AgReportState } from "ag-studio";
import { AgStudio, AgStudioProvider, createWidgets } from "ag-studio-react";
import { useEffect, useMemo, useState } from "react";
import { hukamaAdapter } from "./adapter";
import MoneyFlowWidget from "./MoneyFlowWidget";
import { dataModel, initialReport, promptStarters, type DashboardTables } from "./report";

const LICENSE_KEY = import.meta.env.VITE_AG_STUDIO_LICENSE_KEY as string | undefined;
const modules = [AgStudioAiModule];

const MONEY_FLOW_ICON = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M4 6c8 0 8 12 16 12M4 12c8 0 8-6 16-6M4 18c6 0 10-6 16-6"/></svg>`;

// Hukama's own widget, offered in the widget menu and described for the AI agents.
const widgets = (defaults: { menu: { label: string; widgetIds: string[] }[] }) =>
  createWidgets({
    additionalTypes: [{
      id: "money-flow",
      label: "Money flow",
      icon: MONEY_FLOW_ICON,
      dataMapping: {
        from: { type: "field", supportedRoles: ["category"], requires: { cardinality: "one" }, required: true,
          aiDescription: "Where money comes from, e.g. flows.from (a family member or a mandate)." },
        to: { type: "field", supportedRoles: ["category"], requires: { cardinality: "one" }, required: true,
          aiDescription: "Where money goes, e.g. flows.to (a mandate, a spend category, or 'Still available')." },
        value: { type: "field", supportedRoles: ["numeric"], requires: { cardinality: "one" }, required: true,
          aiDescription: "Amount that sizes each flow, e.g. flows.amount summed." },
      },
      form: (params: { createDefaults: (o: unknown) => unknown }) => params.createDefaults({
        dataMappingItems: [{ key: "from", label: "From" }, { key: "to", label: "To" }, { key: "value", label: "Amount" }],
      }),
      comp: MoneyFlowWidget,
      defaultSize: { width: 900, height: 420 },
      minSize: { width: 360, height: 240 },
      ai: {
        label: "Money flow (Sankey)",
        description: "Shows how money flows from family members into mandates and out to what it was spent on.",
        usage: "Use for 'where did the money go', 'who funded what' or flow questions. Map flows.from, flows.to and flows.amount (sum).",
      },
    }],
    menu: [{ label: "Hukama", widgetIds: ["money-flow"] }, ...defaults.menu],
  } as never);

const brand = {
  accentColor: "#4a1f3d",
  fontFamily: { googleFont: "Manrope" },
  chartPaletteFills1Color: "#4a1f3d",
  chartPaletteFills2Color: "#ff8a7a",
  chartPaletteFills3Color: "#1f6b5c",
  chartPaletteFills4Color: "#c9952a",
  chartPaletteFills5Color: "#2f4f8f",
  chartPaletteFills6Color: "#b35c7a",
};
const theme = studioTheme
  .withParams({ ...brand, backgroundColor: "#ffffff", foregroundColor: "#1f1a1d", browserColorScheme: "light" }, "light")
  .withParams({ ...brand, accentColor: "#f0b3cf", chartPaletteFills1Color: "#f0b3cf", backgroundColor: "#1c171a",
    foregroundColor: "#f4eef1", browserColorScheme: "dark" }, "dark");

export default function Dashboard({ tables, editing, saved, onChange }: {
  tables: DashboardTables;
  editing: boolean;
  saved: AgReportState | null;
  onChange: (state: AgReportState) => void;
}) {
  const data = useMemo(() => dataModel(tables), [tables]);
  const panels = useMemo(() => ({ edit: { right: ["ai", "edit"] }, view: { right: [] } }), []);
  const ai = useMemo(() => ({ api }: { api: Parameters<typeof createAiHarness>[0] }) =>
    createAiHarness(api, { adapter: hukamaAdapter, promptStarters }), []);
  const mode = useColorMode();

  return (
    <div className="ag-theme-mode studio-frame" data-ag-theme-mode={mode}>
      <AgStudioProvider modules={modules} licenseKey={LICENSE_KEY}>
        <AgStudio
          style={{ height: "100%", width: "100%" }}
          data={data}
          initialState={saved ?? initialReport}
          onStateUpdated={(e: { state: AgReportState }) => onChange(e.state)}
          widgets={widgets as never}
          mode={editing ? "edit" : "view"}
          panels={panels as never}
          theme={theme}
          loadThemeGoogleFonts
          ai={ai as never}
        />
      </AgStudioProvider>
    </div>
  );
}

function useColorMode() {
  const query = "(prefers-color-scheme: dark)";
  const [dark, setDark] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const on = () => setDark(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return dark ? "dark" : "light";
}
