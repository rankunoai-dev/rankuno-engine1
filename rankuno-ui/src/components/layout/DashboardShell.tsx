import { FilePdfOutlined } from "@ant-design/icons";
import { Alert, Button, Select, Segmented, Space } from "antd";
import { useEffect, useMemo } from "react";
import { buildDashModel, EMPTY_MODEL } from "../../lib/dashboardModel";
import { useCrawlStore } from "../../store/useCrawlStore";
import { useDashboardStore } from "../../store/useDashboardStore";
import { FocusGraphStage } from "../graph/FocusGraphStage";
import { NodeInspector } from "../inspector/NodeInspector";
import { KpiMetricStrip } from "../metrics/KpiMetricStrip";
import { LevelFilterRow } from "../tree/LevelFilterRow";
import { TeleportSearch } from "../tree/TeleportSearch";
import { VirtualizedTree } from "../tree/VirtualizedTree";
import { CrawlReport } from "../report/CrawlReport";
import { LiveCrawlProgressModal } from "../telemetry/LiveCrawlProgressModal";
import { LiveCrawlModal } from "./LiveCrawlModal";
import { NavigationRail } from "./NavigationRail";
import { useState } from "react";

/**
 * The dashboard shell.
 *
 * The safety banners are kept from the previous layout rather than dropped in
 * the port. Truncation, synthetic data, a zero-fetch crawl and a blocked crawl
 * are each a way to read this screen confidently and wrongly, and each one cost
 * a cycle to make visible (build-logs 0012 and 0013). A redesign is not a reason
 * to stop saying them.
 */
