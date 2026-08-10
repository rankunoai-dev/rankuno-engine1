import { Alert, Spin } from "antd";
import { useEffect, useState } from "react";
import type { CrawlDataAdapter } from "./adapters/adapterInterface";
import { DEFAULT_API_BASE, HttpAdapter } from "./adapters/httpAdapter";
import { MockAdapter } from "./adapters/mockAdapter";
import { HeaderBar } from "./components/layout/HeaderBar";
import { DirectoryPane } from "./components/visualizer/DirectoryPane";
import { PageDetailDrawer } from "./components/visualizer/PageDetailDrawer";
import { ReactFlowGraph } from "./components/visualizer/ReactFlowGraph";
import { SplitPaneLayout } from "./components/visualizer/SplitPaneLayout";
import { useCrawlStore } from "./store/useCrawlStore";

const API_BASE = import.meta.env["VITE_API_BASE"] ?? DEFAULT_API_BASE;

/**
 * Pick the live API when it answers, and fixtures when it does not.
 *
 * The fallback is announced rather than silent. Fixture data looks exactly like
 * crawl output on screen, so a user who started the UI without the server and
 * was quietly handed `example.com` would have no way to tell they were reading
 * generated data.
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
  const status = useCrawlStore((state) => state.status);
  const [offline, setOffline] = useState<boolean | null>(null);

  useEffect(() => {
    void (async () => {
      const { adapter, offline: isOffline } = await chooseAdapter();
      setOffline(isOffline);
      await init(adapter);
    })();
  }, [init]);

  const busy = status === "running" || status === "queued";

  return (
    <div style={{ height: "100vh", display: "flex", flexDirection: "column" }}>
      {offline === true && (
        <Alert
          type="info"
          banner
          showIcon
          message={`Engine not reachable at ${API_BASE} — showing bundled fixtures. Start it with: python -m src.api.server`}
        />
      )}

      <HeaderBar />

      {offline === null || busy ? (
        <div
          style={{
            flex: 1,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <Spin size="large" tip={busy ? "Crawling…" : "Connecting…"} />
        </div>
      ) : (
        <SplitPaneLayout left={<DirectoryPane />} right={<ReactFlowGraph />} />
      )}

      <PageDetailDrawer />
    </div>
  );
}
