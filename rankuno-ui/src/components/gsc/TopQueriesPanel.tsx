import { Alert, Button } from "antd";
import { useEffect, useId, useRef, useState } from "react";
import { ApiError } from "../../adapters/httpAdapter";
import {
  TOP_QUERIES_STOP_COPY,
  parseTopQueriesResult,
  type TopQueriesResult,
} from "../../lib/topQueries";
import { useCrawlStore } from "../../store/useCrawlStore";
import { JobPasswordPrompt } from "../jobs/JobPasswordPrompt";
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

/** The header the server reads the deletion password from (ADR 0042). */
const DELETE_PASSWORD_HEADER = "X-Deletion-Password";

/** The server detail when a protected job gets no password at all. */
const PASSWORD_REQUIRED_DETAIL = "job password required";

const PROMPT_DESCRIPTION =
  "This crawl is protected. Enter its deletion password to fetch its Search Console top queries. It is used for this request only and is not kept.";

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
 * The server detail is passed through for 403, 409, 502 and 503, because it
 * is the only place the reason lives. A 403 is shown without a guess at what it
 * means: the server has said refused, not why. A 401 only ends the session,
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

/** True when the server refused a password, or locked the job after too many tries. */
function isPasswordRefusal(cause: unknown): cause is ApiError {
  return cause instanceof ApiError && (cause.status === 403 || cause.status === 429);
}

interface Props {
  /** The selected job id. The panel renders nothing without one. */
  jobId: string | null;
  /** Whether the job has a finished result. The panel renders nothing otherwise. */
  finished: boolean;
}

/**
 * Fetch a finished crawl's Search Console top queries, on request.
 *
 * Manual only. Nothing is fetched on mount, on a job change, while polling, or
 * on retry: each fetch is a click, because one fetch can take about a minute per
 * 25,000 rows of the Search Console quota. A protected job asks for its deletion
 * password first. The prompt holds it in component state and it is sent once,
 * in the header, never stored. The result shows the row count and the stop
 * reason, never the query text. A partial result is labelled as one.
 */
export function TopQueriesPanel({ jobId, finished }: Props): JSX.Element | null {
  const adapter = useCrawlStore((state) => state.adapter);
  const protectedJob = useCrawlStore(
    (state) => state.jobs.find((job) => job.id === jobId)?.hasDeletePassword === true,
  );
  const headingId = useId();

  const [busyIds, setBusyIds] = useState<ReadonlySet<string>>(() => new Set(inFlightJobIds));
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [cooldownJobId, setCooldownJobId] = useState<string | null>(null);
  const [promptOpen, setPromptOpen] = useState(false);
  // The server reason for a refused password, shown inside the prompt.
  const [promptError, setPromptError] = useState<string | null>(null);

  // The job the panel is showing now. A response for any other job is dropped
  // rather than displayed against the wrong crawl.
  const currentJobRef = useRef<string | null>(jobId);
  useEffect(() => {
    currentJobRef.current = jobId;
    // A prompt opened for one job must not carry over to the next.
    setPromptOpen(false);
    setPromptError(null);
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

  /**
   * One fetch. Resolves true when the prompt may close: the password was
   * accepted, none was needed, or the response is no longer wanted. Resolves
   * false when the server refused the password, which keeps the prompt open.
   */
  function runFetch(password: string | undefined): Promise<boolean> {
    if (jobId === null || !finished) return Promise.resolve(true);
    // Synchronous check and add, before any await. A second click in the same
    // tick finds the id already present and does nothing.
    if (inFlightJobIds.has(jobId)) return Promise.resolve(true);
    if (typeof adapter?.fetchTopQueries !== "function") return Promise.resolve(true);

    const requestedJobId = jobId;
    // Bound here, while adapter.fetchTopQueries is narrowed, so the call keeps
    // its this and the async body below does not need a second narrowing.
    const send = adapter.fetchTopQueries.bind(adapter);
    // Only a password request carries the header. A plain click sends the call
    // exactly as it did before.
    const init =
      password === undefined ? undefined : { headers: { [DELETE_PASSWORD_HEADER]: password } };

    inFlightJobIds.add(requestedJobId);
    setBusyIds((previous) => new Set(previous).add(requestedJobId));

    return (async (): Promise<boolean> => {
      try {
        const body: unknown =
          init === undefined ? await send(requestedJobId) : await send(requestedJobId, init);
        if (currentJobRef.current !== requestedJobId) return true;
        const result = parseTopQueriesResult(body);
        setOutcome(
          result !== null
            ? { kind: "result", jobId: requestedJobId, result }
            : { kind: "error", jobId: requestedJobId, message: INVALID_RESPONSE },
        );
        return true;
      } catch (cause) {
        if (currentJobRef.current !== requestedJobId) return true;
        if (password !== undefined && isPasswordRefusal(cause)) {
          setPromptError(cause.message);
          return false;
        }
        if (
          password === undefined &&
          cause instanceof ApiError &&
          cause.status === 403 &&
          cause.message === PASSWORD_REQUIRED_DETAIL
        ) {
          // The list did not flag this job as protected, but the server says it is.
          setPromptError(null);
          setPromptOpen(true);
          return false;
        }
        const failure = describeTopQueriesFailure(cause);
        setOutcome({ kind: "error", jobId: requestedJobId, message: failure.message });
        if (failure.cooldown) setCooldownJobId(requestedJobId);
        return true;
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

  function onFetchClick(): void {
    if (protectedJob) {
      setPromptError(null);
      setPromptOpen(true);
      return;
    }
    void runFetch(undefined);
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
        <Button onClick={onFetchClick} disabled={busy || coolingDown} loading={busy}>
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

      <JobPasswordPrompt
        open={promptOpen}
        title="Deletion password"
        okText="Fetch Top Queries"
        description={PROMPT_DESCRIPTION}
        error={promptError}
        onSubmit={async (password) => {
          const accepted = await runFetch(password);
          if (accepted) {
            setPromptOpen(false);
            setPromptError(null);
          }
          return accepted;
        }}
        onCancel={() => {
          setPromptOpen(false);
          setPromptError(null);
        }}
      />
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
