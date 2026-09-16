import { Alert, Spin } from "antd";
import { useEffect, useState } from "react";
import "./styles/design-system.css";
import type { CrawlDataAdapter } from "./adapters/adapterInterface";
import { API_BASE, HttpAdapter } from "./adapters/httpAdapter";
import { MockAdapter } from "./adapters/mockAdapter";
import { LoginScreen } from "./components/auth/LoginScreen";
import { DashboardShell } from "./components/layout/DashboardShell";
import { isSessionValid, useAuthStore } from "./store/useAuthStore";
import { useCrawlStore } from "./store/useCrawlStore";

/**
 * Pick the live API when it answers, and fixtures when it does not.
 *
 * The fallback is announced rather than silent. Fixture data looks exactly like
 * crawl output on screen, so a user who started the UI without the server and
 * was quietly handed `example.com` would have no way to tell.
 */
async function chooseAdapter(): Promise<{
  adapter: CrawlDataAdapter;
  offline: boolean;
}> {
  try {
    const response = await fetch(`${API_BASE}/health`, {
      signal: AbortSignal.timeout(2_000),
    });
    if (response.ok) return { adapter: new HttpAdapter(API_BASE), offline: false };
  } catch {
    // Unreachable, which almost always means the server was never started.
  }
  return { adapter: new MockAdapter(), offline: true };
}

export default function App(): JSX.Element {
  const init = useCrawlStore((state) => state.init);
  const [offline, setOffline] = useState<boolean | null>(null);
  const [adapter, setAdapter] = useState<CrawlDataAdapter | null>(null);
  // Session-token auth (ADR 0016) has nothing to do with fixtures: `MockAdapter`
  // never leaves the browser, so it carries no boundary this could guard.
  // Only a live engine's first call is bearer-guarded, hence `offline ||
  // authenticated` below rather than gating unconditionally.
  const authenticated = useAuthStore(isSessionValid);

  useEffect(() => {
    void (async () => {
      const { adapter: chosen, offline: isOffline } = await chooseAdapter();
      setAdapter(chosen);
      setOffline(isOffline);
    })();
  }, []);

  useEffect(() => {
    if (!adapter) return;
    if (offline || authenticated) void init(adapter);
    // `init` never changes identity (zustand actions are stable), so this
    // fires again only when the adapter is chosen or `authenticated` flips —
    // in particular, the moment a login succeeds, which is what makes the
    // first authenticated request happen without a manual reload.
  }, [adapter, offline, authenticated, init]);

  if (offline === null || adapter === null) {
    return (
      <div
        style={{
          height: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "var(--bg)",
        }}
      >
        <Spin size="large" tip="Connecting…" />
      </div>
    );
  }

  if (!offline && !authenticated) {
    return <LoginScreen />;
  }

  return (
    <>
      {offline && (
        <Alert
          type="info"
          banner
          showIcon
          message={`Engine not reachable at ${API_BASE} — showing bundled fixtures. Start it with: python -m src.api.server`}
        />
      )}
      <DashboardShell />
    </>
  );
}
