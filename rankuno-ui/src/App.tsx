import { Alert, Spin } from "antd";
import { useEffect, useState } from "react";
import "./styles/design-system.css";
import type { CrawlDataAdapter } from "./adapters/adapterInterface";
import { API_BASE, HttpAdapter } from "./adapters/httpAdapter";
import { MockAdapter } from "./adapters/mockAdapter";
import { DashboardShell } from "./components/layout/DashboardShell";
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

  useEffect(() => {
    void (async () => {
      const { adapter, offline: isOffline } = await chooseAdapter();
      setOffline(isOffline);
      await init(adapter);
    })();
  }, [init]);

  if (offline === null) {
    return (
      <div
        style={{
          height: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#f5f6f8",
        }}
      >
        <Spin size="large" tip="Connecting…" />
      </div>
    );
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
