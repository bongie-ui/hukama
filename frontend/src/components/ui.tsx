import type { ReactNode } from "react";
import { money } from "../api";
import type { Payment, RequestStatus } from "../types";
import Icon from "./Icon";

// ---- Status --------------------------------------------------------------------------------------------

const STATUS: Record<RequestStatus, [string, string]> = {
  NEW: ["New", ""],
  ASSESSED: ["Checking", "info"],
  APPROVED: ["Paying", "info"],
  PAID: ["Paid", "ok"],
  REFUSED: ["Refused", "bad"],
  ESCALATED: ["Needs approval", "warn"],
  HELD_FRAUD: ["Held: possible fraud", "bad"],
  CONFIRMED_FRAUD: ["Fraud reported", "bad"],
  FAILED: ["Payment failed", "bad"],
  CANCELLED: ["Cancelled", ""],
};

export function statusTone(status: RequestStatus) {
  return STATUS[status]?.[1] ?? "";
}

export function StatusPill({ status }: { status: RequestStatus }) {
  const [label, tone] = STATUS[status] ?? [status, ""];
  return <span className={`pill ${tone}`}>{label}</span>;
}

export function riskTone(level: string) {
  return level === "HIGH" ? "bad" : level === "MEDIUM" ? "warn" : "ok";
}

export function SimTag({ label = "Simulated rail" }: { label?: string }) {
  return <span className="sim" title="This step is simulated in the demo; no real money moves on it">{label}</span>;
}

export function lastMileLabel(p: Payment): string | null {
  switch (p.last_mile_status) {
    case "DELIVERING": return "Delivering to phone";
    case "PREPARING": return "Being packed";
    case "OUT_FOR_DELIVERY": return "Out for delivery";
    case "DELIVERED": return "Delivered";
    case "AWAITING_COLLECTION": return "Ready to collect";
    case "COLLECTED": return "Collected";
    default: return null;
  }
}

/** One-line payment state for lists. */
export function paymentSummary(p: Payment | null): [string, string] | null {
  if (!p) return null;
  const lm = lastMileLabel(p);
  const moving = ["DELIVERING", "PREPARING", "OUT_FOR_DELIVERY", "AWAITING_COLLECTION"].includes(p.last_mile_status);
  if (p.status === "SUCCESS") return [lm ?? "Received by payee", moving ? "info" : "ok"];
  if (p.status === "PENDING") return ["Payout pending", "info"];
  return [`Payout ${p.status.toLowerCase()}`, "bad"];
}

// ---- Feedback ------------------------------------------------------------------------------------------

export function ErrorNote({ error }: { error: string | null | undefined }) {
  if (!error) return null;
  return <div className="notice error" role="alert"><Icon name="alert" size={18} />{error}</div>;
}

export function Notice({ tone = "info", icon = "alert", children }: { tone?: string; icon?: string; children: ReactNode }) {
  return <div className={`notice ${tone}`}><Icon name={icon} size={18} /><div>{children}</div></div>;
}

export function Empty({ icon = "sparkle", title, children }: { icon?: string; title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <span className="icon-circle"><Icon name={icon} size={24} /></span>
      <strong>{title}</strong>
      {children && <div className="small">{children}</div>}
    </div>
  );
}

export function Skeleton({ h = 18, w = "100%", r }: { h?: number; w?: number | string; r?: number }) {
  return <div className="skeleton" style={{ height: h, width: w, borderRadius: r }} aria-hidden />;
}

export function LoadingCards({ n = 3, h = 180 }: { n?: number; h?: number }) {
  return (
    <div className="grid-cards" aria-busy="true" aria-label="Loading">
      {Array.from({ length: n }, (_, i) => <Skeleton key={i} h={h} r={18} />)}
    </div>
  );
}

export function PageLoading() {
  return (
    <div className="page" aria-busy="true" aria-label="Loading">
      <Skeleton h={34} w="40%" />
      <Skeleton h={160} r={24} />
      <LoadingCards n={2} h={140} />
    </div>
  );
}

// ---- People --------------------------------------------------------------------------------------------

const AVATAR_COLORS = ["#4a1f3d", "#b9443a", "#1f6b5c", "#2f4f8f", "#7a5a12", "#6b2f73"];

function hash(text: string) {
  let h = 0;
  for (const ch of text) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return h;
}

export function personColor(name: string) {
  return AVATAR_COLORS[hash(name) % AVATAR_COLORS.length];
}

export function initials(name: string) {
  const parts = name.replace(/\(.*\)/, "").trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (/^\+?\d/.test(parts[0])) return "#";
  // First two names, so "Aunt Ann Smith" (AA) and "Alan Smith" (AS) stay distinct.
  return (parts[0][0] + (parts[1]?.[0] ?? "")).toUpperCase();
}

export function Avatar({ name, size = "", title }: { name: string; size?: "" | "sm" | "lg"; title?: string }) {
  return (
    <span className={`avatar ${size}`} style={{ background: personColor(name) }} title={title ?? name} aria-hidden={!title}>
      {initials(name)}
    </span>
  );
}

export function isPhoneOnly(name: string) {
  return !/[a-z]/i.test(name);
}

/** A person's avatar, or a phone icon for someone known only by number. */
export function Who({ name, size = "" }: { name: string; size?: "" | "sm" | "lg" }) {
  if (isPhoneOnly(name)) {
    const px = size === "sm" ? 28 : size === "lg" ? 48 : 36;
    return <span className="icon-circle" style={{ width: px, height: px }}><Icon name="phone" size={px / 2} /></span>;
  }
  return <Avatar name={name} size={size} />;
}

export function firstName(name: string) {
  return name.split(/\s+/)[0] ?? name;
}

// ---- Money ---------------------------------------------------------------------------------------------

export function Money({ value, currency = "USD", size = "md" }: { value: string | number; currency?: string; size?: "md" | "lg" | "xl" }) {
  return <span className={`amount ${size}`}>{money(value, currency)}</span>;
}

export function MoneyInput({ id, value, onChange, label, min = 1 }:
  { id: string; value: string; onChange: (v: string) => void; label: string; min?: number }) {
  return (
    <div className="money-input">
      <span aria-hidden>$</span>
      <input id={id} className="input" type="number" inputMode="decimal" min={min} step="0.01" value={value}
        aria-label={label} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

/** "Akha (Build)" -> ["Akha", "Build"] */
export function splitType(label: string): [string, string] {
  const m = label.match(/^(.*?)\s*\((.*)\)$/);
  return m ? [m[1], m[2]] : [label, ""];
}

export function productLabel(product: string) {
  return product ? product.replace(/_/g, " ") : "payment";
}
