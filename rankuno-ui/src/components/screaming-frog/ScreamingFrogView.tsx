import { Alert, Button, Input, Radio, Select, Spin, Tag, message } from "antd";
import { useCallback, useEffect, useState } from "react";
import type {
  DispatchPreview,
  DispatchPreviewRequest,
  WorkerDispatchAdapter,
  WorkerJobView,
  WorkerSummary,
  WorkerTemplatesView,
} from "../../adapters/adapterInterface";
import { ApiError } from "../../adapters/httpAdapter";
import { formatCrawlTime } from "../../lib/time";
import { useCrawlStore } from "../../store/useCrawlStore";
import { useUiStore } from "../../store/useUiStore";
import { DispatchConfirmModal } from "./DispatchConfirmModal";
import { WorkerCredentialsPanel } from "./WorkerCredentialsPanel";
import { WorkerJobsPanel } from "./WorkerJobsPanel";
import { newCorrelationId } from "./correlationId";
import type { PastedListChoice } from "./UrlListPastePanel";
import { UrlListPastePanel } from "./UrlListPastePanel";
import type { UrlListChoice } from "./UrlListSourcePicker";
import { UrlListSourcePicker } from "./UrlListSourcePicker";
import { UnavailableSettings } from "./UnavailableSettings";
import "./screaming-frog.css";

interface Props {
  /** Defaults to the adapter the session is running on. Injectable for tests. */
  adapter?: WorkerDispatchAdapter | null;
}

/** The "no template" option's value. antd shows a `null` value as unchosen. */
const NO_TEMPLATE = "";

/**
 * What Screaming Frog is pointed at.
 *
 * `spider` is `--crawl <url>`: follow links from a seed. `list` and `paste`
 * are both `--crawl-list <file>`: fetch exactly the supplied URLs and nothing
 * else. There is no default beyond `spider` and the choice is never implied by
 * another field, because the two kinds produce different artefacts — a list run
 * describes a set of pages and must never be read as a crawl of the site
 * (ADR 0023).
 *
 * `list` and `paste` differ only in where the URLs come from — a crawl this
 * engine already ran, or a block of text an operator pasted. Everything after
 * that is one server-side path: the same dedupe, the same domain filter, the
 * same per-host SSRF check, the same ceiling, the same digest.
 */
type CrawlMode = "spider" | "list" | "paste";

/**
 * Launch a Screaming Frog crawl on a machine the operator owns.
 *
 * Two fields, and only two: a seed URL and a template. That is the whole of
 * what `WorkerJobEnvelope` carries, and the whole of what the worker will act
 * on. The older RAE screen offered twelve crawl options of which six reached
 * nothing — include/exclude patterns, GA4 fields, a URL list — and a control
 * that silently does not apply is worse than an absent one, because the crawl
 * comes back wrong and the settings say it should not have.
 *
 * Four states here are first-class rather than a shrug and an empty dropdown,
 * because each has a different thing to do about it:
 *
 * * **No machine registered.** The most likely first run. Says what a worker is
 *   and how to make one, since there is no screen for that yet.
 * * **Registered but offline.** Says when it was last seen, against the
 *   server's own threshold, and blocks the launch with the reason visible.
 * * **Never reported its templates** (`reported_at === null`). Not the same as
 *   holding none: the machine has never spoken. A dropdown saying "no templates
 *   available" would be a claim about a PC nobody has heard from.
 * * **Fixture mode.** No engine to ask, so nothing is offered.
 *
 * The one control that is not a crawl option is the mode (ADR 0023). In list
 * mode the URLs come from a finished crawl **this engine** ran — a `/jobs`
 * record, never a `/workers/jobs` dispatch; the two id spaces have no join,
 * and `UrlListSourcePicker` is the only place either is read. The seed URL
 * stays required there and is filled from the source crawl's own root: it
 * names the site in every log line, and it is the domain the list was filtered
 * against.
 */
