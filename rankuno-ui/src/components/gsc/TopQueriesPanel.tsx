import { Alert, Button } from "antd";
import { useEffect, useId, useRef, useState } from "react";
import { ApiError } from "../../adapters/httpAdapter";
import {
  TOP_QUERIES_STOP_COPY,
  parseTopQueriesResult,
  type TopQueriesResult,
} from "../../lib/topQueries";
import { useCrawlStore } from "../../store/useCrawlStore";
import "./gsc.css";

/**
 * How long the button stays off after a `502` or `503`.
 *
 * Those answers mean Search Console or the save failed, and the server fetch
 * takes about a minute per page of rows, so an immediate second click only
 * repeats the wait. Also the only retry guard: nothing retries on its own.
 */
const COOLDOWN_MS = 30_000;

const GENERIC_FAILURE = "Top queries could not be fetched. Try again in a moment.";
const INVALID_RESPONSE =
  "The engine answered, but the answer could not be read. Nothing is shown.";

/**
 * Job ids with a top-queries request in flight, shared by every instance.
 *
 * Module-level rather than a `useRef`: the panel lives inside a modal that
 * unmounts on close, so a per-instance ref would forget a request still pending
 * and let a reopened modal send the same fetch again. A `Set` is updated
 * synchronously before the first `await`, which is what makes the guard hold
 * against a second click in the same tick.
 */
const inFlightJobIds = new Set<string>();

type Outcome =
  | { kind: "result"; jobId: string; result: TopQueriesResult }
  | { kind: "error"; jobId: string; message: string };

interface Failure {
  message: string;
  cooldown: boolean;
}

/**
 * What a failed fetch says on screen, by HTTP status.
 *
 * The server's `detail` is passed through for 403, 409, 502 and 503, because it
 * is the only place the reason lives. A 403 is shown without a guess at what it
 * means: the server has said "refused", not why. A `401` only ends the session,
 * which the shared session flow already handles, so it gets a neutral line
 * rather than an error the user cannot act on.
 */
function describeTopQueriesFailure(cause: unknown): Failure {
  if (!(cause instanceof ApiError)) return { message: GENERIC_FAILURE, cooldown: false };
  switch (cause.status) {
    case 401:
      return { message: "Your session has ended. Sign in again to fetch top queries.", cooldown: false };
    case 403:
      return { message: `The engine refused this request. ${cause.message}`, cooldown: false };
    case 409:
      return { message: `Top queries cannot be fetched for this crawl. ${cause.message}`, cooldown: false };
    case 502:
    case 503:
      return {
        message: `Nothing was saved, so any earlier result still stands. ${cause.message} You can try again in ${COOLDOWN_MS / 1000} seconds.`,
        cooldown: true,
      };
    default:
      return { message: GENERIC_FAILURE, cooldown: false };
  }
}

interface Props {
  /** The selected job's id. The panel renders nothing without one. */
  jobId: string | null;
  /** Whether the job has a finished result. The panel renders nothing otherwise. */
  finished: boolean;
}

/**
 * Fetch a finished crawl's Search Console top queries, on request.
 *
 * Manual only. Nothing is fetched on mount, on a job change, while polling, or
 * on retry: each fetch is a click, because one fetch can take about a minute per
 * 25,000 rows of the Search Console quota. The result shows the row count and
 * the stop reason, never the query text. A partial result is labelled as one.
 */
export function TopQueriesPanel({ jobId, finished }: Props): JSX.Element | null {
  const adapter = useCrawlStore((state) => state.adapter);
  const headingId = useId();

  const [busyIds, setBusyIds] = useState<ReadonlySet<string>>(() => new Set(inFlightJobIds));
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [cooldownJobId, setCooldownJobId] = useState<string | null>(null);

  // The job the panel is showing now. A response for any other job is dropped
  // rather than displayed against the wrong crawl.
  const currentJobRef = useRef<string | null>(jobId);
  useEffect(() => {
    currentJobRef.current = jobId;
  }, [jobId]);

  // The cooldown lifts by itself. Cleared on the timer, not by a render.
  useEffect(() => {
    if (cooldownJobId === null) return;
    const timer = window.setTimeout(() => setCooldownJobId(null), COOLDOWN_MS);
    return () => window.clearTimeout(timer);
  }, [cooldownJobId]);

  if (jobId === null || !finished || typeof adapter?.fetchTopQueries !== "function") {
    return null;
  }

  const busy = busyIds.has(jobId);
  const coolingDown = cooldownJobId === jobId;
  const shown = outcome !== null && outcome.jobId === jobId ? outcome : null;

  function fetchTopQueries(): void {
    if (jobId === null || !finished) return;
    // Synchronous check and add, before any `await`. A second click in the same
    // tick finds the id already present and does nothing.
    if (inFlightJobIds.has(jobId)) return;
    if (typeof adapter?.fetchTopQueries !== "function") return;

    const requestedJobId = jobId;
    // Bound here, while `adapter.fetchTopQueries` is narrowed, so the call keeps
    // its `this` and the async body below does not need a second narrowing.
    const send = adapter.fetchTopQueries.bind(adapter);

    inFlightJobIds.add(requestedJobId);
    setBusyIds((previous) => new Set(previous).add(requestedJobId));

    void (async () => {
      try {
        const body: unknown = await send(requestedJobId);
        if (currentJobRef.current !== requestedJobId) return;
        const result = parseTopQueriesResult(body);
        setOutcome(
          result !== null
            ? { kind: "result", jobId: requestedJobId, result }
            : { kind: "error", jobId: requestedJobId, message: INVALID_RESPONSE },
        );
      } catch (cause) {
        if (currentJobRef.current !== requestedJobId) return;
        const failure = describeTopQueriesFailure(cause);
        setOutcome({ kind: "error", jobId: requestedJobId, message: failure.message });
        if (failure.cooldown) setCooldownJobId(requestedJobId);
      } finally {
        inFlightJobIds.delete(requestedJobId);
        setBusyIds((previous) => {
          const next = new Set(previous);
          next.delete(requestedJobId);
          return next;
        });
      }
    })();
  }

  return (
    <section className="gsc-card" aria-labelledby={headingId}>
      <h3 id={headingId} className="gsc-title">
        Top queries
      </h3>
      <p className="gsc-hint">
        Fetches every query row Search Console holds for this crawl&apos;s property over the
        last year. Runs only when you click, and the result is kept on the crawl.
      </p>
      <div className="gsc-top-queries-actions">
        <Button onClick={fetchTopQueries} disabled={busy || coolingDown} loading={busy}>
          Fetch Top Queries
        </Button>
        {busy && (
          <span className="gsc-hint">
            Fetching from Search Console. A large property takes about a minute per 25,000 rows.
          </span>
        )}
      </div>

      {shown?.kind === "result" && <ResultNotice result={shown.result} />}
      {shown?.kind === "error" && <Alert type="error" showIcon message={shown.message} />}
    </section>
  );
}

function ResultNotice({ result }: { result: TopQueriesResult }): JSX.Element {
  const count = `${result.rows.toLocaleString()} ${result.rows === 1 ? "row" : "rows"}`;
  if (result.complete) {
    return (
      <p role="status" className="gsc-hint">
        {count} fetched. {TOP_QUERIES_STOP_COPY[result.stopReason]}
      </p>
    );
  }
  return (
    <div role="status" className="gsc-alert gsc-alert--warning">
      <span>
        <strong>Partial result:</strong> {count} received. {TOP_QUERIES_STOP_COPY[result.stopReason]}{" "}
        Do not read this as the full result.
      </span>
    </div>
  );
}
