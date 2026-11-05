import { useState } from "react";
import { api } from "../api";
import { useAction } from "../hooks";
import Icon from "./Icon";
import { ErrorNote } from "./ui";

/** A private link for someone without an account: a payee's upload link or a beneficiary's shop link. */
export default function LinkPanel({ token, route, endpoint, intro, empty, onChange, pinNote }:
  { token?: string | null; route: string; endpoint: string; intro: string; empty: string; onChange: () => void;
    pinNote?: string }) {
  const { busy, error, run } = useAction();
  const [copied, setCopied] = useState(false);
  const [pin, setPin] = useState<string | null>(null);
  const link = token ? `${window.location.origin}/#/${route}/${token}` : "";
  const change = (method: "post" | "delete", body?: unknown) => run(async () => {
    const r = await (method === "post" ? api.post<{ pin?: string | null }>(endpoint, body) : api.delete(endpoint));
    setPin((r as { pin?: string | null } | null)?.pin ?? null);
    onChange();
  });
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      (document.getElementById(`link-${endpoint}`) as HTMLInputElement | null)?.select();
    }
  };
  return (
    <div className="stack" style={{ gap: 10, flexBasis: "100%", paddingTop: 8 }}>
      {link ? (
        <>
          <span className="small ink-2">{intro}</span>
          {pin && (
            <div className="notice warn" role="status"><Icon name="lock" size={18} />
              <div><strong>PIN: <span className="num" style={{ fontSize: "1.25em", letterSpacing: ".15em" }}>{pin}</span></strong> {pinNote} It is shown only now.</div>
            </div>
          )}
          <div className="row" style={{ flexWrap: "nowrap" }}>
            <input id={`link-${endpoint}`} className="input" readOnly value={link} onFocus={(e) => e.target.select()} style={{ minWidth: 0 }} />
            <button className="btn primary" onClick={copy}>{copied ? "Copied" : "Copy link"}</button>
          </div>
          <div className="row between">
            <a className="small" href={`#/${route}/${token}`} target="_blank" rel="noreferrer">Preview the page</a>
            <div className="row" style={{ gap: 14 }}>
              {pinNote && <button className="linkbtn small" disabled={busy} onClick={() => change("post", { reset_pin: true })}>New PIN</button>}
              <button className="linkbtn small" disabled={busy} onClick={() => change("post", { new: true })}>New link</button>
              <button className="linkbtn small" disabled={busy} onClick={() => change("delete")}>Turn off</button>
            </div>
          </div>
        </>
      ) : (
        <div className="row between">
          <span className="small ink-2">{empty}</span>
          <button className="btn primary sm" disabled={busy} onClick={() => change("post")}>Create link</button>
        </div>
      )}
      <ErrorNote error={error} />
    </div>
  );
}