export function ScreamingFrogView({ adapter }: Props): JSX.Element {
  const storeAdapter = useCrawlStore((state) => state.adapter);
  const api: WorkerDispatchAdapter | null = adapter ?? storeAdapter;

  const [workers, setWorkers] = useState<WorkerSummary[]>([]);
  const [offlineAfterS, setOfflineAfterS] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [workerId, setWorkerId] = useState<string | null>(null);
  const [templates, setTemplates] = useState<WorkerTemplatesView | null>(null);
  const [templatesLoading, setTemplatesLoading] = useState(false);

  const [seedUrl, setSeedUrl] = useState("");
  const [template, setTemplate] = useState<string>(NO_TEMPLATE);
  const [urlError, setUrlError] = useState<string | null>(null);

  const [mode, setMode] = useState<CrawlMode>("spider");
  const [listChoice, setListChoice] = useState<UrlListChoice | null>(null);
  const [pasteChoice, setPasteChoice] = useState<PastedListChoice | null>(null);
  const [listSourceJobId, setListSourceJobId] = useState<string | null>(null);

  const [preview, setPreview] = useState<DispatchPreview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState<PreviewFailure | null>(null);
  const [refreshSignal, setRefreshSignal] = useState(0);

  // "Run in Screaming Frog", clicked on a cross-check over on the jobs screen.
  // Consumed once and cleared: left standing it would re-arm list mode every
  // time the operator came back here, which is a crawl setting they asked for
  // once and would then have to undo on every visit.
  const requestedListJob = useUiStore((state) => state.listCrawlSourceJobId);
  const clearListCrawl = useUiStore((state) => state.clearListCrawl);
  useEffect(() => {
    if (requestedListJob === null) return;
    setMode("list");
    setListSourceJobId(requestedListJob);
    // Which URLs is still unanswered — only the crawl was carried across.
    setListChoice(null);
    setPreview(null);
    setPreviewError(null);
    setUrlError(null);
    clearListCrawl();
  }, [requestedListJob, clearListCrawl]);

  // Keyed on the adapter object, never on `api.listWorkers.bind(api)`: `bind`
  // returns a fresh function on every render, so a dependency on one would make
  // this callback new every render and the effect below fetch forever.
  const loadWorkers = useCallback(async (): Promise<void> => {
    if (!api?.listWorkers) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setLoadError(null);
    try {
      const view = await api.listWorkers();
      setWorkers(view.workers);
      setOfflineAfterS(view.offline_after_s);
      // Chosen for the operator only when there is no choice to make. With
      // several machines, picking one for them risks dispatching to the wrong
      // desk — the id is not something you notice afterwards.
      setWorkerId((current) =>
        current ?? (view.workers.length === 1 ? (view.workers[0]?.worker_id ?? null) : null),
      );
    } catch (cause) {
      setLoadError(
        cause instanceof Error ? cause.message : "Could not read the list of machines.",
      );
      setWorkers([]);
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    void loadWorkers();
  }, [loadWorkers]);

  const selected = workers.find((worker) => worker.worker_id === workerId) ?? null;

  // Re-read on every selection rather than trusting the list's own
  // `templates`: that snapshot is as old as the last `GET /workers`, and
  // this endpoint is the only one that reports *when* the machine last spoke,
  // which is what separates "holds none" from "has never said".
  useEffect(() => {
    if (workerId === null) {
      setTemplates(null);
      return;
    }
    const fetchTemplates = api?.getWorkerTemplates;
    if (!fetchTemplates) {
      // Fall back to the summary, which carries the same two facts the server
      // builds that view from — `templates` and `last_seen_at`.
      const fallback = workers.find((worker) => worker.worker_id === workerId);
      setTemplates(
        fallback
          ? {
              worker_id: fallback.worker_id,
              templates: fallback.templates,
              unrecognised_count: fallback.unrecognised_template_count,
              reported_at: fallback.last_seen_at,
            }
          : null,
      );
      return;
    }
    let cancelled = false;
    setTemplatesLoading(true);
    fetchTemplates
      .call(api, workerId)
      .then((view) => {
        if (!cancelled) setTemplates(view);
      })
      .catch(() => {
        // Not surfaced as an error: the launch does not need a template, and a
        // red banner over an optional picker would read as a blocked crawl.
        if (!cancelled) setTemplates(null);
      })
      .finally(() => {
        if (!cancelled) setTemplatesLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [api, workerId, workers]);

  // A template the selected machine does not hold would be refused there, so a
  // machine change drops a choice that no longer applies rather than carrying
  // it silently into the next dispatch.
  useEffect(() => {
    const held = (templates?.templates ?? []).some((entry) => entry.name === template);
    if (template !== NO_TEMPLATE && !held) {
      setTemplate(NO_TEMPLATE);
    }
  }, [templates, template]);

  // The note a human wrote beside the chosen config on the worker. Looked up
  // from the list rather than stored alongside the selection: the list is
  // re-read on every machine change, and a stale copy of a description is a
  // description of a different config.
  const chosen = (templates?.templates ?? []).find((entry) => entry.name === template);

  async function startPreview(): Promise<void> {
    if (!api?.previewDispatch || workerId === null) return;
    const trimmed = seedUrl.trim();
    const invalid = validateUrl(trimmed);
    setUrlError(invalid);
    if (invalid) return;
    // Belt and braces with `whyBlocked`: a list-mode preview with no chosen
    // source would build no list and queue an ordinary site crawl under a
    // heading that says otherwise.
    if (mode === "list" && listChoice === null) return;
    if (mode === "paste" && pasteChoice === null) return;

    setPreviewing(true);
    setPreviewError(null);
    try {
      setPreview(
        await api.previewDispatch(workerId, {
          seed_url: trimmed,
          template_name: template === NO_TEMPLATE ? null : template,
          correlation_id: newCorrelationId(),
          // This call is what builds and stores the list, so the count and the
          // digest in the response describe bytes that already exist. Nothing
          // shown for approval is ever carried over from the picker above.
          ...listRequest(mode, listChoice, pasteChoice),
        }),
      );
    } catch (cause) {
      setPreviewError(describePreviewFailure(cause));
    } finally {
      setPreviewing(false);
    }
  }

  // Stable across renders: the picker holds it as a prop and calls it from its
  // own handlers, and a fresh closure every render would be a new prop every
  // render. Dropping any standing preview is the point — an approval describes
  // one list, and this is the moment that list stopped being the chosen one.
  const chooseList = useCallback((choice: UrlListChoice | null): void => {
    setListChoice(choice);
    setPreview(null);
    setPreviewError(null);
    if (choice && choice.base_url) {
      // The source crawl's own root, not something typed. It is the domain the
      // list was filtered against, so any other address would name a site the
      // URLs are not from.
      setSeedUrl(choice.base_url);
      setUrlError(null);
    }
  }, []);

  // Stable across renders for the same reason `chooseList` is: the panel holds
  // it as a prop. The seed URL is filled from the chosen domain — a pasted list
  // has no source crawl to take one from, and its registrable domain is what
  // the whole list is filtered against, so any other address would name a site
  // the URLs are not from.
  const choosePaste = useCallback((choice: PastedListChoice | null): void => {
    setPasteChoice(choice);
    setPreview(null);
    setPreviewError(null);
    if (choice) {
      setSeedUrl(choice.seedUrl);
      setUrlError(null);
    }
  }, []);

  function changeMode(next: CrawlMode): void {
    setMode(next);
    setListChoice(null);
    setPasteChoice(null);
    setListSourceJobId(null);
    setPreview(null);
    setPreviewError(null);
    setUrlError(null);
  }

  function reuse(job: WorkerJobView): void {
    setWorkerId(job.worker_id);
    setSeedUrl(job.envelope.seed_url);
    setTemplate(job.envelope.template_name ?? NO_TEMPLATE);
    setUrlError(null);
    setPreviewError(null);
    // Reuse copies the envelope, and the envelope carries a digest, not a
    // list. Re-running a list job means choosing its source again — silently
    // dropping back to a site crawl with the same seed would be a different
    // crawl wearing the old one's settings.
    changeMode("spider");
  }

  // Bound once, here, rather than inside the JSX: the modal is only rendered
  // when it exists, and binding at the call site would need a non-null
  // assertion that TypeScript cannot check across the closure.
  const confirmDispatch = api?.confirmDispatch?.bind(api);
  const canDispatch = api?.previewDispatch !== undefined;
  const canListCrawl = api?.listUrlListSources !== undefined && api?.listJobs !== undefined;
  const canPasteList = api?.planPastedUrlList !== undefined;
  const blockedReason = whyBlocked({
    canDispatch,
    selected,
    seedUrl: seedUrl.trim(),
    offlineAfterS,
    mode,
    hasList: mode === "paste" ? pasteChoice !== null : listChoice !== null,
  });

  return (
    <div className="sfd-wrap">
      <div className="sfd-head">
        <h2>Screaming Frog crawl</h2>
      </div>
      <p className="sfd-sub">
        Runs on a Windows machine you control, through the Rankuno worker
        daemon. You approve the exact URL, template and machine before anything
        starts, and the approval is good for about two minutes.
      </p>

      {!canDispatch && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16, maxWidth: 720 }}
          message="Fixture mode — no engine is reachable, so no machine can be asked to crawl anything."
        />
      )}

      {loading ? (
        <div style={{ padding: 32 }}>
          <Spin tip="Reading registered machines…">
            <div style={{ minHeight: 40 }} />
          </Spin>
        </div>
      ) : loadError ? (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16, maxWidth: 720 }}
          message="Could not read the list of machines."
          description={loadError}
          action={
            <Button size="small" onClick={() => void loadWorkers()}>
              Try again
            </Button>
          }
        />
      ) : workers.length === 0 ? (
        <NoWorkers onRefresh={() => void loadWorkers()} canAsk={canDispatch} />
      ) : (
        <div className="sfd-card">
          <div className="sfd-field">
            <label htmlFor="sfd-worker">Machine</label>
            <Select
              id="sfd-worker"
              value={workerId}
              placeholder="Choose the PC that will run the crawl"
              onChange={(value: string) => setWorkerId(value)}
              /* jsdom reports zero heights, which starves antd's virtual
                 list; a fleet of desktops does not need one anyway. */
              virtual={false}
              options={workers.map((worker) => ({
                value: worker.worker_id,
                label: `${worker.display_name} — ${worker.is_online ? "online" : "offline"}`,
              }))}
            />
            {selected && (
              <span className="sfd-hint">
                <Tag color={selected.is_online ? "success" : "default"}>
                  {selected.is_online ? "ONLINE" : "OFFLINE"}
                </Tag>
                {!selected.is_active && <Tag color="error">REVOKED</Tag>}
                {describeLastSeen(selected, offlineAfterS)}
              </span>
            )}
          </div>

          {selected && !selected.is_online && (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 14 }}
              message={`${selected.display_name} is not checked in.`}
              description="Start the Rankuno worker daemon on that PC — the crawl is refused until the machine reports in, so nothing would be queued."
            />
          )}

          {/* A fieldset and a legend, not a styled label: this is a group of
              radios, and grouping is what a screen reader announces before
              reading either option. */}
          <fieldset className="sfd-fieldset">
            <legend>What to crawl</legend>
            <Radio.Group
              value={mode}
              onChange={(event) => changeMode(event.target.value as CrawlMode)}
            >
              <Radio value="spider" className="sfd-source">
                <span className="sfd-source-body">
                  <span className="sfd-source-name">Spider from a seed URL</span>
                  <span className="sfd-hint">
                    Screaming Frog follows links outward from one address. The
                    ordinary crawl.
                  </span>
                </span>
              </Radio>
              <Radio value="list" className="sfd-source" disabled={!canListCrawl}>
                <span className="sfd-source-body">
                  <span className="sfd-source-name">
                    A list of URLs from a finished Rankuno crawl
                  </span>
                  <span className="sfd-hint">
                    Screaming Frog fetches exactly those URLs and does not
                    spider outward. This is the only way to audit orphans — a
                    page nothing links to cannot be reached by following links.
                  </span>
                  {!canListCrawl && (
                    <span className="sfd-source-why">
                      This mode cannot read the engine's own crawls, so there is
                      nothing to take URLs from.
                    </span>
                  )}
                </span>
              </Radio>
              <Radio value="paste" className="sfd-source" disabled={!canPasteList}>
                <span className="sfd-source-body">
                  <span className="sfd-source-name">A list of URLs I paste</span>
                  <span className="sfd-hint">
                    The same list mode, for URLs this engine has never crawled —
                    a column out of a spreadsheet. You see how many were read,
                    and what could not be, before you approve anything.
                  </span>
                  {!canPasteList && (
                    <span className="sfd-source-why">
                      This mode cannot check a pasted list, so there is nothing
                      to send.
                    </span>
                  )}
                </span>
              </Radio>
            </Radio.Group>
          </fieldset>

          {mode === "list" && (
            <UrlListSourcePicker
              api={api}
              initialJobId={listSourceJobId}
              onChange={chooseList}
            />
          )}

          {mode === "paste" && <UrlListPastePanel api={api} onChange={choosePaste} />}

          <div className="sfd-field">
            <label htmlFor="sfd-seed">{mode === "spider" ? "Seed URL" : "Site"}</label>
            <Input
              id="sfd-seed"
              value={seedUrl}
              placeholder="https://www.example.com/"
              status={urlError ? "error" : undefined}
              aria-invalid={urlError !== null}
              aria-describedby={urlError ? "sfd-seed-error" : "sfd-seed-hint"}
              onChange={(event) => {
                setSeedUrl(event.target.value);
                if (urlError) setUrlError(null);
              }}
              onPressEnter={() => void startPreview()}
            />
            {urlError ? (
              <span className="sfd-invalid" id="sfd-seed-error" role="alert">
                {urlError}
              </span>
            ) : (
              <span className="sfd-hint" id="sfd-seed-hint">
                {seedHint(mode)}
              </span>
            )}
          </div>

          <div className="sfd-field">
            <label htmlFor="sfd-template">Screaming Frog template</label>
            <Select
              id="sfd-template"
              value={template}
              loading={templatesLoading}
              disabled={templatesLoading}
              virtual={false}
              onChange={(value: string) => setTemplate(value)}
              options={[
                {
                  value: NO_TEMPLATE,
                  label: "None — that machine's own default configuration",
                },
                ...(templates?.templates ?? []).map((entry) => ({
                  value: entry.name,
                  label: entry.name,
                })),
              ]}
            />
            {/* Beneath the Select, matching where RAE put it. A `.seospiderconfig`
                is binary, so this sentence is the only description of the chosen
                config that exists anywhere. Rendered as a text node — it comes
                from a machine outside the trust boundary and is never HTML. */}
            {chosen?.description ? (
              <p className="sfd-template-note">{chosen.description}</p>
            ) : null}
            <span className="sfd-hint">{describeTemplates(templates, templatesLoading)}</span>
          </div>

          {/* Directly under the template picker, because that is the answer it
              gives: include and exclude patterns are decided by which config
              is chosen, and the chosen config's own note is what the panel
              shows. No control inside it collects anything. */}
          <UnavailableSettings template={chosen ?? null} />

          {previewError && (
            <Alert
              type={previewError.refusal ? "warning" : "error"}
              showIcon
              style={{ marginBottom: 14 }}
              message={previewError.heading}
              description={previewError.detail}
            />
          )}

          <div className="sfd-launch">
            <Button
              type="primary"
              loading={previewing}
              disabled={blockedReason !== null}
              onClick={() => void startPreview()}
            >
              Review and launch
            </Button>
            {blockedReason !== null && (
              <span className="sfd-blocked">{blockedReason}</span>
            )}
          </div>
        </div>
      )}

      {!loading && !loadError && workers.length > 0 && (
        <WorkerCredentialsPanel
          api={api}
          workers={workers}
          onChanged={() => void loadWorkers()}
        />
      )}

      <WorkerJobsPanel
        api={api}
        refreshSignal={refreshSignal}
        onReuse={reuse}
        workerNames={Object.fromEntries(
          workers.map((worker) => [worker.worker_id, worker.display_name]),
        )}
      />

      {preview && confirmDispatch && (
        <DispatchConfirmModal
          preview={preview}
          workerName={selected?.display_name ?? preview.worker_id}
          /* Only in spider mode. In the two list modes the address was filled in from
             the source crawl, so a note about "what you typed" would be about
             text the operator never entered. */
          typedUrl={mode === "spider" ? seedUrl.trim() : undefined}
          confirm={(request) => confirmDispatch(preview.worker_id, request)}
          onDispatched={() => {
            setPreview(null);
            setRefreshSignal((value) => value + 1);
            message.success("Crawl dispatched. It appears below once the machine picks it up.");
          }}
          onClose={() => setPreview(null)}
          onStartAgain={() => {
            // The form still holds what was typed, so "again" means one click
            // on Review and launch — not retyping a URL that was correct.
            setPreview(null);
            setPreviewError(null);
          }}
        />
      )}
    </div>
  );
}

