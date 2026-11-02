import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import Icon from "./components/Icon";
import { Avatar, ErrorNote, PageLoading } from "./components/ui";
import { SessionContext, useApi, usePoll, useSession } from "./hooks";
import Chat from "./pages/Chat";
import DashboardPage from "./pages/DashboardPage";
import Home from "./pages/Home";
import Inbox from "./pages/Inbox";
import Login from "./pages/Login";
import MandateDetail from "./pages/MandateDetail";
import NewMandate from "./pages/NewMandate";
import People from "./pages/People";
import RequestDetail from "./pages/RequestDetail";
import { match, usePath } from "./router";
import type { PayRequest, Session } from "./types";

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setSession(await api.get<Session>("/auth/me/"));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  if (!session) {
    return (
      <main className="content">
        {error ? <div className="page narrow"><ErrorNote error={error} /><button className="btn" onClick={refresh}>Try again</button></div> : <PageLoading />}
      </main>
    );
  }
  return (
    <SessionContext.Provider value={{ session, refresh }}>
      {session.authenticated ? <Shell /> : <Login />}
    </SessionContext.Provider>
  );
}

const NAV = [
  { href: "/", key: "home", label: "Home", icon: "home" },
  { href: "/inbox", key: "inbox", label: "Approvals", icon: "shield" },
  { href: "/dashboard", key: "dashboard", label: "Dashboard", icon: "chart" },
  { href: "/chat", key: "chat", label: "Assistant", icon: "chat" },
  { href: "/people", key: "people", label: "People", icon: "people" },
];

function Shell() {
  const path = usePath();
  const { session, refresh } = useSession();
  const inbox = useApi<PayRequest[]>("/requests/?inbox=1");
  usePoll(inbox.reload, 15000, true);
  useEffect(() => {
    void inbox.reload(); // an approval elsewhere may have cleared the count
  }, [path]); // eslint-disable-line react-hooks/exhaustive-deps

  const section = path.split(/[/?]/)[1] || "home";
  const active = (key: string) => section === key || (key === "home" && (section === "mandates" || section === "requests"));
  const count = inbox.data?.length ?? 0;
  const user = session.user!;
  const logout = async () => {
    await api.post("/auth/logout/");
    window.location.hash = "/";
    await refresh();
  };

  return (
    <div className="shell">
      <aside className="sidebar" aria-label="Main">
        <a className="brand" href="#/"><img src="/favicon.svg" alt="" /><span>Hukama</span></a>
        {NAV.map((n) => (
          <a key={n.key} className="navlink" href={`#${n.href}`} aria-current={active(n.key) ? "page" : undefined}>
            <Icon name={n.icon} />{n.label}
            {n.key === "inbox" && count > 0 && <span className="count" aria-label={`${count} waiting`}>{count}</span>}
          </a>
        ))}
        <a className="navlink" href="#/mandates/new" style={{ marginTop: 8 }}><Icon name="plus" />New mandate</a>
        <div className="me">
          <Avatar name={user.name} />
          <div>
            <strong>{user.name}</strong>
            <span className="xs muted">{user.family?.name}</span>
          </div>
          <button className="btn ghost icon-only" onClick={logout} title={session.demo_mode ? "Switch person" : "Log out"}
            aria-label={session.demo_mode ? "Switch person" : "Log out"}><Icon name="logout" /></button>
        </div>
      </aside>

      <header className="topbar">
        <a className="brand" href="#/"><img src="/favicon.svg" alt="" /><span>Hukama</span></a>
        <button className="btn ghost sm" onClick={logout} aria-label={session.demo_mode ? "Switch person" : "Log out"}>
          <Avatar name={user.name} size="sm" />{session.demo_mode ? "Switch" : "Log out"}
        </button>
      </header>

      <main className="content" id="main">
        <Route path={path} />
      </main>

      <nav className="tabbar" aria-label="Main">
        {NAV.map((n) => (
          <a key={n.key} href={`#${n.href}`} aria-current={active(n.key) ? "page" : undefined}>
            <Icon name={n.icon} size={22} />{n.label}
            {n.key === "inbox" && count > 0 && <span className="count">{count}</span>}
          </a>
        ))}
      </nav>
    </div>
  );
}

function Route({ path }: { path: string }) {
  let m;
  if (path === "/" || path === "") return <Home />;
  if (path === "/mandates/new") return <NewMandate />;
  if ((m = match("/mandates/:id", path))) return <MandateDetail id={m.id} />;
  if ((m = match("/requests/:id", path))) return <RequestDetail id={m.id} />;
  if (path.startsWith("/inbox")) return <Inbox />;
  if (path.startsWith("/chat")) return <Chat path={path} />;
  if (path.startsWith("/dashboard")) return <DashboardPage />;
  if (path.startsWith("/people")) return <People />;
  return (
    <div className="page narrow">
      <div className="card"><div className="empty"><strong>Page not found</strong><a href="#/">Go home</a></div></div>
    </div>
  );
}
