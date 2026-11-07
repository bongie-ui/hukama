import { useState, type FormEvent } from "react";
import { api } from "../api";
import Icon from "../components/Icon";
import { Avatar, ErrorNote, Skeleton } from "../components/ui";
import { useAction, useApi, useSession } from "../hooks";
import type { Me } from "../types";

const COUNTRY: Record<string, string> = { ZA: "Johannesburg", US: "United States", GB: "United Kingdom", ZW: "Zimbabwe" };

export default function Login() {
  const { session, refresh } = useSession();
  const demo = useApi<Me[]>(session.demo_mode ? "/auth/demo-users/" : null);
  const { busy, error, run } = useAction();
  const [who, setWho] = useState<string | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [signingUp, setSigningUp] = useState(false);

  const asPersona = (u: string) => {
    setWho(u);
    void run(async () => {
      await api.post("/auth/demo-login/", { username: u });
      await refresh();
    });
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      await api.post("/auth/login/", { username, password });
      await refresh();
    });
  };

  return (
    <div className="login">
      <section className="login-brand">
        <span className="brand"><img src="/favicon.svg" alt="" /><span>Hukama</span></span>
        <div className="stack" style={{ gap: 18 }}>
          <h1>Send home with <em>rules</em>, not worry.</h1>
          <p>Family abroad funds a shared mandate. The builder, the school or mobile money gets paid directly, and only when the rules you agreed are met.</p>
          <div className="points">
            <div><Icon name="check" />Pays suppliers and schools directly through PayPal</div>
            <div><Icon name="check" />Siblings share caps, so nobody tops up twice</div>
            <div><Icon name="check" />Scam messages are held until you call home</div>
          </div>
        </div>
        <p className="meaning">Hukama (Shona): kinship, the ties that hold a family together.<br />
          <a href="/legal/privacy/" style={{ color: "inherit" }}>Privacy</a> · <a href="/legal/terms/" style={{ color: "inherit" }}>Terms</a></p>
      </section>

      <section className="login-panel">
        {signingUp ? <Signup onCancel={() => setSigningUp(false)} onDone={refresh} /> : <div>
          {session.demo_mode && (
            <div className="stack">
              <div className="stack-sm">
                <h2>Try the demo</h2>
                <p className="muted small">Choose a family member. Each one supports home from a different country.</p>
              </div>
              {demo.loading && !demo.data && [0, 1, 2].map((i) => <Skeleton key={i} h={72} r={18} />)}
              {demo.data?.length === 0 && <div className="notice info">No demo family yet. Run <code>python manage.py seed_demo</code>.</div>}
              {demo.data?.map((u) => (
                <button key={u.username} className="persona" disabled={busy} onClick={() => asPersona(u.username)}>
                  <Avatar name={u.name} size="lg" />
                  <div>
                    <strong>{u.name}</strong>
                    <span>{COUNTRY[u.country] ?? u.country}{u.role === "ADMIN" ? " · family admin" : ""}</span>
                  </div>
                  {busy && who === u.username ? <span className="spinner" /> : <Icon name="chevron" />}
                </button>
              ))}
            </div>
          )}

          {session.demo_mode && <div className="or">or sign in</div>}

          <form className="stack" onSubmit={submit}>
            {!session.demo_mode && <h2>Sign in</h2>}
            <div className="field">
              <label htmlFor="u">Username</label>
              <input id="u" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="p">Password</label>
              <input id="p" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
            </div>
            <button className="btn primary block lg" disabled={busy || !username || !password}>Sign in</button>
          </form>
          <ErrorNote error={error} />
          <div className="or">new to Hukama?</div>
          <button className="btn outline block lg" onClick={() => setSigningUp(true)}><Icon name="people" size={18} />Start your family</button>
        </div>}
      </section>
    </div>
  );
}

const COUNTRIES: [string, string][] = [["ZA", "South Africa"], ["GB", "United Kingdom"], ["US", "United States"],
  ["BW", "Botswana"], ["AU", "Australia"], ["CA", "Canada"], ["IE", "Ireland"], ["ZW", "Zimbabwe"]];

/** A new family: the person becomes its admin and can then add people at home, payees and the rest of the family. */
function Signup({ onCancel, onDone }: { onCancel: () => void; onDone: () => Promise<void> | void }) {
  const [form, setForm] = useState({ first_name: "", last_name: "", email: "", password: "", family_name: "", country: "", phone: "" });
  const { busy, error, run } = useAction();
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      await api.post("/auth/signup/", form);
      await onDone();
    });
  };
  return (
    <form className="stack" onSubmit={submit}>
      <div className="stack-sm">
        <h2>Start your family</h2>
        <p className="muted small">You'll be the family's admin. Next you add the people you support at home, who gets paid, and the rest of the family.</p>
      </div>
      <div className="form-grid">
        <div className="field"><label htmlFor="s-first">First name</label><input id="s-first" autoComplete="given-name" value={form.first_name} onChange={set("first_name")} /></div>
        <div className="field"><label htmlFor="s-last">Last name</label><input id="s-last" autoComplete="family-name" value={form.last_name} onChange={set("last_name")} /></div>
      </div>
      <div className="field"><label htmlFor="s-fam">Family name</label><input id="s-fam" placeholder={form.last_name ? `${form.last_name} family` : "e.g. the Moyo family"} value={form.family_name} onChange={set("family_name")} /></div>
      <div className="field"><label htmlFor="s-email">Email</label><input id="s-email" type="email" autoComplete="email" value={form.email} onChange={set("email")} />
        <span className="hint">Use the email of your PayPal account, so funding is easy.</span></div>
      <div className="field"><label htmlFor="s-pass">Password</label><input id="s-pass" type="password" autoComplete="new-password" value={form.password} onChange={set("password")} />
        <span className="hint">At least 8 characters, not a common password.</span></div>
      <div className="form-grid">
        <div className="field">
          <label htmlFor="s-country">You live in</label>
          <select id="s-country" value={form.country} onChange={set("country")}>
            <option value="">Choose…</option>
            {COUNTRIES.map(([c, n]) => <option key={c} value={c}>{n}</option>)}
          </select>
        </div>
        <div className="field"><label htmlFor="s-phone">Phone <span className="muted">(optional)</span></label><input id="s-phone" inputMode="tel" placeholder="+44…" value={form.phone} onChange={set("phone")} /></div>
      </div>
      <button className="btn primary block lg" disabled={busy || !form.first_name || !form.email || !form.password}>{busy ? <span className="spinner" /> : null}Create my family</button>
      <button type="button" className="linkbtn small" style={{ alignSelf: "center" }} onClick={onCancel}>I already have an account</button>
      <ErrorNote error={error} />
    </form>
  );
}