/**
 * The first-run state: nothing registered.
 *
 * Explains what a worker is, because nothing else in this dashboard does, and
 * gives the registration call verbatim — there is no screen for it today, and
 * an empty dropdown with no explanation is how an operator concludes the
 * feature is broken.
 */
function NoWorkers({
  onRefresh,
  canAsk,
}: {
  onRefresh: () => void;
  canAsk: boolean;
}): JSX.Element {
  return (
    <div className="sfd-card sfd-explain">
      <h3>No machine is registered yet</h3>
      <p>
        A <em>worker</em> is your own Windows PC with the Rankuno worker daemon
        running on it. Screaming Frog is a desktop application and this
        dashboard runs in a Linux container, so the crawl has to happen on a
        machine that has Screaming Frog and a licence on it. The daemon asks
        this server for work, runs it locally, and uploads the finished export
        back.
      </p>
      <p>Registering one is an API call today — there is no screen for it yet:</p>
      <code className="sfd-code">
        {`POST /api/v1/workers
Authorization: Bearer <your session token>

{ "display_name": "Studio desktop" }`}
      </code>
      <p>
        The response carries a one-time <code>worker_secret</code>, which is
        never shown again. Put it and the returned <code>worker_id</code> in the
        environment on that PC, then start the daemon with{" "}
        <code>rankuno-worker</code>. It reports which Screaming Frog templates
        it holds when it checks in.
      </p>
      {canAsk && (
        <Button size="small" onClick={onRefresh}>
          Check again
        </Button>
      )}
    </div>
  );
}