export function DashboardShell(): JSX.Element {
  const result = useCrawlStore((state) => state.result);
  const jobs = useCrawlStore((state) => state.jobs);
  const activeJobId = useCrawlStore((state) => state.activeJobId);
  const selectJob = useCrawlStore((state) => state.selectJob);
  const grouping = useCrawlStore((state) => state.grouping);
  const setGrouping = useCrawlStore((state) => state.setGrouping);
  const adapter = useCrawlStore((state) => state.adapter);
  const status = useCrawlStore((state) => state.status);
  const error = useCrawlStore((state) => state.error);
  const liveMessage = useCrawlStore((state) => state.liveMessage);

  const loadCheckpoint = useCrawlStore((state) => state.loadCheckpoint);
  const setModel = useDashboardStore((state) => state.setModel);
  const expandAll = useDashboardStore((state) => state.expandAll);
  const collapseAll = useDashboardStore((state) => state.collapseAll);
  const [crawlOpen, setCrawlOpen] = useState(false);
  const [printedAt, setPrintedAt] = useState<Date | null>(null);

  // Rebuilt only when the crawl or the grouping changes. At 20,000 pages this
  // walk is the single most expensive thing the UI does.
  const model = useMemo(
    () => (result ? buildDashModel(result, grouping) : EMPTY_MODEL),
    [result, grouping],
  );

  useEffect(() => {
    if (model.nodes.length > 0) setModel(model);
  }, [model, setModel]);

  const active = jobs.find((job) => job.id === activeJobId);
  const discovery = result?.discovery;
  const navParsed = (result?.navigation.roots.length ?? 0) > 0;

  return (
    <div className="rk-dash">
      <NavigationRail />

      <div className="rk-app">
        <header className="hdr">
          <h1>
            Rankuno Engine{" "}
            <span>— {result ? result.base_url : "no crawl loaded"}</span>
          </h1>

          <Space size={8}>
            <Select
              size="small"
              style={{ minWidth: 240 }}
              value={activeJobId ?? undefined}
              onChange={selectJob}
              placeholder="Select a crawl"
              options={jobs.map((job) => ({ value: job.id, label: job.label }))}
            />
            {adapter?.startJob !== undefined && (
              <Button
                size="small"
                type="primary"
                loading={status === "running" || status === "queued"}
                onClick={() => setCrawlOpen(true)}
              >
                New crawl
              </Button>
            )}
            {result && (
              <Button
                size="small"
                icon={<FilePdfOutlined />}
                onClick={() => {
                  // Stamped before printing so the report carries the moment it
                  // was produced, not the moment it is read.
                  setPrintedAt(new Date());
                  // One frame, so React has committed the report before the
                  // browser snapshots the page for printing.
                  requestAnimationFrame(() => window.print());
                }}
              >
                PDF
              </Button>
            )}
            <Segmented
              size="small"
              value={grouping}
              onChange={(value) => setGrouping(value as "navigation" | "path")}
              options={[
                { label: "Navigation", value: "navigation", disabled: !navParsed },
                { label: "URL path", value: "path" },
              ]}
            />
          </Space>

          <div className={`perf${discovery?.truncated ? " stale" : ""}`}>
            {liveMessage ??
              (result
                ? `${model.nodes.length.toLocaleString()} nodes · virtual list`
                : status.toUpperCase())}
          </div>
        </header>

        {error && (
          <Alert
            type="error"
            banner
            showIcon
            message={error}
            /* A failed job with saved work is not a dead end. Offering the
               recovery here, next to the reason, is the only place the user is
               already looking when they need it. */
            action={
              active?.recoverable ? (
                <Button
                  size="small"
                  type="primary"
                  onClick={() => void loadCheckpoint(active.id)}
                >
                  Render partial tree
                </Button>
              ) : undefined
            }
          />
        )}

        {active?.synthetic && (
          <Alert
            type="warning"
            banner
            showIcon
            message="Synthetic dataset — generated for performance testing. Not crawl output, and not evidence about the engine."
          />
        )}

        {discovery && discovery.pages_fetched === 0 && (
          <Alert
            type="error"
            banner
            showIcon
            message={
              discovery.fetch_failures > 0
                ? `0 pages fetched — ${discovery.fetch_failures} requests were refused. Classifications rest on URL string patterns alone.`
                : "0 pages fetched over the network. Classifications rest on URL string patterns alone."
            }
          />
        )}

        {/* Distinct from truncation. Truncated means the crawl stopped at a
            ceiling it was told about; this means it was abandoned, and there is
            no way to know how much of the site is missing. */}
        {discovery?.stopped_reason && (
          <Alert
            type="warning"
            banner
            showIcon
            message={`Crawl stopped early — ${discovery.stopped_reason}. Showing the ${discovery.total_urls.toLocaleString()} URLs found before it stopped; this is not the whole site, and how much is missing is unknown.`}
          />
        )}

        {discovery?.truncated && (
          <Alert
            type="warning"
            banner
            showIcon
            message="Crawl stopped at its page ceiling. This is a partial view of the site, not the whole of it."
          />
        )}

        {grouping === "navigation" && !navParsed && result && (
          <Alert
            type="info"
            banner
            showIcon
            message="No header menu could be parsed, so lanes show URL-path depth rather than navigation depth."
          />
        )}

        <div className="rk-body">
          {result ? (
            <>
              <KpiMetricStrip result={result} />

              <div className="split">
                <section className="card">
                  <div className="ch">
                    <h2>DirectoryTree</h2>
                    <span>virtual · ~25 rows in DOM</span>
                  </div>
                  <TeleportSearch model={model} />
                  <LevelFilterRow model={model} />
                  <Space size={4} style={{ padding: "0 10px 8px" }}>
                    <Button size="small" onClick={() => expandAll(model, 1)}>
                      L1
                    </Button>
                    <Button size="small" onClick={() => expandAll(model, 2)}>
                      L2
                    </Button>
                    <Button size="small" onClick={() => expandAll(model, 99)}>
                      All
                    </Button>
                    <Button size="small" onClick={() => collapseAll(model)}>
                      Collapse
                    </Button>
                  </Space>
                  <VirtualizedTree model={model} />
                </section>

                <section className="card graphwrap">
                  <div className="ch">
                    <h2>Visual Hierarchy Mapping — Focus Mode</h2>
                    <span>selected neighbourhood only · click to walk the tree</span>
                  </div>
                  <FocusGraphStage model={model} />
                  <NodeInspector model={model} />
                </section>
              </div>
            </>
          ) : (
            <div className="rk-empty">
              {status === "failed"
                ? "This crawl failed and produced no result. Select a previous successful crawl above."
                : "No crawl loaded. Select one above, or start a new crawl."}
            </div>
          )}
        </div>
      </div>

      <LiveCrawlModal open={crawlOpen} onClose={() => setCrawlOpen(false)} />
      <LiveCrawlProgressModal />

      {/* Always mounted, revealed only by `@media print`. The on-screen tree is
          virtualized, so printing the page would capture the ~25 rows that
          happen to be in the DOM. */}
      {result && model.nodes.length > 0 && (
        <CrawlReport
          model={model}
          result={result}
          generatedAt={printedAt ?? new Date()}
        />
      )}
    </div>
  );
}
