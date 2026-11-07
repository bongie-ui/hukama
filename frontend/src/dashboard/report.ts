// The family dashboard's data model and starting layout for AG Studio.
// Tables come from /api/dashboard/data/ (backend/mandates/dashboard.py); every table links to mandates.
import type { AgDataSourcesDefinition, AgFieldDefinition, AgReportState } from "ag-studio";

export interface DashboardTables {
  mandates: Record<string, unknown>[];
  fundings: Record<string, unknown>[];
  requests: Record<string, unknown>[];
  ledger: Record<string, unknown>[];
  flows: Record<string, unknown>[];
}

const text = (id: string, name: string, hide = false): AgFieldDefinition => ({ id, name, format: "textFormat", hide });
const usd = (id: string, name: string): AgFieldDefinition => ({ id, name, format: "currencyFormat", formatOptions: { format: "$#,##0.00" } });
const int = (id: string, name: string): AgFieldDefinition => ({ id, name, format: "integerFormat" });
const day = (id: string, name: string): AgFieldDefinition => ({ id, name, format: "dateFormat" });

function withDates(rows: Record<string, unknown>[]) {
  return rows.map((r) => (typeof r.date === "string" ? { ...r, date: new Date(`${r.date}T00:00:00`) } : r));
}

export function dataModel(t: DashboardTables): AgDataSourcesDefinition {
  return {
    description:
      "One family's purpose-locked remittances. Family members abroad fund mandates (signed rules for how money " +
      "may be spent). Requests to spend are fraud-checked, then decided by a rules engine; approved ones are paid " +
      "by PayPal Payout. Amounts are US dollars. 'paid' counts only money that actually went out.",
    sources: [
      {
        id: "mandates", name: "Mandates", description: "Money set aside for one purpose, with signed rules.",
        data: t.mandates,
        fields: [text("mandate_id", "Mandate id", true), text("mandate", "Mandate"), text("kind", "Purpose"),
          text("type", "Type", true), text("status", "Status"), usd("funded", "Funded"), usd("available", "Available"),
          usd("spent", "Spent"), int("funders", "Funders")],
      },
      {
        id: "fundings", name: "Funding", description: "Money family members put into a mandate (captured payments).",
        data: withDates(t.fundings),
        fields: [text("funding_id", "Funding id", true), text("mandate_id", "Mandate id", true), text("funder", "Funder"),
          usd("amount", "Amount"), text("rail", "Paid with"), day("date", "Date")],
      },
      {
        id: "requests", name: "Requests", description: "Requests to spend from a mandate and what the rules decided. fraud_alert is 1 for requests held or reported as fraud.",
        data: withDates(t.requests),
        fields: [text("request_id", "Request id", true), text("mandate_id", "Mandate id", true),
          text("requested_by", "Requested by"), text("category", "Category"), usd("amount", "Amount asked"),
          usd("paid", "Paid out"), text("outcome", "Outcome"), text("channel", "Channel"), text("risk_level", "Risk"),
          int("risk_score", "Risk score"), int("fraud_alert", "Fraud alerts"), day("date", "Date")],
      },
      {
        id: "flows", name: "Money flow",
        description: "Where the money came from and went: family member -> mandate (Funded), mandate -> 'Spent: <category>' (Spent), mandate -> 'Still available' (Available).",
        data: t.flows,
        fields: [text("from", "From"), text("to", "To"), text("stage", "Stage"), usd("amount", "Amount")],
      },
      {
        id: "ledger", name: "Audit trail", description: "Append-only record of every event.",
        data: withDates(t.ledger),
        fields: [text("entry_id", "Entry id", true), text("mandate_id", "Mandate id", true), text("time", "When"),
          text("event", "Event"), text("actor", "By"), usd("amount", "Amount"), day("date", "Date")],
      },
    ],
    relationships: ["fundings", "requests", "ledger"].map((table) => ({
      id: `${table}-mandates`,
      source: { tableId: table, fieldId: "mandate_id" },
      target: { tableId: "mandates", fieldId: "mandate_id" },
      type: "many-to-one" as const, // many fundings / requests / ledger rows per mandate
    })),
  } as AgDataSourcesDefinition;
}