/**
 * A refused preview, as the form should present it.
 *
 * `refusal` separates "the server decided against this, and told you why" from
 * "something went wrong". A 409 or a 422 here is a *decision about the data* —
 * this crawl has never been cross-checked, or its list is over the ceiling —
 * and an operator who reads that as a fault goes looking for a bug instead of
 * choosing the other source.
 */
interface PreviewFailure {
  heading: string;
  /** The server's own sentence, verbatim. */
  detail: string;
  /** A decision to act on rather than a failure to report. */
  refusal: boolean;
}

/**
 * Turn a refused preview into something an operator can act on.
 *
 * `detail` is always the server's own text and is never paraphrased: the 422
 * names both numbers, says why a shorter list is not substituted, and points
 * at the smaller source; the 409 explains what a cross-check has to do with an
 * orphan. Rewriting either would lose the part that says what to do next.
 *
 * The headings exist because the server's sentence alone does not say whether
 * anything ran. Nothing did — a preview builds and stores a list, and a
 * refusal means it built none — and "nothing will run" is the claim the
 * over-ceiling case most needs, because a ceiling that trimmed rather than
 * refused would be the reasonable guess.
 */
function describePreviewFailure(cause: unknown): PreviewFailure {
  if (!(cause instanceof ApiError)) {
    return {
      heading: "The crawl could not be prepared.",
      detail: cause instanceof Error ? cause.message : "No reason was given.",
      refusal: false,
    };
  }
  switch (cause.status) {
    case 409:
      return {
        heading: "Nothing was prepared — that crawl cannot supply those URLs.",
        detail: cause.message,
        refusal: true,
      };
    case 422:
      return {
        // Said first and plainly. The one wrong conclusion available here is
        // "it will run, just with fewer URLs", and the engine refuses rather
        // than trimming precisely so that never happens.
        heading: "Nothing was prepared, and no shortened crawl will run.",
        detail: cause.message,
        refusal: true,
      };
    case 404:
      return {
        heading: "That crawl is not available.",
        detail: cause.message,
        refusal: true,
      };
    case 403:
      return {
        heading: "That crawl is not yours to send.",
        detail: cause.message,
        refusal: true,
      };
    case 400:
      return {
        heading: "That address cannot be crawled.",
        detail: cause.message,
        refusal: true,
      };
    default:
      return {
        heading: "The crawl could not be prepared.",
        detail: cause.message,
        refusal: false,
      };
  }
}

