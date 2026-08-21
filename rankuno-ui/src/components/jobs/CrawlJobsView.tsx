import { Button, Dropdown, Empty, Popconfirm, Progress, Table, Tag, Tooltip } from "antd";
import type { MenuProps } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useEffect, useState } from "react";
import type { CrawlJobSummary, JobStatus } from "../../adapters/adapterInterface";
import {
  elapsedSeconds,
  fetchedPercent,
  formatClock,
  formatRemaining,
} from "../../lib/duration";
import { formatCrawlTime } from "../../lib/time";
import type { LiveJob } from "../../store/useCrawlStore";
import { isLive, useCrawlStore } from "../../store/useCrawlStore";
import { useUiStore } from "../../store/useUiStore";
import { PerformancePanel } from "./PerformancePanel";
import { ReconcilePanel } from "./ReconcilePanel";
import { UrlTicker } from "../telemetry/UrlTicker";
import "./jobs.css";

/** One table row: the server's record, plus live telemetry when we have it. */
interface JobRow {
  key: string;
  id: string;
  label: string;
  status: JobStatus;
  live: LiveJob | null;
  summary: CrawlJobSummary | null;
  crawledAt: string | null;
  recoverable: boolean;
  hasCheckpoint: boolean;
  synthetic: boolean;
}

const STATUS_COLOUR: Record<JobStatus, string> = {
  idle: "default",
  queued: "gold",
  running: "processing",
  succeeded: "success",
  partial: "warning",
  failed: "error",
};

/**
 * Every crawl, running and finished, in one table.
 *
 * Two sources are merged here rather than in the store. `jobs` is what the
 * server knows — every job that ever ran, surviving a browser reload. `liveJobs`
 * is what this session is watching, and holds the only copy of the telemetry:
 * the job list endpoint returns metadata, not progress. A crawl started in
 * another tab therefore appears with a status and no progress bar, which is
 * honest — this page cannot know its rate, and inventing one would be worse
 * than an empty column.
 */
