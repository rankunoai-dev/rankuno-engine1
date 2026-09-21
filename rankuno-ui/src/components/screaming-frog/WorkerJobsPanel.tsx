import { Alert, Button, Empty, Table, Tag, message } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useCallback, useEffect, useState } from "react";
import type {
  WorkerDispatchAdapter,
  WorkerJobView,
} from "../../adapters/adapterInterface";
import { formatBytes, saveBlob } from "../../lib/download";
import { formatClock } from "../../lib/duration";
import { formatCrawlTime } from "../../lib/time";
import "./screaming-frog.css";

interface Props {
  /**
   * The adapter itself, not two bound methods.
   *
   * `adapter.listWorkerJobs.bind(adapter)` returns a new function on every
   * render, which as a hook dependency means a refetch on every render —
   * forever, since each fetch renders again. The object identity is stable.
   */
  api: WorkerDispatchAdapter | null;
  /** Bumped by a successful dispatch, to refetch without waiting for the poll. */
  refreshSignal: number;
  /** Put a finished job's settings back in the form. Never auto-runs anything. */
  onReuse: (job: WorkerJobView) => void;
  /** Machine display names by worker id, for rows naming a machine. */
  workerNames: Readonly<Record<string, string>>;
}

/** Statuses that can still change, so the list is worth polling. */
const ACTIVE: ReadonlySet<string> = new Set(["queued", "dispatched"]);

/** How often to refetch while anything is still moving. */
const POLL_MS = 5_000;

const STATUS_COLOUR: Readonly<Record<string, string>> = {
  queued: "gold",
  dispatched: "processing",
  succeeded: "success",
  partial: "warning",
  failed: "error",
};

/**
 * Every Screaming Frog dispatch for this org.
 *
 * Deliberately a *separate* table from `CrawlJobsView`. These rows come from
 * `/workers/jobs`, carry `WorkerJobStatus` values that only look like the
 * engine's, and their ids address a different store — an id from here passed to
 * a `/jobs` route is a 404. Merging the two would save a table and cost the
 * only visible evidence that they are different systems.
 *
 * There is no progress column and there will not be one. The supervisor knows
 * whether the Screaming Frog process is alive, and nothing else: a three-hour
 * crawl reports "running" for three hours. Elapsed time is real and is shown;
 * a percentage would be invented.
 */
