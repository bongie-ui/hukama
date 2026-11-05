import { useState } from "react";
import { api } from "../api";
import Icon from "../components/Icon";
import { Avatar, ErrorNote, Notice, SimTag, Skeleton } from "../components/ui";
import { useAction, useApi } from "../hooks";
import type { Beneficiary, Family, Payee } from "../types";

const PRODUCTS = ["airtime", "bundles", "cash", "groceries"];
const PAYEE_KINDS: [string, string][] = [
  ["SUPPLIER", "Supplier"], ["SCHOOL", "School"], ["FUNERAL_PROVIDER", "Funeral provider"], ["MEDICAL_AID", "Medical aid"], ["OTHER", "Other"],
];
const COUNTRY: Record<string, string> = { ZA: "South Africa", US: "United States", GB: "United Kingdom", ZW: "Zimbabwe" };

export default function People() {
  const beneficiaries = useApi<Beneficiary[]>("/beneficiaries/");
  const payees = useApi<Payee[]>("/payees/");
  const family = useApi<Family>("/family/");

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>People</h1>
          <p>Who the family supports, who can be paid, and who funds it. Only registered numbers are trusted.</p>
        </div>
      </header>

      <section className="section" aria-labelledby="ben-h">
        <div className="section-head"><h2 id="ben-h">Supported at home</h2></div>
        <ErrorNote error={beneficiaries.error} />
        <div className="grid-cards">
          {beneficiaries.loading && !beneficiaries.data && <Skeleton h={150} r={18} />}
          {beneficiaries.data?.map((b) => <BeneficiaryCard key={b.id} b={b} onSaved={beneficiaries.reload} />)}
          <AddBeneficiary onSaved={beneficiaries.reload} />
        </div>
      </section>

      <section className="section" aria-labelledby="pay-h">
        <div className="section-head"><h2 id="pay-h">Payees</h2><span className="small muted">Paid directly. Real payouts go through PayPal.</span></div>
        <ErrorNote error={payees.error} />
        <div className="card flush">
          <div className="list">
            {payees.loading && !payees.data && <div style={{ padding: 18 }}><Skeleton h={44} /></div>}
            {payees.data?.map((p) => (
              <div className="list-item" key={p.id}>
                <span className="type-icon" style={{ width: 38, height: 38 }}><Icon name={p.kind === "SCHOOL" ? "school" : p.kind === "SUPPLIER" ? "build" : p.kind === "MOBILE_MONEY_PROVIDER" ? "airtime" : p.kind === "GROCER" ? "groceries" : p.kind === "FUNERAL_PROVIDER" ? "flower" : "health"} size={18} /></span>
                <div className="main">
                  <span className="title">{p.name}</span>
                  <span className="sub">{p.kind_label}{p.phone ? ` · ${p.phone}` : ""}</span>
                </div>
                <div className="end">
                  {p.verified ? <span className="pill ok">Verified</span> : <span className="pill warn">Not verified</span>}
                  {p.rail === "BILLER_SIM" ? <SimTag /> : p.rail === "LOCAL_MOBILE_MONEY" ? <SimTag label="Simulated last mile" /> : <span className="xs muted">PayPal Payout</span>}
                </div>
              </div>
            ))}
          </div>
        </div>
        <AddPayee onSaved={payees.reload} />
      </section>

      <section className="section" aria-labelledby="fam-h">
        <div className="section-head"><h2 id="fam-h">{family.data?.name ?? "Family"}</h2></div>
        <div className="grid-cards">
          {family.data?.members.map((m) => (
            <div className="card row" key={m.user_id} style={{ flexWrap: "nowrap" }}>
              <Avatar name={m.name} size="lg" />
              <div className="stack-sm" style={{ gap: 2, minWidth: 0 }}>
                <strong>{m.name}</strong>
                <span className="small muted">{COUNTRY[m.country] ?? m.country}{m.role === "ADMIN" ? " · admin" : m.role === "VIEWER" ? " · viewer" : " · funder"}</span>
              </div>
            </div>
          ))}
        </div>
        {family.data?.role === "ADMIN" && <InviteMember onSaved={family.reload} />}
      </section>
    </div>
  );
}

