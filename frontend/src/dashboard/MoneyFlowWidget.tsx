// Custom AG Studio widget: a Sankey "money flow" from any "from" category to any "to" category, sized by a
// number. On the family dashboard it shows family member -> mandate -> what the money was spent on.
// Built on AG Charts Enterprise (already part of AG Studio), drawn with the vanilla API: no extra package.
import { AgCharts, LicenseManager, ModuleRegistry, SankeySeriesModule, type AgChartInstance, type AgChartOptions } from "ag-charts-enterprise";
import { getChartTheme, type AgWidgetFieldReference, type AgWidgetParams } from "ag-studio";
import { useEffect, useRef, useState } from "react";

ModuleRegistry.registerModules([SankeySeriesModule]);
// This chart is created directly, outside AG Studio, so it needs the same licence key AG Studio gets.
const LICENSE_KEY = import.meta.env.VITE_AG_STUDIO_LICENSE_KEY as string | undefined;
if (LICENSE_KEY) LicenseManager.setLicenseKey(LICENSE_KEY);

export interface MoneyFlowDef {
  type: "money-flow";
  dataMapping: {
    from: AgWidgetFieldReference[];
    to: AgWidgetFieldReference[];
    value: AgWidgetFieldReference[];
  };
}

type Row = Record<string, unknown>;

export default function MoneyFlowWidget(params: AgWidgetParams<MoneyFlowDef>) {
  const { api, widgetApi, dataMapping } = params;
  const from = dataMapping.from?.at(0);
  const to = dataMapping.to?.at(0);
  const value = dataMapping.value?.at(0);
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<AgChartInstance | null>(null);
  const loaded = useRef(false);
  const [rows, setRows] = useState<Row[] | null>(null);

  useEffect(() => {
    if (!from || !to || !value) {
      widgetApi.setDisplayState("incompleteDataMapping");
      return;
    }
    widgetApi.setDisplayState("loading", { prominent: !loaded.current });
    let cancelled = false;
    // The flow always covers the whole family picture, so it ignores cross-filters from other widgets.
    widgetApi.getData({ fields: [from, to, value] }, { crossFilter: "none" }).then((response) => {
      if (cancelled) return;
      const data = response.results.rows.filter((r: Row) => Number(r[value.key]) > 0);
      if (!data.length) {
        widgetApi.setDisplayState("noData");
        return;
      }
      loaded.current = true;
      widgetApi.setDisplayState("displayed");
      setRows(data);
    });
    return () => {
      cancelled = true;
    };
  }, [widgetApi, from, to, value]);

  useEffect(() => {
    if (!rows || !from || !to || !value || !box.current) return;
    const options: AgChartOptions = {
      container: box.current,
      theme: getChartTheme(api),
      background: { fill: "transparent" },
      data: rows.map((r) => ({
        from: widgetApi.formatFieldValue(from, r[from.key]),
        to: widgetApi.formatFieldValue(to, r[to.key]),
        size: Number(r[value.key]),
      })),
      series: [{
        type: "sankey",
        fromKey: "from",
        toKey: "to",
        sizeKey: "size",
        sizeName: "Amount",
        tooltip: {
          renderer: ({ datum }: { datum?: { id?: string; from?: string; to?: string; size?: number } }) => datum == null ? "" :
            `<div style="padding:6px 10px"><div class="ag-charts-tooltip-title">${datum.id ?? `${datum.from} → ${datum.to}`}</div>` +
            `<div class="ag-charts-tooltip-content">${widgetApi.formatFieldValue(value, datum.size)}</div></div>`,
        },
      }],
    } as AgChartOptions;
    if (chart.current) chart.current.update(options);
    else chart.current = AgCharts.create(options);
  }, [rows, api, widgetApi, from, to, value]);

  useEffect(() => () => {
    chart.current?.destroy();
    chart.current = null;
  }, []);

  return <div ref={box} style={{ width: "100%", height: "100%" }} />;
}
