import { Button, Empty, Progress, Table, Tag, Tooltip } from "antd";
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
  const setView = useUiStore((state) => state.setView);

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
      width: 132,
      render: (_value, row) => (
        <ActionCell row={row} onOpen={() => openTree(row)} />
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

/** View / recover buttons for one row. */
function ActionCell({ row, onOpen }: { row: JobRow; onOpen: () => void }): JSX.Element {
  if (row.recoverable) {
    return (
      <Tooltip title="This crawl failed, but the URLs it found were checkpointed. The tree is real; the classifications in it are placeholders.">
        <Button size="small" onClick={onOpen}>
          Partial tree
        </Button>
      </Tooltip>
    );
  }

  const ready = row.status === "succeeded" || row.status === "partial";
  return (
    <Button size="small" type={ready ? "primary" : "default"} disabled={!ready} onClick={onOpen}>
      View tree
    </Button>
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
