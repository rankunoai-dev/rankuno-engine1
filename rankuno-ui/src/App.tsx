import { Spin } from "antd";
import { useEffect } from "react";
import { MockAdapter } from "./adapters/mockAdapter";
import { HeaderBar } from "./components/layout/HeaderBar";
import { DirectoryPane } from "./components/visualizer/DirectoryPane";
import { PageDetailDrawer } from "./components/visualizer/PageDetailDrawer";
import { ReactFlowGraph } from "./components/visualizer/ReactFlowGraph";
import { SplitPaneLayout } from "./components/visualizer/SplitPaneLayout";
import { useCrawlStore } from "./store/useCrawlStore";

// The single place the data source is chosen. Swapping to an HTTP adapter when
// the API exists is this line, because nothing else imports fixtures directly.
const adapter = new MockAdapter();

export default function App(): JSX.Element {
  const init = useCrawlStore((state) => state.init);
  const status = useCrawlStore((state) => state.status);

  useEffect(() => {
    void init(adapter);
  }, [init]);

  return (
    <div style={{ height: "100vh", display: "flex", flexDirection: "column" }}>
      <HeaderBar />

      {status === "running" || status === "queued" ? (
        <div
          style={{
            flex: 1,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <Spin size="large" tip="Loading crawl…" />
        </div>
      ) : (
        <SplitPaneLayout left={<DirectoryPane />} right={<ReactFlowGraph />} />
      )}

      <PageDetailDrawer />
    </div>
  );
}
