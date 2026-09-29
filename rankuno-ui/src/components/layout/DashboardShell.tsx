import { Alert, Button, Spin } from "antd";
import { useEffect, useMemo } from "react";
import { buildDashModel, EMPTY_MODEL } from "../../lib/dashboardModel";
import { dashboardNotices } from "../../lib/dashboardNotices";
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
import { GscAccountsView } from "../gsc/GscAccountsView";
import { LaunchView } from "../screaming-frog/LaunchView";
import { ScreamingFrogView } from "../screaming-frog/ScreamingFrogView";
import { HeaderBar } from "./HeaderBar";
import { LiveCrawlModal } from "./LiveCrawlModal";
import { NavigationRail } from "./NavigationRail";
import { NoticeStack } from "./NoticeStack";
import { useAuthStore } from "../../store/useAuthStore";
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
 *
 * They are now dismissible, which is not a retraction of that. A dismissal is
 * recorded against one crawl and one banner, `NoticeStack` keeps a count of
 * what is hidden on screen with a control that restores it, and a different
 * crawl starts with everything showing. The finding is put away, never lost.
 *
 * The error banner below is the exception and stays permanent. It is the only
 * banner that carries an *action* — "Render partial tree" is the recovery path
 * for a failed job with a checkpoint on disk — and a recovery button behind a
 * close button is worse than the clutter it saves. It is also the one banner
 * with nothing to scope a dismissal to: it fires for a rejected submission,
 * which has no job row and therefore no crawl id, so the only dismissal
 * available for it would be the global one this design forbids. It is already
 * transient in a way the others are not — the store clears `error` on the next
 * action — so it goes away by itself as soon as anything happens.
 */
export function DashboardShell(): JSX.Element {
  const result = useCrawlStore((state) => state.result);
  const jobs = useCrawlStore((state) => state.jobs);
  const activeJobId = useCrawlStore((state) => state.activeJobId);
  const grouping = useCrawlStore((state) => state.grouping);
  const reconciliation = useCrawlStore((state) => state.reconciliation);
  const includeDefaulters = useCrawlStore((state) => state.includeDefaulters);
  const status = useCrawlStore((state) => state.status);
  const error = useCrawlStore((state) => state.error);
  const view = useUiStore((state) => state.view);
  const enterMode = useUiStore((state) => state.enterMode);
  // Fixture mode implements neither. Both launch cards say so rather than
  // hiding, so "the engine is not running" is readable from the first screen.
  const canStartEngineCrawl = useCrawlStore((state) => state.adapter?.startJob !== undefined);
  const canDispatchScreamingFrog = useCrawlStore(
    (state) => state.adapter?.previewDispatch !== undefined,
  );
  // `null` only in offline/fixture mode, which never logged in — `GscAccountsView`
  // itself falls back to `"default"` for that case, the same org its own
  // component-local prop default already named before this store existed.
  const authOrgId = useAuthStore((state) => state.orgId);

  const loadCheckpoint = useCrawlStore((state) => state.loadCheckpoint);
  const setModel = useDashboardStore((state) => state.setModel);
  const [crawlOpen, setCrawlOpen] = useState(false);
  const [printedAt, setPrintedAt] = useState<Date | null>(null);

  // Rebuilt only when the crawl, the grouping, the loaded cross-check or the
  // defaulter toggle changes. At 20,000 pages this walk is the single most
  // expensive thing the UI does.
  const model = useMemo(
    () =>
      result ? buildDashModel(result, grouping, reconciliation, includeDefaulters) : EMPTY_MODEL,
    [result, grouping, reconciliation, includeDefaulters],
  );

  useEffect(() => {
    if (model.nodes.length > 0) setModel(model);
  }, [model, setModel]);

  const active = jobs.find((job) => job.id === activeJobId);
  const navParsed = (result?.navigation?.roots.length ?? 0) > 0;

  // Every banner that applies to the loaded crawl. Rebuilt only when the result
  // or the job's synthetic flag changes, so a dismissal — which lives in its
  // own store — does not re-derive the list it is filtering.
  const notices = useMemo(
    () => dashboardNotices(result, active?.synthetic ?? false),
    [result, active?.synthetic],
  );

  return (
    // The report is a *sibling* of `.rk-dash`, not a child. Printing hides
    // `.rk-dash` outright, and a hidden ancestor hides everything under it —
    // nested, the report printed as a blank page.
    <>
      <div className="rk-dash">
        <NavigationRail />

        <div className="rk-app">
          <HeaderBar
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

          {/* The opening screen. Boundaried like the others: it reads the
              adapter's capabilities, and a shell that blanks entirely would
              leave no way back to any other view. */}
          {view === "launch" && (
            <ErrorBoundary label="The launch screen">
              {/* Each card enters its product, landing on the engine view last
                  open, so the crawl form closes onto the engine rather than
                  back onto Launch. `onOpenEngine` is the same landing without
                  `setCrawlOpen` — entering the engine and starting a crawl are
                  two different intentions, and the rail no longer offers the
                  first from this screen. */}
              <LaunchView
                onEngineCrawl={() => {
                  enterMode("engine");
                  setCrawlOpen(true);
                }}
                onOpenEngine={() => enterMode("engine")}
                onScreamingFrog={() => enterMode("screaming-frog")}
                canStartEngineCrawl={canStartEngineCrawl}
                canDispatchScreamingFrog={canDispatchScreamingFrog}
              />
            </ErrorBoundary>
          )}
          {/* A different job system from `CrawlJobsView` below — its own view
              rather than a tab inside that one, so the two are never read as
              rows of the same table. */}
          {view === "screaming-frog" && (
            <ErrorBoundary label="The Screaming Frog launcher">
              <ScreamingFrogView />
            </ErrorBoundary>
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
          {view === "gsc-accounts" && (
            <ErrorBoundary label="GSC Accounts">
              <GscAccountsView orgId={authOrgId ?? undefined} />
            </ErrorBoundary>
          )}

          {/* Seven banners that describe the loaded result, each dismissible
              against this crawl alone. The wording and the firing conditions
              moved to `dashboardNotices` unchanged — a stack of conditional
              JSX cannot be counted, and "2 hidden notices" needs to know how
              many banners apply, not how many are on screen. */}
          {view === "visualizer" && (
            <NoticeStack notices={notices} crawlId={activeJobId} />
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
                    {/* The depth commands moved into `TreeControls`, which sits
                        inside the tree itself and renders in the full-screen
                        view too — that view had no way to collapse anything.
                        Kept in one place rather than copied, so the two cannot
                        drift. */}
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
            ) : status === "queued" || status === "running" ? (
              /* A fetch is in flight — the job list on boot, a crawl restored
                 from the last session, or a job just picked. Saying "No crawl
                 loaded" while one is on its way is both wrong and the exact
                 thing a restore was added to stop showing. Announced politely
                 rather than drawn only as a spinner, so the wait is readable
                 without sight of it. */
              <div className="rk-empty" role="status" aria-live="polite">
                <Spin size="small" /> <span>Loading the crawl…</span>
              </div>
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