export function CrawlJobsView(): JSX.Element {
  const jobs = useCrawlStore((state) => state.jobs);
  const liveJobs = useCrawlStore((state) => state.liveJobs);
  const activeJobId = useCrawlStore((state) => state.activeJobId);
  const selectJob = useCrawlStore((state) => state.selectJob);
  const loadCheckpoint = useCrawlStore((state) => state.loadCheckpoint);
  const refreshJobs = useCrawlStore((state) => state.refreshJobs);
  const relaunch = useCrawlStore((state) => state.relaunch);
  const cancel = useCrawlStore((state) => state.cancel);
  // Fixtures cannot crawl, so the buttons are hidden rather than offered and
  // then failing on click.
  const canRelaunch = useCrawlStore((state) => state.adapter?.startJob !== undefined);
  const setView = useUiStore((state) => state.setView);
  // Hidden entirely when the adapter cannot reconcile — fixtures cannot — so
  // the control is absent rather than present and failing on click.
  const canReconcile = useCrawlStore(
    (state) => state.adapter?.reconcileScreamingFrog !== undefined,
  );
  // Same reasoning as `canReconcile`: fixtures have no Search Console data.
  const canIngestGsc = useCrawlStore(
    (state) => state.adapter?.uploadGscExport !== undefined,
  );
  const [reconciling, setReconciling] = useState<JobRow | null>(null);
  const [performing, setPerforming] = useState<JobRow | null>(null);

  // Drives the elapsed clocks only. The crawl's own numbers arrive on the
  // adapter's poll; this is a second-hand, and it stops when nothing is running
  // so an idle jobs tab does no work at all.
  const anyLive = Object.values(liveJobs).some(isLive);
  const now = useTicker(anyLive);

  const rows = buildRows(jobs, liveJobs);

  function openTree(row: JobRow): void {
    void (async () => {
      if (row.recoverable) await loadCheckpoint(row.id);
      else await selectJob(row.id);
      setView("visualizer");
    })();
  }

  const columns: ColumnsType<JobRow> = [
    {
      title: "Target",
      dataIndex: "label",
      key: "label",
      render: (_value, row) => (
        <div className="jb-target">
          <span className="jb-url">{row.label}</span>
          <span className="jb-meta">
            {row.id === activeJobId && <Tag className="jb-viewing">viewing</Tag>}
            {row.synthetic && <Tag color="purple">synthetic</Tag>}
            <span className="jb-when">{formatCrawlTime(row.crawledAt)}</span>
          </span>
        </div>
      ),
    },
    {
      title: "Status",
      key: "status",
      width: 130,
      render: (_value, row) => (
        <div className="jb-status">
          <Tag color={STATUS_COLOUR[row.status]}>{row.status.toUpperCase()}</Tag>
          {row.live && (
            <span className="jb-clock">
              {formatClock(elapsedSeconds(row.live.startedAt, row.live.endedAt, now))}
            </span>
          )}
        </div>
      ),
    },
    {
      title: "Progress",
      key: "progress",
      width: 300,
      render: (_value, row) => <ProgressCell row={row} />,
    },
    {
      title: "",
      key: "actions",
      width: 150,
      render: (_value, row) => (
        <ActionCell
          row={row}
          onOpen={() => openTree(row)}
          onRelaunch={(mode) => void relaunch(row.id, mode, `${row.label} (${mode})`)}
          onCancel={() => void cancel(row.id)}
          onReconcile={() => setReconciling(row)}
          onPerformance={() => setPerforming(row)}
          canRelaunch={canRelaunch}
          canReconcile={canReconcile}
          canIngestGsc={canIngestGsc}
        />
      ),
    },
  ];

  return (
    <div className="jb-wrap">
      <div className="jb-head">
        <h2>Crawl jobs</h2>
        <span className="jb-sub">
          Crawls run in the background. Leaving this tab does not stop them.
        </span>
        <Button size="small" onClick={() => void refreshJobs()}>
          Refresh
        </Button>
      </div>

      <Table<JobRow>
        className="jb-table"
        columns={columns}
        dataSource={rows}
        size="small"
        pagination={false}
        locale={{
          emptyText: <Empty description="No crawls yet. Start one from the header." />,
        }}
        expandable={{
          // Only a job with a live stream has anything to expand into. A row
          // with an expander that opens onto nothing is worse than no expander.
          rowExpandable: (row) => (row.live?.telemetry?.recent_items.length ?? 0) > 0,
          expandedRowRender: (row) => <StreamPanel row={row} />,
        }}
      />

      {reconciling && (
        <ReconcilePanel
          jobId={reconciling.id}
          label={reconciling.label}
          open
          onClose={() => setReconciling(null)}
        />
      )}

      {performing && (
        <PerformancePanel
          jobId={performing.id}
          label={performing.label}
          open
          onClose={() => setPerforming(null)}
        />
      )}
    </div>
  );
}

/** Progress bar, counts and ETA for one row. */
function ProgressCell({ row }: { row: JobRow }): JSX.Element {
  const telemetry = row.live?.telemetry ?? null;

  if (!row.live) {
    // Finished before this session, or started elsewhere. The server keeps no
    // progress history, so there is nothing truthful to draw.
    return <span className="jb-dim">—</span>;
  }

  const completed = telemetry?.completed ?? 0;
  const discovered = telemetry?.discovered ?? 0;
  const percent = fetchedPercent(completed, discovered);
  const done = !isLive(row.live);

  return (
    <div className="jb-progress">
      <Progress
        percent={done ? 100 : percent}
        size="small"
        status={row.status === "failed" ? "exception" : done ? "normal" : "active"}
        strokeColor={done ? undefined : { "0%": "#00f2fe", "100%": "#4facfe" }}
        showInfo={false}
      />
      <div className="jb-numbers">
        <Tooltip title="Pages fetched against URLs discovered. Sitemap URLs count toward the total but are never fetched, so a sitemap-heavy crawl completes below 100%.">
          <span className="jb-count">
            {discovered > 0
              ? `${completed.toLocaleString()} / ${discovered.toLocaleString()}`
              : "discovering…"}
          </span>
        </Tooltip>
        <span className="jb-eta">{describeEta(row.live)}</span>
      </div>
    </div>
  );
}

