import { Alert, Button, Space } from "antd";
import { useEffect, useMemo } from "react";
import { buildDashModel, EMPTY_MODEL } from "../../lib/dashboardModel";
import { ErrorBoundary } from "../ErrorBoundary";
import { useCrawlStore } from "../../store/useCrawlStore";
import { useDashboardStore } from "../../store/useDashboardStore";
import { FocusGraphStage } from "../graph/FocusGraphStage";
import { NodeInspector } from "../inspector/NodeInspector";
import { KpiMetricStrip } from "../metrics/KpiMetricStrip";
import { LevelFilterRow } from "../tree/LevelFilterRow";
import { TeleportSearch } from "../tree/TeleportSearch";
import { VirtualizedTree } from "../tree/VirtualizedTree";
import { CrawlReport } from "../report/CrawlReport";
import { AuditView } from "../audit/AuditView";
import { CrawlJobsView } from "../jobs/CrawlJobsView";
import { CrawlNotifier } from "../jobs/CrawlNotifier";
import { HeaderBar } from "./HeaderBar";
import { LiveCrawlModal } from "./LiveCrawlModal";
import { NavigationRail } from "./NavigationRail";
import { useUiStore } from "../../store/useUiStore";
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
  const grouping = useCrawlStore((state) => state.grouping);
  const status = useCrawlStore((state) => state.status);
  const error = useCrawlStore((state) => state.error);
  const view = useUiStore((state) => state.view);

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
  const navParsed = (result?.navigation?.roots.length ?? 0) > 0;

  return (
    // The report is a *sibling* of `.rk-dash`, not a child. Printing hides
    // `.rk-dash` outright, and a hidden ancestor hides everything under it —
    // nested, the report printed as a blank page.
    <>
      <div className="rk-dash">
        <NavigationRail />

        <div className="rk-app">
          <HeaderBar
            nodeCount={model.nodes.length}
            navParsed={navParsed}
            onNewCrawl={() => setCrawlOpen(true)}
            onPrint={() => {
              // Stamped before printing so the report carries the moment it was
              // produced, not the moment it is read.
              setPrintedAt(new Date());
              // One frame, so React has committed the report before the browser
              // snapshots the page for printing.
              requestAnimationFrame(() => window.print());
            }}
          />

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

          {/* Everything below describes the *loaded result*, so it belongs to
              the visualizer. The error banner above stays on both, because a
              rejected submission has no job row to be reported against. */}
          {view === "jobs" && <CrawlJobsView />}
          {/* Boundaried for the reason stated on the boundary itself: a view
              that reads a field an older stored result does not carry throws
              during render, and an unboundaried throw blanks the whole
              dashboard rather than the one panel at fault. */}
          {view === "audit" && (
            <ErrorBoundary label="The audit">
              <AuditView />
            </ErrorBoundary>
          )}

          {view === "visualizer" && active?.synthetic && (
            <Alert
              type="warning"
              banner
              showIcon
              message="Synthetic dataset — generated for performance testing. Not crawl output, and not evidence about the engine."
            />
          )}

          {view === "visualizer" && discovery && discovery.pages_fetched === 0 && (
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
          {view === "visualizer" && discovery?.stopped_reason && (
            <Alert
              type="warning"
              banner
              showIcon
              message={`Crawl stopped early — ${discovery.stopped_reason}. Showing the ${discovery.total_urls.toLocaleString()} URLs found before it stopped; this is not the whole site, and how much is missing is unknown.`}
            />
          )}

          {view === "visualizer" && discovery?.truncated && (
            <Alert
              type="warning"
              banner
              showIcon
              message="Crawl stopped at its page ceiling. This is a partial view of the site, not the whole of it."
            />
          )}

          {/* Not gated on `grouping === "navigation"`. `selectJob` switches the
              grouping to "path" the moment it sees an unparsed menu, so that
              condition was false exactly when this needed to be said — the
              banner could never fire. It is the fallback itself that has to be
              announced, not the toggle position. */}
          {view === "visualizer" && result && !navParsed && (
            <Alert
              type="warning"
              banner
              showIcon
              message={
                discovery?.pages_fetched === 0
                  ? "No header menu was parsed because no page was fetched. The tree below groups by URL path, and its lane numbers are path depth — not navigation depth. Each row's badge shows the level the engine classified, which is the reliable figure."
                  : "No header menu could be parsed, so the tree groups by URL path. Lane numbers are path depth, not navigation depth. Each row's badge shows the level the engine classified."
              }
            />
          )}

          {view === "visualizer" && (
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
                    {/* `All` and `Collapse` were the labels here and read as
                        filters beside the L1/L2 depth buttons rather than as the
                        whole-tree commands they are. Named for what they do. */}
                    <Space size={4} style={{ padding: "0 10px 8px" }}>
                      <Button
                        size="small"
                        title="Open the first level only"
                        onClick={() => expandAll(model, 1)}
                      >
                        L1
                      </Button>
                      <Button
                        size="small"
                        title="Open the first two levels"
                        onClick={() => expandAll(model, 2)}
                      >
                        L2
                      </Button>
                      <Button
                        size="small"
                        title={`Open every section, to the bottom — ${model.nodes.length.toLocaleString()} nodes`}
                        onClick={() => expandAll(model, 99)}
                      >
                        Expand all
                      </Button>
                      <Button
                        size="small"
                        title="Close every section back to the top level"
                        onClick={() => collapseAll(model)}
                      >
                        Collapse all
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
          )}
        </div>

        <LiveCrawlModal open={crawlOpen} onClose={() => setCrawlOpen(false)} />
        {/* Renders nothing. Announces background crawls as they finish, from
            above the view switch so a crawl that ends while the operator is on
            the jobs tab is still offered. */}
        <CrawlNotifier />
      </div>

      {/* Always mounted, revealed only by `@media print`. The on-screen tree is
          virtualized, so printing the page would capture the ~25 rows that
          happen to be in the DOM. */}
      {result && model.nodes.length > 0 && (
        <ErrorBoundary label="The printable report">
          <CrawlReport
            model={model}
            result={result}
            generatedAt={printedAt ?? new Date()}
          />
        </ErrorBoundary>
      )}
    </>
  );
}