/**
 * The `url_list` half of a preview request, or nothing at all.
 *
 * A function rather than an inline ternary because there are now three modes
 * and the spread had to stay a single expression. `spider` contributes
 * nothing, which is what makes a plain `--crawl` preview identical to every
 * request predating ADR 0023.
 */
function listRequest(
  mode: CrawlMode,
  list: UrlListChoice | null,
  paste: PastedListChoice | null,
): { url_list?: DispatchPreviewRequest["url_list"] } {
  if (mode === "list" && list) {
    return { url_list: { source_job_id: list.source_job_id, source: list.source } };
  }
  if (mode === "paste" && paste) {
    // The raw text, unsplit. The server parses it with the same parser that
    // produced the counts the operator just read, so the number approved and
    // the number crawled come from one implementation.
    return { url_list: { source: "pasted", urls: paste.urls } };
  }
  return {};
}

/** What the address field is for, which is not the same thing in all three modes. */
function seedHint(mode: CrawlMode): string {
  if (mode === "spider") {
    return "Where the crawl starts. The server normalizes it and shows you the result before anything runs.";
  }
  if (mode === "paste") {
    return "Filled in from the site you chose above. A list run still needs an address: it names the site in the job record, and its domain is what the list is filtered against. It is not spidered.";
  }
  return "Filled in from the source crawl. A list run still needs an address: it names the site in the job record, and its domain is what the list was filtered against. It is not spidered.";
}