const kpi = (id: string, caption: string) => ({
  type: "value",
  dataMapping: { value: [{ id, aggregation: "sum" }] },
  format: { caption: { enabled: true, text: caption } },
});

const titled = (type: string, title: string, dataMapping: Record<string, unknown>) => ({
  type, dataMapping, format: { title: { enabled: true, text: title } },
});

export const initialReport = {
  pages: [
    {
      id: "family",
      name: "Family overview",
      widgets: {
        funded: kpi("mandates.funded", "Funded"),
        available: kpi("mandates.available", "Available to spend"),
        paid: kpi("requests.paid", "Paid out"),
        fraud: kpi("requests.fraud_alert", "Fraud alerts"),
        moneyFlow: {
          type: "money-flow",
          dataMapping: { from: [{ id: "flows.from" }], to: [{ id: "flows.to" }], value: [{ id: "flows.amount", aggregation: "sum" }] },
          format: { title: { enabled: true, text: "Where the money came from and went" } },
        },
        byMandate: titled("column-chart-grouped", "Spent and available by mandate", {
          categoryKey: [{ id: "mandates.mandate" }],
          valueKey: [{ id: "mandates.spent", aggregation: "sum" }, { id: "mandates.available", aggregation: "sum" }],
          tooltipKey: [],
        }),
        byFunder: titled("donut-chart", "Contributions by family member", {
          categoryKey: [{ id: "fundings.funder" }],
          valueKey: [{ id: "fundings.amount", aggregation: "sum" }],
          tooltipKey: [],
        }),
        byCategory: titled("bar-chart-grouped", "Spend by category", {
          categoryKey: [{ id: "requests.category" }],
          valueKey: [{ id: "requests.paid", aggregation: "sum" }],
          tooltipKey: [],
        }),
        outcomes: titled("donut-chart", "What the rules decided", {
          categoryKey: [{ id: "requests.outcome" }],
          valueKey: [{ id: "requests.request_id", aggregation: "count" }],
          tooltipKey: [],
        }),
        ledger: titled("grid", "Audit trail", {
          cols: [{ id: "ledger.time" }, { id: "ledger.event" }, { id: "ledger.actor" }, { id: "mandates.mandate" },
            { id: "ledger.amount", aggregation: "sum" }],
        }),
      },
      widgetLayout: {
        funded: { xTrack: 0, yTrack: 0, xSpan: 6, ySpan: 6 },
        available: { xTrack: 6, yTrack: 0, xSpan: 6, ySpan: 6 },
        paid: { xTrack: 12, yTrack: 0, xSpan: 6, ySpan: 6 },
        fraud: { xTrack: 18, yTrack: 0, xSpan: 6, ySpan: 6 },
        moneyFlow: { xTrack: 0, yTrack: 6, xSpan: 24, ySpan: 24 },
        byMandate: { xTrack: 0, yTrack: 30, xSpan: 12, ySpan: 18 },
        byFunder: { xTrack: 12, yTrack: 30, xSpan: 12, ySpan: 18 },
        byCategory: { xTrack: 0, yTrack: 48, xSpan: 12, ySpan: 18 },
        outcomes: { xTrack: 12, yTrack: 48, xSpan: 12, ySpan: 18 },
        ledger: { xTrack: 0, yTrack: 66, xSpan: 24, ySpan: 22 },
      },
    },
  ],
  selectedPageId: "family",
} as unknown as AgReportState;

export const promptStarters = [
  { label: "Who has given the most?", prompt: "Add a chart showing how much each family member has contributed to each mandate." },
  { label: "Fraud over time", prompt: "Show fraud alerts by week, and a table of the held requests with their risk score." },
  { label: "Monthly support", prompt: "Chart airtime, bundles and cash paid out per month." },
];
