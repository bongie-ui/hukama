import Icon from "../components/Icon";
import PublicAssistant from "../components/PublicAssistant";
import { ErrorNote, Notice, Skeleton } from "../components/ui";
import { api } from "../api";
import { useApi } from "../hooks";

interface BusinessView {
  verified: boolean;
  available?: boolean;
  email?: string;
  families?: { payee: string; family: string; upload: string; for: string[] }[];
}

/** "Send an invoice": a school or business logs in with the PayPal account that receives its payments and sees the
 * families it can invoice. No link to pass around. */
export default function Business({ login }: { login?: string | null }) {
  const view = useApi<BusinessView>("/public/business/");
  const logout = async () => { await api.post("/public/business/logout/"); void view.reload(); };
  const d = view.data;

  return (
    <div className="give">
      <header className="give-top">
        <a className="brand" href="#/"><img src="/favicon.svg" alt="" /><span>Hukama</span></a>
      </header>
      <main className="give-main">
        <section className="give-hero">
          <span className="eyebrow">For schools and businesses</span>
          <h1>Send an invoice to a family</h1>
          <p>Log in with the PayPal account that receives your payments. Hukama shows the families that pay you; send a photo of the invoice or quote, and approved payments come straight to that PayPal account.</p>
        </section>
        {login && login !== "ok" && <Notice tone="warn" icon="lock">{login}</Notice>}
        <ErrorNote error={view.error} />
        {!d && !view.error && <Skeleton h={160} r={18} />}
        {d && !d.verified && (
          <div className="card stack" style={{ gap: 12 }}>
            <h2>Log in with PayPal</h2>
            <span className="small ink-2">Use the PayPal account the family pays you on. Hukama only checks the email; it never sees your password.</span>
            {d.available === false
              ? <span className="small muted">PayPal isn't set up on this server.</span>
              : <a className="btn primary block lg" href="/api/public/business/login/"><Icon name="lock" size={18} />Log in with PayPal</a>}
            <span className="xs muted">Not listed yet? Ask the family to add you as a payee with your PayPal email.</span>
          </div>
        )}
        {d?.verified && (
          <>
            <div className="row between small" style={{ flexWrap: "nowrap" }}>
              <span className="row" style={{ gap: 6 }}><Icon name="check" size={16} />Logged in with PayPal as {d.email}</span>
              <button className="linkbtn small" onClick={logout}>Log out</button>
            </div>
            {(d.families ?? []).length === 0 ? (
              <div className="card"><span className="small muted">No family pays this PayPal account yet.</span></div>
            ) : (
              <section className="card stack">
                <h2>Families you can invoice</h2>
                <div className="list">
                  {d.families!.map((f) => (
                    <a key={f.upload} className="list-item" style={{ paddingInline: 0 }} href={`#/supplier/${f.upload}`}>
                      <span className="type-icon" style={{ width: 38, height: 38 }}><Icon name="send" size={18} /></span>
                      <div className="main"><span className="title">{f.family}</span><span className="sub">as {f.payee} · {f.for.join(", ")}</span></div>
                      <span className="btn primary sm">Send</span>
                    </a>
                  ))}
                </div>
              </section>
            )}
          </>
        )}
      </main>
      <PublicAssistant />
    </div>
  );
}
