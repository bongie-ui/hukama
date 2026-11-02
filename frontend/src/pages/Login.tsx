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
        <p className="meaning">Hukama (Shona): kinship, the ties that hold a family together.</p>
      </section>

      <section className="login-panel">
        <div>
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
        </div>
      </section>
    </div>
  );
}
