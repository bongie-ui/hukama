import { useState } from "react";
import { api, newKey } from "../api";
import { useAction, useApi } from "../hooks";
import { navigate } from "../router";
import type { Mandate, Payee, RequestDetail } from "../types";
import Icon from "./Icon";
import { ErrorNote, MoneyInput } from "./ui";

export const EVIDENCE_KINDS: [string, string][] = [
  ["QUOTE", "Quote"], ["INVOICE", "Invoice"], ["MILESTONE_PHOTO", "Progress photo"], ["RECEIPT", "Receipt"], ["OTHER", "Other"],
];

export async function uploadFile(file: File) {
  const form = new FormData();
  form.append("file", file);
  return api.post<{ id: string; name: string; content_type: string }>("/uploads/", form);
}

function allowedPayeeIds(m: Mandate) {
  return m.rules.filter((r) => r.kind === "allowed_payees").flatMap((r) => (r.params.payee_ids as string[]) ?? []);
}

function guessKind(file: File) {
  const n = file.name.toLowerCase();
  if (n.includes("invoice")) return "INVOICE";
  if (n.includes("quote")) return "QUOTE";
  if (n.includes("receipt")) return "RECEIPT";
  return file.type.startsWith("image/") ? "MILESTONE_PHOTO" : "OTHER";
}

/** Ask to pay a supplier, school or provider from a mandate, with quotes, invoices or photos attached. */
export default function RequestForm({ mandate }: { mandate: Mandate }) {
  const payees = useApi<Payee[]>("/payees/");
  const ids = allowedPayeeIds(mandate);
  const options = payees.data?.filter((p) => ids.includes(p.id)) ?? [];
  const [payee, setPayee] = useState("");
  // The mandate type fixes what the money is for; only other mandates ask.
  const fixedProduct = mandate.type === "IMFUNDO" ? "school_fees" : mandate.type === "AKHA" ? "materials" : mandate.type === "ISILILO" ? "funeral" : "";
  const [product, setProduct] = useState(fixedProduct);
  const [amount, setAmount] = useState("");
  const [message, setMessage] = useState("");
  const [files, setFiles] = useState<{ file: File; kind: string }[]>([]);
  const { busy, error, run } = useAction();

  const submit = () => run(async () => {
    const uploads = [];
    for (const f of files) uploads.push({ upload_id: (await uploadFile(f.file)).id, kind: f.kind });
    const r = await api.post<RequestDetail>("/requests/", {
      mandate: mandate.id, payee: payee || options[0]?.id, product, amount, message_text: message, uploads,
      idempotency_key: newKey(),
    });
    navigate(`/requests/${r.id}`);
  });

  return (
    <section className="card stack" aria-labelledby="rf-h" style={{ gap: 16 }}>
      <div className="stack-sm">
        <h2 id="rf-h">Request a payment</h2>
        <span className="small muted">Attach the quote, invoice or progress photo. The assistant reads it and the rules decide.</span>
      </div>
      <div className="form-grid">
        <div className="field">
          <label htmlFor="rf-payee">Pay</label>
          {options.length > 1 ? (
            <select id="rf-payee" value={payee || options[0]?.id || ""} onChange={(e) => setPayee(e.target.value)}>
              {options.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          ) : <span id="rf-payee" className="input" style={{ display: "flex", alignItems: "center" }}>{options[0]?.name ?? "No payee yet"}</span>}
        </div>
        {!fixedProduct && (
          <div className="field">
            <label htmlFor="rf-product">For</label>
            <input id="rf-product" placeholder="e.g. materials" value={product} onChange={(e) => setProduct(e.target.value)} />
          </div>
        )}
        <div className="field">
          <label htmlFor="rf-amount">Amount</label>
          <MoneyInput id="rf-amount" label="Amount in US dollars" value={amount} onChange={setAmount} />
        </div>
      </div>
      <div className="field">
        <label htmlFor="rf-msg">Note <span className="muted">(optional)</span></label>
        <input id="rf-msg" value={message} onChange={(e) => setMessage(e.target.value)} placeholder="e.g. Cement for the foundation" />
      </div>
      <div className="field">
        <span className="label">Documents</span>
        <label className="btn outline" style={{ alignSelf: "flex-start" }}>
          <Icon name="clip" size={18} />Attach quote, invoice or photo
          <input type="file" accept="image/*" multiple hidden
            onChange={(e) => { setFiles([...files, ...Array.from(e.target.files ?? []).map((file) => ({ file, kind: guessKind(file) }))]); e.target.value = ""; }} />
        </label>
        {files.length > 0 && (
          <div className="row" style={{ gap: 6 }}>
            {files.map((f, i) => (
              <span className="chip" key={i}>
                {f.file.name}
                <select aria-label={`What is ${f.file.name}?`} value={f.kind}
                  onChange={(e) => setFiles(files.map((x, j) => (j === i ? { ...x, kind: e.target.value } : x)))}>
                  {EVIDENCE_KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                </select>
                <button aria-label={`Remove ${f.file.name}`} onClick={() => setFiles(files.filter((_, j) => j !== i))}><Icon name="x" size={12} /></button>
              </span>
            ))}
          </div>
        )}
      </div>
      <button className="btn primary lg" disabled={busy || !product || Number(amount) <= 0 || options.length === 0} onClick={submit}>
        {busy ? <><span className="spinner" />Reading documents and checking the rules…</> : "Submit for checking"}
      </button>
      <ErrorNote error={error} />
    </section>
  );
}