function BeneficiaryCard({ b, onSaved }: { b: Beneficiary; onSaved: () => void }) {
  const [editing, setEditing] = useState(false);
  const [phone, setPhone] = useState(b.phone);
  const { busy, error, run } = useAction();
  const save = () => run(async () => {
    await api.patch(`/beneficiaries/${b.id}/`, { phone });
    setEditing(false);
    onSaved();
  });

  return (
    <div className="card stack">
      <div className="row" style={{ flexWrap: "nowrap" }}>
        <Avatar name={b.name} size="lg" />
        <div className="stack-sm" style={{ gap: 2, minWidth: 0 }}>
          <strong>{b.name}</strong>
          <span className="small muted">{b.relationship} · <span className="num">{b.phone}</span></span>
          {b.address && <span className="xs muted row" style={{ gap: 4 }}><Icon name="home" size={14} />{b.address}</span>}
        </div>
      </div>
      <div className="row" style={{ gap: 6 }}>{b.allowed_products.map((p) => <span key={p} className="pill brand plain">{p}</span>)}</div>
      {b.phone_recently_changed && <Notice tone="warn">Number changed recently. Extra fraud checks apply for 72 hours.</Notice>}
      {editing ? (
        <div className="stack">
          <Notice tone="warn">Scammers often ask families to “update” a number first. After a change, every request for {b.name.split(" ")[0]} gets extra checks for 72 hours.</Notice>
          <div className="field">
            <label htmlFor={`ph-${b.id}`}>New registered number</label>
            <input id={`ph-${b.id}`} value={phone} onChange={(e) => setPhone(e.target.value)} inputMode="tel" />
          </div>
          <div className="row">
            <button className="btn primary sm" disabled={busy || phone === b.phone} onClick={save}>Save number</button>
            <button className="btn outline sm" onClick={() => { setEditing(false); setPhone(b.phone); }}>Cancel</button>
          </div>
          <ErrorNote error={error} />
        </div>
      ) : (
        <button className="linkbtn small" style={{ alignSelf: "flex-start" }} onClick={() => setEditing(true)}>Change registered number</button>
      )}
    </div>
  );
}

function AddBeneficiary({ onSaved }: { onSaved: () => void }) {
  const empty = { name: "", relationship: "", phone: "", address: "", allowed_products: ["airtime", "bundles"] };
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(empty);
  const { busy, error, run } = useAction();
  const save = () => run(async () => {
    await api.post("/beneficiaries/", form);
    setOpen(false);
    setForm(empty);
    onSaved();
  });
  if (!open) {
    return (
      <button className="card" onClick={() => setOpen(true)} style={{ borderStyle: "dashed", cursor: "pointer", display: "grid", placeItems: "center", minHeight: 150, color: "var(--primary)", fontWeight: 700 }}>
        <span className="row"><Icon name="plus" />Register someone at home</span>
      </button>
    );
  }
  return (
    <div className="card stack">
      <h3>Register someone at home</h3>
      <div className="field"><label htmlFor="b-name">Full name</label><input id="b-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
      <div className="form-grid">
        <div className="field"><label htmlFor="b-rel">Relationship</label><input id="b-rel" placeholder="Mother" value={form.relationship} onChange={(e) => setForm({ ...form, relationship: e.target.value })} /></div>
        <div className="field"><label htmlFor="b-phone">Phone</label><input id="b-phone" inputMode="tel" placeholder="0771 234 567" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></div>
      </div>
      <div className="field"><label htmlFor="b-addr">Delivery address <span className="muted">(groceries are only ever delivered here)</span></label>
        <input id="b-addr" value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} placeholder="Stand number, suburb, town" /></div>
      <div className="field">
        <span className="label">What can be sent</span>
        <div className="checks">
          {PRODUCTS.map((p) => (
            <label key={p} className="check">
              <input type="checkbox" checked={form.allowed_products.includes(p)} onChange={(e) => setForm({
                ...form, allowed_products: e.target.checked ? [...form.allowed_products, p] : form.allowed_products.filter((x) => x !== p),
              })} />
              <Icon name={p} size={16} />{p}
            </label>
          ))}
        </div>
      </div>
      <div className="row">
        <button className="btn primary" disabled={busy || !form.name || !form.phone} onClick={save}>Register</button>
        <button className="btn outline" onClick={() => setOpen(false)}>Cancel</button>
      </div>
      <ErrorNote error={error} />
    </div>
  );
}

