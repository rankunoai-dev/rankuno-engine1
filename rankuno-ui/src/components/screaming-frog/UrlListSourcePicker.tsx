import { Alert, Button, Radio, Select } from "antd";
import { useCallback, useEffect, useState } from "react";
import type {
  CrawlJobSummary,
  UrlListSource,
  UrlListSourceOption,
  UrlListSourcesView,
  WorkerDispatchAdapter,
} from "../../adapters/adapterInterface";
import { formatCrawlTime } from "../../lib/time";
import "./screaming-frog.css";

/** A complete list-mode choice. Incomplete choices are reported as `null`. */
export interface UrlListChoice {
  /**
   * A `/jobs` id — a crawl **this engine** ran.
   *
   * Never a `/workers/jobs` id. The two id spaces have no join and no shared
   * prefix, so a mix-up is not a type error, it is every request answering
   * `404`. The only place this value comes from is `CrawlJobSummary.id`.
   */
  source_job_id: string;
  source: UrlListSource;
  /**
   * The source crawl's own root, as the server reports it.
   *
   * A list dispatch still needs a `seed_url`: it names the site in every log
   * line and approval summary, and its registrable domain is the rule the
   * list was filtered against. It is simply not what `--crawl-list` is given.
   */
  base_url: string;
}

interface Props {
  /** Needs `listJobs` and `listUrlListSources`; both are asked for, not assumed. */
  api: WorkerDispatchAdapter | null;
  /**
   * A crawl to open on, when the operator arrived here having already picked
   * one — the "Run in Screaming Frog" action on a cross-check does exactly
   * that.
   *
   * Only the *crawl* is carried, never the subset. Which URLs remains an
   * unanswered question on arrival, because it is the decision being approved
   * and because whether "Orphans Only" can be offered at all is the server's
   * to answer, not the caller's.
   */
  initialJobId?: string | null;
  /**
   * The current complete choice, or `null`.
   *
   * Must be stable across renders — it is an effect dependency two levels up.
   * Called only from event handlers here, never from an effect, so a parent
   * that re-renders on it cannot start a loop.
   */
  onChange: (choice: UrlListChoice | null) => void;
}

/** Crawls worth offering: the ones that could hold URLs to send. */
function selectable(jobs: readonly CrawlJobSummary[]): CrawlJobSummary[] {
  // `succeeded` and `partial` only. A queued or running crawl has nothing
  // finished to take, and a failed one has nothing at all — offering them
  // would mean a picker whose entries mostly answer "this crawl has not
  // finished, so it has no URLs to send". Whether a *source* is usable is
  // still the server's call, never re-derived here.
  return jobs
    .filter((job) => job.status === "succeeded" || job.status === "partial")
    .slice()
    .sort((left, right) => (right.crawledAt ?? "").localeCompare(left.crawledAt ?? ""));
}

/**
 * Choose a finished Rankuno crawl, and which of its URLs to send.
 *
 * Two questions, asked in order, because the second cannot be answered without
 * the first: "Orphans Only" exists only for a crawl that has already been
 * cross-checked against a Screaming Frog export, and nothing in a browser can
 * know whether one has been. So availability is *served*
 * (`GET /jobs/{id}/url-list/sources`) and rendered verbatim, reason and all —
 * a greyed-out option nobody can explain is the failure `unavailable_reason`
 * exists to prevent.
 *
 * The counts shown here are **candidates, before filtering**, and are labelled
 * as such. The truthful number is the one the preview returns after deduping
 * and the off-domain filter have run, and it is the only one the confirmation
 * dialog ever shows. Two numbers that disagree are survivable; a number in an
 * approval that is not the number dispatched is not.
 */