/** Why the launch button is disabled, or `null` when it is not. */
function whyBlocked({
  canDispatch,
  selected,
  seedUrl,
  offlineAfterS,
  mode,
  hasList,
}: {
  canDispatch: boolean;
  selected: WorkerSummary | null;
  seedUrl: string;
  offlineAfterS: number | null;
  mode: CrawlMode;
  hasList: boolean;
}): string | null {
  if (!canDispatch) return "Fixture mode cannot dispatch a crawl.";
  if (!selected) return "Choose the machine that will run the crawl.";
  if (!selected.is_online) {
    const threshold =
      offlineAfterS === null ? "" : ` (a machine counts as offline after ${offlineAfterS}s without checking in)`;
    return selected.last_seen_at === null
      ? `${selected.display_name} has never checked in — start the worker daemon on it${threshold}.`
      : `${selected.display_name} was last seen ${formatCrawlTime(selected.last_seen_at)}${threshold}.`;
  }
  // Before the seed check, and deliberately: in list mode the address is
  // filled in *by* choosing a source, so "enter a URL" would be an instruction
  // to do something the operator cannot do yet.
  if (mode === "list" && !hasList) {
    return "Choose the crawl to take URLs from, and which of its URLs to send.";
  }
  if (mode === "paste" && !hasList) {
    return "Paste the URLs to crawl, then press Check this list.";
  }
  if (!seedUrl) return "Enter the URL the crawl should start from.";
  return null;
}