/** The ETA phrase, or an honest statement of why there is not one yet. */
function describeEta(live: LiveJob): string {
  if (!isLive(live)) return live.error ?? "done";
  const telemetry = live.telemetry;
  // The engine withholds an ETA until a rate means something. "0 sec remaining"
  // during that window would be worse than saying the estimate is not ready.
  if (telemetry?.eta_seconds != null) return `~${formatRemaining(telemetry.eta_seconds)} left`;
  if ((telemetry?.discovered ?? 0) > 0) return "estimating…";
  return "discovering URLs…";
}

/** View, recover, retry, resume and cancel buttons for one row. */
function ActionCell({
  row,
  onOpen,
  onRelaunch,
  onCancel,
  onReconcile,
  onPerformance,
  canRelaunch,
  canReconcile,
  canIngestGsc,
}: {
  row: JobRow;
  onOpen: () => void;
  onRelaunch: (mode: "retry" | "resume") => void;
  onCancel: () => void;
  onReconcile: () => void;
  onPerformance: () => void;
  canRelaunch: boolean;
  canReconcile: boolean;
  canIngestGsc: boolean;
}): JSX.Element {
  const ready = row.status === "succeeded" || row.status === "partial";
  const finished = ready || row.status === "failed";

  // Deliberately NOT `discovered > fetched`. Every healthy crawl satisfies
  // that — a sitemap lists pages no link reaches, and faceted filters are
  // declined on purpose — so keying off it would put a "resume" button
  // promising work on every completed crawl. A crawl that genuinely stopped
  // early is one that failed or hit its ceiling, and left a checkpoint.
  const stoppedEarly = row.hasCheckpoint && (row.status === "failed" || row.status === "partial");
  const running = row.status === "running" || row.status === "queued";

  /*
   * Everything that is not the main action, behind one menu.
   *
   * Five buttons were rendered side by side and wrapped onto a second line at
   * the column's width, which made a table of crawls read as a wall of controls
   * and buried the one an analyst actually wants. These four are each optional
   * or occasional; `View tree` is the one taken almost every time, so it stays
   * out here and the rest move behind `⋯`.
   *
   * Each item carries its own one-line explanation rather than a hover tooltip.
   * A tooltip inside an already-open menu is a second hover on top of a first,
   * and the explanations are the part an analyst new to the tool needs most.
   */
  const extras: MenuProps["items"] = [];

  if (canIngestGsc && ready) {
    extras.push({
      key: "gsc",
      label: (
        <span className="jb-menuitem">
          Search Console
          <em>Add clicks and impressions. The crawl is not changed.</em>
        </span>
      ),
      onClick: onPerformance,
    });
  }

  if (canReconcile && ready) {
    extras.push({
      key: "frog",
      label: (
        <span className="jb-menuitem">
          Cross-check
          <em>Compare against a Screaming Frog export.</em>
        </span>
      ),
      onClick: onReconcile,
    });
  }

  if (canRelaunch && stoppedEarly) {
    extras.push({
      key: "resume",
      label: (
        <span className="jb-menuitem">
          Resume
          <em>Crawl the URLs this run never fetched, as a separate job.</em>
        </span>
      ),
      onClick: () => onRelaunch("resume"),
    });
  }

  if (canRelaunch && finished) {
    extras.push({
      key: "retry",
      label: (
        <span className="jb-menuitem">
          Run again
          <em>Re-crawl from scratch with the same settings. This job is kept.</em>
        </span>
      ),
      onClick: () => onRelaunch("retry"),
    });
  }

  return (
    <div className="jb-actions">
      {row.recoverable ? (
        <Tooltip title="This crawl failed, but the URLs it found were checkpointed. The tree is real; the classifications in it are placeholders.">
          <Button size="small" onClick={onOpen}>
            Partial tree
          </Button>
        </Tooltip>
      ) : (
        <Button size="small" type={ready ? "primary" : "default"} disabled={!ready} onClick={onOpen}>
          View tree
        </Button>
      )}

      {extras.length > 0 && (
        <Dropdown menu={{ items: extras }} trigger={["click"]} placement="bottomRight">
          <Button size="small" aria-label="More actions for this crawl">
            ⋯
          </Button>
        </Dropdown>
      )}

      {/* Destructive, and deliberately not in the menu: a kill needs to be
          visible and deliberate, not two clicks deep beside four routine
          actions. Shown only while the job still holds a slot — the tooltip
          states the limit plainly, because a worker thread cannot be
          interrupted from outside, so this reclaims capacity rather than
          stopping traffic. */}
      {canRelaunch && running && (
        <Tooltip title="Give this crawl's slot back so other crawls can start. The crawl itself keeps running on the server until it finishes or the server restarts — its result is discarded.">
          <Popconfirm
            title="Abandon this crawl?"
            description="Its slot is freed immediately. The crawl keeps running server-side and its result is thrown away."
            okText="Abandon"
            cancelText="Keep"
            onConfirm={onCancel}
          >
            <Button size="small" type="text" danger>
              Kill
            </Button>
          </Popconfirm>
        </Tooltip>
      )}
    </div>
  );
}