function InviteMember({ onSaved }: { onSaved: () => void }) {
  const empty = { first_name: "", last_name: "", email: "", country: "", phone: "", role: "FUNDER" };
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(empty);
  const [sent, setSent] = useState<{ name: string; email: string; password: string | null } | null>(null);
  const { busy, error, run } = useAction();
  const save = () => run(async () => {
    const r = await api.post<{ name: string; username: string; temporary_password: string | null }>("/family/invite/", form);
    setSent({ name: r.name, email: form.email, password: r.temporary_password });
    setOpen(false);
    setForm(empty);
    onSaved();
  });
  const set = (k: keyof typeof empty) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });

  if (!open) return (
    <div className="stack" style={{ gap: 12 }}>
      {sent && (
        <Notice tone="ok" icon="check">
          {sent.name} is in the family.{sent.password
            ? <> Send them, privately: sign in with <strong>{sent.email}</strong> and the temporary password <strong className="num">{sent.password}</strong>. It is shown only once.</>
            : " They already had an account and can sign in as usual."}
        </Notice>
      )}
      <button className="btn outline" style={{ alignSelf: "flex-start" }} onClick={() => { setOpen(true); setSent(null); }}><Icon name="plus" size={18} />Invite a family member</button>
    </div>
  );
  return (
    <div className="card stack">
      <div className="stack-sm"><h3>Invite a family member</h3><span className="small muted">Funders can add money and make requests. Viewers can only see what happens.</span></div>
      <div className="form-grid">
        <div className="field"><label htmlFor="i-first">First name</label><input id="i-first" value={form.first_name} onChange={set("first_name")} /></div>
        <div className="field"><label htmlFor="i-last">Last name</label><input id="i-last" value={form.last_name} onChange={set("last_name")} /></div>
        <div className="field"><label htmlFor="i-email">Email</label><input id="i-email" type="email" value={form.email} onChange={set("email")} /></div>
        <div className="field"><label htmlFor="i-phone">Phone <span className="muted">(with country code)</span></label><input id="i-phone" inputMode="tel" value={form.phone} onChange={set("phone")} /></div>
        <div className="field">
          <label htmlFor="i-country">Lives in</label>
          <select id="i-country" value={form.country} onChange={set("country")}>
            <option value="">Choose…</option>
            {Object.entries(COUNTRY).map(([code, name]) => <option key={code} value={code}>{name}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="i-role">Role</label>
          <select id="i-role" value={form.role} onChange={set("role")}>
            <option value="FUNDER">Funder</option><option value="VIEWER">Viewer</option>
          </select>
        </div>
      </div>
      <div className="row">
        <button className="btn primary" disabled={busy || !form.first_name || !form.email} onClick={save}>Invite</button>
        <button className="btn outline" onClick={() => setOpen(false)}>Cancel</button>
      </div>
      <ErrorNote error={error} />
    </div>
  );
}

function AddPayee({ onSaved }: { onSaved: () => void }) {
  const empty = { name: "", kind: "SUPPLIER", paypal_email: "", phone: "" };
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(empty);
  const { busy, error, run } = useAction();
  const save = () => run(async () => {
    await api.post("/payees/", { ...form, rail: "PAYPAL_PAYOUT" });
    setOpen(false);
    setForm(empty);
    onSaved();
  });
  if (!open) return <button className="btn outline" style={{ alignSelf: "flex-start" }} onClick={() => setOpen(true)}><Icon name="plus" size={18} />Add a payee</button>;
  return (
    <div className="card stack">
      <div className="stack-sm"><h3>Add a payee</h3><span className="small muted">New payees start unverified and cannot be paid until Hukama checks them. Then they are paid by PayPal Payout to their PayPal email.</span></div>
      <div className="form-grid">
        <div className="field"><label htmlFor="p-name">Business name</label><input id="p-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
        <div className="field">
          <label htmlFor="p-kind">Kind</label>
          <select id="p-kind" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
            {PAYEE_KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </div>
        <div className="field"><label htmlFor="p-email">PayPal email</label><input id="p-email" type="email" value={form.paypal_email} onChange={(e) => setForm({ ...form, paypal_email: e.target.value })} /></div>
        <div className="field"><label htmlFor="p-phone">Chat number <span className="muted">(optional)</span></label><input id="p-phone" inputMode="tel" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></div>
      </div>
      <div className="row">
        <button className="btn primary" disabled={busy || !form.name || !form.paypal_email} onClick={save}>Add payee</button>
        <button className="btn outline" onClick={() => setOpen(false)}>Cancel</button>
      </div>
      <ErrorNote error={error} />
    </div>
  );
}