export function UrlListSourcePicker({
  api,
  initialJobId = null,
  onChange,
}: Props): JSX.Element {
  const [jobs, setJobs] = useState<CrawlJobSummary[]>([]);
  const [jobsLoading, setJobsLoading] = useState(false);
  const [jobsError, setJobsError] = useState<string | null>(null);

  const [jobId, setJobId] = useState<string | null>(initialJobId);
  const [sources, setSources] = useState<UrlListSourcesView | null>(null);
  const [sourcesLoading, setSourcesLoading] = useState(false);
  const [sourcesError, setSourcesError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [chosen, setChosen] = useState<UrlListSource | null>(null);

  // Keyed on the adapter object, not on a `bind` of one of its methods: `bind`
  // returns a new function every render, and the effect below would fetch in a
  // loop. Same reasoning as `ScreamingFrogView.loadWorkers`.
  const loadJobs = useCallback(async (): Promise<void> => {
    const list = api?.listJobs;
    if (!list) return;
    setJobsLoading(true);
    setJobsError(null);
    try {
      setJobs(selectable(await list.call(api)));
    } catch (cause) {
      setJobsError(
        cause instanceof Error ? cause.message : "Could not read your finished crawls.",
      );
      setJobs([]);
    } finally {
      setJobsLoading(false);
    }
  }, [api]);

  useEffect(() => {
    void loadJobs();
  }, [loadJobs]);

  // A second arrival from the cross-check panel, on a different crawl, while
  // this picker is already mounted. Handled as an effect rather than as
  // initial state alone, which only runs once. The subset is cleared and the
  // parent told, because a subset chosen from the previous crawl would
  // otherwise stand against the new one.
  useEffect(() => {
    if (initialJobId === null) return;
    setJobId(initialJobId);
    setChosen(null);
    onChange(null);
  }, [initialJobId, onChange]);

  // Building the answer means streaming a crawl result that can be tens of
  // megabytes, so this is a first-class loading state rather than a pause.
  useEffect(() => {
    const ask = api?.listUrlListSources;
    if (jobId === null || !ask) {
      setSources(null);
      return;
    }
    let cancelled = false;
    setSourcesLoading(true);
    setSourcesError(null);
    setSources(null);
    // The loading flag is cleared in the same handler that sets the result,
    // not in a `.finally`: a separate handler is a separate microtask and so a
    // second render, and the intermediate frame — options on screen, still
    // marked busy — is a real state a screen reader would announce.
    ask
      .call(api, jobId)
      .then((view) => {
        if (cancelled) return;
        setSources(view);
        setSourcesLoading(false);
      })
      .catch((cause: unknown) => {
        if (cancelled) return;
        setSourcesError(
          cause instanceof Error
            ? cause.message
            : "Could not work out what that crawl can offer.",
        );
        setSourcesLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [api, jobId, retry]);

  // Changing the crawl invalidates the subset chosen from the old one, and the
  // parent must hear about that before it can preview anything: a choice left
  // standing here would dispatch one crawl's URLs under another crawl's name.
  function chooseJob(id: string): void {
    setJobId(id);
    setChosen(null);
    onChange(null);
  }

  function chooseSource(value: UrlListSource): void {
    const option = sources?.sources.find((entry) => entry.source === value);
    if (!sources || !option?.available) return;
    setChosen(value);
    // `sources.job_id` and not the local `jobId`: it is the id the server
    // answered about, so it cannot disagree with the counts beside it.
    onChange({
      source_job_id: sources.job_id,
      source: value,
      base_url: sources.base_url,
    });
  }

  if (!api?.listJobs || !api.listUrlListSources) {
    return (
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 14 }}
        message="This mode cannot read the engine's own crawls, so there are no URLs to send."
      />
    );
  }

  return (
    <div className="sfd-list">
      <div className="sfd-field">
        <label htmlFor="sfd-source-job">Source crawl</label>
        <Select
          id="sfd-source-job"
          value={jobId}
          loading={jobsLoading}
          disabled={jobsLoading || jobs.length === 0}
          placeholder="Choose the finished crawl whose URLs to send"
          /* jsdom reports zero heights, which starves antd's virtual list. */
          virtual={false}
          onChange={chooseJob}
          options={jobs.map((job) => ({
            value: job.id,
            label: `${job.label || job.id} — ${job.baseUrl}`,
          }))}
        />
        <span className="sfd-hint">{describeJobs(jobs, jobsLoading, jobsError)}</span>
        {jobsError !== null && (
          <Button size="small" onClick={() => void loadJobs()}>
            Try again
          </Button>
        )}
      </div>

      {jobId !== null && (
        <fieldset className="sfd-fieldset">
          <legend>Which URLs</legend>
          {sourcesLoading && (
            <p className="sfd-hint" role="status">
              Reading that crawl to see what it can offer. A large crawl takes a
              few seconds.
            </p>
          )}
          {sourcesError !== null && (
            <Alert
              type="error"
              showIcon
              style={{ marginBottom: 10 }}
              message="Could not work out what that crawl can offer."
              description={sourcesError}
              action={
                <Button size="small" onClick={() => setRetry((value) => value + 1)}>
                  Try again
                </Button>
              }
            />
          )}
          {sources !== null && (
            <>
              <Radio.Group
                value={chosen}
                onChange={(event) => chooseSource(event.target.value as UrlListSource)}
              >
                {sources.sources.map((option) => (
                  <Radio
                    key={option.source}
                    value={option.source}
                    disabled={!option.available}
                    className="sfd-source"
                  >
                    <SourceOption option={option} />
                  </Radio>
                ))}
              </Radio.Group>
              <p className="sfd-hint">
                A single list holds at most {sources.max_urls.toLocaleString()}{" "}
                URLs. Over that the engine refuses rather than sending a
                shortened list, because a shortened list audits fewer pages than
                the approval says it does.
              </p>
            </>
          )}
        </fieldset>
      )}
    </div>
  );
}

/**
 * One source, with the server's own label, reason and count.
 *
 * The count is prefixed "about" and suffixed "before filtering" on purpose.
 * It is a pre-filter candidate total and the dispatched number will usually be
 * smaller; saying so here is what keeps the larger number from reading as a
 * promise the confirmation dialog then breaks.
 */
function SourceOption({ option }: { option: UrlListSourceOption }): JSX.Element {
  return (
    <span className="sfd-source-body">
      <span className="sfd-source-name">
        {option.label}
        {option.candidate_url_count !== null && (
          <span className="sfd-source-count">
            {option.exceeds_ceiling
              ? ` — more than ${option.candidate_url_count.toLocaleString()} URLs`
              : ` — about ${option.candidate_url_count.toLocaleString()} URL${
                  option.candidate_url_count === 1 ? "" : "s"
                } before filtering`}
          </span>
        )}
      </span>
      {option.description && (
        <span className="sfd-hint">{option.description}</span>
      )}
      {/* Never empty when the option is unavailable, and never a colour on its
          own: a disabled radio with no sentence beside it is the state
          operators report as "it just will not let me". */}
      {!option.available && option.unavailable_reason && (
        <span className="sfd-source-why">{option.unavailable_reason}</span>
      )}
    </span>
  );
}

/** What the source-crawl picker is actually showing, including why it is empty. */
function describeJobs(
  jobs: readonly CrawlJobSummary[],
  loading: boolean,
  error: string | null,
): string {
  if (loading) return "Reading your finished crawls…";
  if (error !== null) return "Your finished crawls could not be read.";
  if (jobs.length === 0) {
    return "No finished Rankuno crawl yet. List mode sends URLs this engine has already found, so there has to be a crawl to take them from — run one first, then come back.";
  }
  const newest = jobs[0]?.crawledAt;
  const when = newest ? ` The most recent finished ${formatCrawlTime(newest)}.` : "";
  return `${jobs.length} finished crawl${jobs.length === 1 ? "" : "s"} to choose from.${when}`;
}