/** Last-seen, phrased against the server's own threshold rather than ours. */
function describeLastSeen(worker: WorkerSummary, offlineAfterS: number | null): string {
  const threshold = offlineAfterS === null ? "" : ` · offline after ${offlineAfterS}s`;
  return worker.last_seen_at === null
    ? `never checked in${threshold}`
    : `last seen ${formatCrawlTime(worker.last_seen_at)}${threshold}`;
}

/**
 * What the template picker is actually showing.
 *
 * The `reported_at === null` branch is the whole reason this function exists.
 * An empty list from a machine that has never spoken is not a machine with no
 * templates, and saying "no templates available" there would be a claim the
 * server never made.
 */
function describeTemplates(
  templates: WorkerTemplatesView | null,
  loading: boolean,
): string {
  if (loading) return "Asking that machine what it holds…";
  if (templates === null) return "Choose a machine to see the templates it holds.";
  if (templates.reported_at === null) {
    return "This machine has not reported its templates yet — it has never checked in. Start the worker daemon on it; the list fills in on its first check-in. A crawl can still run without a template.";
  }
  if (templates.templates.length === 0) {
    return `This machine checked in ${formatCrawlTime(templates.reported_at)} and reported no saved templates.${describeSkipped(templates.unrecognised_count)} The crawl will use Screaming Frog's default configuration.`;
  }
  return `${templates.templates.length} template${templates.templates.length === 1 ? "" : "s"} reported ${formatCrawlTime(templates.reported_at)}.${describeSkipped(templates.unrecognised_count)}`;
}