/** Expanded row: the live URL stream for a running crawl. */
function StreamPanel({ row }: { row: JobRow }): JSX.Element {
  const telemetry = row.live?.telemetry;
  const items = telemetry?.recent_items ?? [];
  return (
    <div className="jb-stream">
      <UrlTicker urls={items} compact />
      <span className="jb-dim">
        {/* Stated because the ticker looks like a complete log and is not. */}
        Last {items.length} of {(telemetry?.completed ?? 0).toLocaleString()} fetched — the
        stream is capped so polling stays cheap on large crawls.
        {telemetry && telemetry.rate_per_sec > 0
          ? ` ${telemetry.rate_per_sec.toFixed(1)} pages/sec.`
          : ""}
      </span>
    </div>
  );
}

/**
 * Merge the server's job list with this session's live telemetry.
 *
 * Server order is preserved — it returns newest first — except that anything
 * still running is lifted to the top, which is what the operator opened this
 * tab to see.
 */
function buildRows(
  jobs: readonly CrawlJobSummary[],
  liveJobs: Readonly<Record<string, LiveJob>>,
): JobRow[] {
  const rows: JobRow[] = jobs.map((job) => {
    const live = liveJobs[job.id] ?? null;
    return {
      key: job.id,
      id: job.id,
      label: job.label || job.baseUrl || job.id,
      // The live poll is ahead of the cached list between refreshes, so it wins.
      status: live?.status ?? job.status,
      live,
      summary: job,
      crawledAt: job.crawledAt,
      recoverable: job.recoverable === true,
      hasCheckpoint: job.hasCheckpoint === true,
      synthetic: job.synthetic,
    };
  });

  // A crawl submitted seconds ago is in `liveJobs` before the next `listJobs`
  // returns it. Without this it would vanish from the table for one poll —
  // exactly when the operator is watching for it to appear.
  const known = new Set(rows.map((row) => row.id));
  for (const live of Object.values(liveJobs)) {
    if (known.has(live.id)) continue;
    rows.unshift({
      key: live.id,
      id: live.id,
      label: live.label,
      status: live.status,
      live,
      summary: null,
      crawledAt: new Date(live.startedAt).toISOString(),
      recoverable: false,
      hasCheckpoint: false,
      synthetic: false,
    });
  }

  return rows.sort((a, b) => rank(a) - rank(b));
}

/** Running first, then everything else in the order the server gave. */
function rank(row: JobRow): number {
  return row.live && isLive(row.live) ? 0 : 1;
}

/**
 * A once-per-second clock, running only while it is needed.
 *
 * Returns a timestamp rather than an interval id so the elapsed columns are a
 * pure function of it. Stopped entirely when nothing is live: a jobs tab left
 * open on a finished list should not wake the tab once a second forever.
 */
function useTicker(enabled: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!enabled) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [enabled]);
  return now;
}
