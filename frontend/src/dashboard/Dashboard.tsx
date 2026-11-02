// Family dashboard built on AG Studio, with its Agent Framework answering through our backend.
// Loaded lazily (it is large) from pages/DashboardPage.tsx.
import { AgStudioAiModule, createAiHarness, studioTheme } from "ag-studio";
import { AgStudio, AgStudioProvider } from "ag-studio-react";
import { useEffect, useMemo, useState } from "react";
import { hukamaAdapter } from "./adapter";
import { dataModel, initialReport, promptStarters, type DashboardTables } from "./report";

const LICENSE_KEY = import.meta.env.VITE_AG_STUDIO_LICENSE_KEY as string | undefined;
const modules = [AgStudioAiModule];

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

export default function Dashboard({ tables, editing }: { tables: DashboardTables; editing: boolean }) {
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
          initialState={initialReport}
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