/**
 * Say that files were skipped, and why, or say nothing.
 *
 * The case this exists for: Screaming Frog's own Save As names a config
 * `SEO Spider Config - Basic.seospiderconfig`, which is not a slug, so the
 * worker cannot offer it. Before this line the operator saw an empty dropdown
 * over a full folder and no reason for it anywhere in the product. The
 * filenames themselves stay on the worker — they are arbitrary text from
 * outside the trust boundary, they are logged on the machine that holds them,
 * and that is the only place a human can rename anything.
 */
function describeSkipped(count: number): string {
  // `!count` and not `count <= 0`: an older engine that does not send the
  // field at all leaves this `undefined`, and `undefined <= 0` is false, which
  // would put the words "undefined files were not recognised" on the screen.
  if (!count || count <= 0) return "";
  const files = count === 1 ? "file was" : "files were";
  return ` ${count} ${files} not recognised: a config file's name must be lower-case letters, digits, hyphens or underscores, so rename it on that machine to offer it here.`;
}

/** Reject what the server would reject, before spending a round trip on it. */
function validateUrl(value: string): string | null {
  if (!value) return "Enter the URL the crawl should start from.";
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    return "Must be a full URL, including https://";
  }
  if (parsed.protocol !== "https:" && parsed.protocol !== "http:") {
    return "Only http:// and https:// addresses can be crawled.";
  }
  return null;
}