export function WorkerJobsPanel({
  api,
  refreshSignal,
  onReuse,
  workerNames,
}: Props): JSX.Element | null {
  const [jobs, setJobs] = useState<WorkerJobView[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState<string | null>(null);

  const refresh = useCallback(async (): Promise<void> => {
    if (!api?.listWorkerJobs) return;
    try {
      setJobs(await api.listWorkerJobs());
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not read the dispatch list.");
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    void refresh();
  }, [refresh, refreshSignal]);

  const anyActive = jobs.some((job) => ACTIVE.has(job.status));

  // Polling stops the moment nothing is moving. This call is also what sweeps
  // jobs abandoned by a daemon that died, so it is worth making while work is
  // outstanding and worth not making when there is none.
  useEffect(() => {
    if (!anyActive) return;
    const timer = window.setInterval(() => void refresh(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [anyActive, refresh]);

  // A once-a-second clock for the elapsed column, running only while needed.
  const now = useTicker(anyActive);

  if (!api?.listWorkerJobs) return null;
  const downloadBundle = api.downloadWorkerBundle?.bind(api);

  async function download(job: WorkerJobView): Promise<void> {
    if (!downloadBundle) return;
    setDownloading(job.id);
    try {
      saveBlob(`${job.id}-bundle.zip`, await downloadBundle(job.id));
    } catch (cause) {
      message.error(
        cause instanceof Error ? cause.message : "The bundle could not be downloaded.",
      );
    } finally {
      setDownloading(null);
    }
  }

  const columns: ColumnsType<WorkerJobView> = [
    {
      title: "Target",
      key: "target",
      render: (_value, job) => (
        <div className="sfj-target">
          <span className="sfj-url">{job.envelope.seed_url}</span>
          <span className="sfj-sub">
            {workerNames[job.worker_id] ?? job.worker_id} ·{" "}
            {job.envelope.template_name ?? "no template"}
          </span>
        </div>
      ),
    },
    {
      title: "Status",
      key: "status",
      width: 230,
      render: (_value, job) => (
        <div className="sfj-status">
          <Tag color={STATUS_COLOUR[job.status] ?? "default"}>
            {job.status.toUpperCase()}
          </Tag>
          <span className="sfj-detail">{describeStatus(job)}</span>
        </div>
      ),
    },
    {
      title: "Timing",
      key: "timing",
      width: 200,
      render: (_value, job) => (
        <div className="sfj-status">
          <span className="sfj-clock">{elapsed(job, now)}</span>
          <span className="sfj-detail">{formatCrawlTime(job.created_at)}</span>
        </div>
      ),
    },
    {
      title: "Outcome",
      key: "outcome",
      width: 300,
      render: (_value, job) => <Outcome job={job} onReuse={onReuse} />,
    },
    {
      title: "",
      key: "actions",
      width: 170,
      render: (_value, job) => (
        <div className="sfj-actions">
          {hasBundle(job) && downloadBundle && (
            <Button
              size="small"
              type="primary"
              loading={downloading === job.id}
              disabled={downloading !== null && downloading !== job.id}
              onClick={() => void download(job)}
            >
              Download ({formatBytes(job.bundle_size_bytes)})
            </Button>
          )}
        </div>
      ),
    },
  ];

  return (
    <section aria-labelledby="sfj-title">
      <div className="sfj-head">
        <h3 id="sfj-title">Screaming Frog dispatches</h3>
        <span className="sfj-note">
          A separate job system from Crawl jobs — different ids, different
          statuses.
        </span>
        <Button size="small" onClick={() => void refresh()} loading={loading}>
          Refresh
        </Button>
      </div>

      {error && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 10 }}
          message={error}
          action={
            <Button size="small" onClick={() => void refresh()}>
              Try again
            </Button>
          }
        />
      )}

      <Table<WorkerJobView>
        rowKey="id"
        columns={columns}
        dataSource={jobs}
        size="small"
        loading={loading && jobs.length === 0}
        pagination={false}
        /* Five columns of URLs and error text do not fit a narrow window. The
           table scrolls inside its own container rather than pushing the
           dashboard sideways. */
        scroll={{ x: 900 }}
        locale={{
          emptyText: (
            <Empty description="No Screaming Frog crawl has been dispatched yet." />
          ),
        }}
      />
    </section>
  );
}

/** The outcome cell: what finished, or why it did not. */
function Outcome({
  job,
  onReuse,
}: {
  job: WorkerJobView;
  onReuse: (job: WorkerJobView) => void;
}): JSX.Element {
  if (job.status === "failed" || job.status === "partial") {
    const reason = job.error ?? "No reason was recorded.";
    const licence = isLicenceFailure(reason);
    return (
      <div className="sfj-status">
        <span className="sfj-error">{reason}</span>
        {licence ? (
          /* No retry offered, deliberately (ADR 0013 condition 6). A licence
             that is invalid or expired is a state of the machine, not of this
             crawl, and a button that re-runs it just spends another few
             minutes arriving at the identical error. */
          <span className="sfj-noretry">
            Fix the Screaming Frog licence on that machine. Running this again
            first would fail the same way.
          </span>
        ) : (
          <Button size="small" onClick={() => onReuse(job)}>
            Use these settings again
          </Button>
        )}
      </div>
    );
  }

  if (hasBundle(job)) {
    return (
      <div className="sfj-status">
        <span className="sfj-detail">
          Bundle ready · {formatBytes(job.bundle_size_bytes)}
        </span>
        <Button size="small" onClick={() => onReuse(job)}>
          Use these settings again
        </Button>
      </div>
    );
  }

  return <span className="sfj-detail">—</span>;
}

/** Whether a finished job has an archive to offer. */
function hasBundle(job: WorkerJobView): boolean {
  return job.status === "succeeded" || (job.status === "partial" && job.bundle_size_bytes != null);
}

/**
 * A sentence for each status, saying what is and is not known.
 *
 * The `dispatched` line is the important one. The worker reports alive or
 * finished and nothing between, so "running" is the whole of what the platform
 * knows about a crawl that may have hours left.
 */
function describeStatus(job: WorkerJobView): string {
  switch (job.status) {
    case "queued":
      return "Waiting for the daemon on that machine to pick it up.";
    case "dispatched":
      return "Running on that machine. No progress detail is available — only whether it is still alive.";
    case "succeeded":
      return "Finished and uploaded.";
    case "partial":
      return "Finished, but the run degraded. The reason is beside it.";
    case "failed":
      return "Did not finish.";
    default:
      // A status this build does not know about. Shown raw rather than
      // swallowed: a silent blank would be read as "nothing happened".
      return "Reported by the server under a status this dashboard does not recognise.";
  }
}

/**
 * Whether a failure is about the Screaming Frog licence.
 *
 * Matched on the message because that is all the platform has: the daemon
 * reports a string, and there is no error code on `WorkerJob`. A false positive
 * costs one hidden convenience button; a false negative offers a re-run that
 * cannot possibly succeed.
 */
function isLicenceFailure(reason: string): boolean {
  return /licen[cs]e/i.test(reason);
}

/** Elapsed for a running job, total for a finished one, "—" when unknown. */
function elapsed(job: WorkerJobView, now: number): string {
  const start = Date.parse(job.dispatched_at ?? job.created_at);
  if (Number.isNaN(start)) return "—";
  const end = job.finished_at ? Date.parse(job.finished_at) : null;
  const stop = end !== null && !Number.isNaN(end) ? end : now;
  return formatClock(Math.max(0, (stop - start) / 1000));
}

/** A once-per-second clock, running only while something is still going. */
function useTicker(enabled: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!enabled) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [enabled]);
  return now;
}
