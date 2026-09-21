import { Alert, Button, Input, Select, Spin, Tag, message } from "antd";
import { useCallback, useEffect, useState } from "react";
import type {
  DispatchPreview,
  WorkerDispatchAdapter,
  WorkerJobView,
  WorkerSummary,
  WorkerTemplatesView,
} from "../../adapters/adapterInterface";
import { formatCrawlTime } from "../../lib/time";
import { useCrawlStore } from "../../store/useCrawlStore";
import { DispatchConfirmModal } from "./DispatchConfirmModal";
import { WorkerJobsPanel } from "./WorkerJobsPanel";
import "./screaming-frog.css";

interface Props {
  /** Defaults to the adapter the session is running on. Injectable for tests. */
  adapter?: WorkerDispatchAdapter | null;
}

/** The "no template" option's value. antd shows a `null` value as unchosen. */
const NO_TEMPLATE = "";

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

  const [preview, setPreview] = useState<DispatchPreview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [refreshSignal, setRefreshSignal] = useState(0);

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
  // `template_names`: that snapshot is as old as the last `GET /workers`, and
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
      // builds that view from — `template_names` and `last_seen_at`.
      const fallback = workers.find((worker) => worker.worker_id === workerId);
      setTemplates(
        fallback
          ? {
              worker_id: fallback.worker_id,
              templates: fallback.template_names,
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
    if (template !== NO_TEMPLATE && !(templates?.templates ?? []).includes(template)) {
      setTemplate(NO_TEMPLATE);
    }
  }, [templates, template]);

  async function startPreview(): Promise<void> {
    if (!api?.previewDispatch || workerId === null) return;
    const trimmed = seedUrl.trim();
    const invalid = validateUrl(trimmed);
    setUrlError(invalid);
    if (invalid) return;

    setPreviewing(true);
    setPreviewError(null);
    try {
      setPreview(
        await api.previewDispatch(workerId, {
          seed_url: trimmed,
          template_name: template === NO_TEMPLATE ? null : template,
          correlation_id: newCorrelationId(),
        }),
      );
    } catch (cause) {
      setPreviewError(
        cause instanceof Error ? cause.message : "The crawl could not be prepared.",
      );
    } finally {
      setPreviewing(false);
    }
  }

  function reuse(job: WorkerJobView): void {
    setWorkerId(job.worker_id);
    setSeedUrl(job.envelope.seed_url);
    setTemplate(job.envelope.template_name ?? NO_TEMPLATE);
    setUrlError(null);
    setPreviewError(null);
  }

  // Bound once, here, rather than inside the JSX: the modal is only rendered
  // when it exists, and binding at the call site would need a non-null
  // assertion that TypeScript cannot check across the closure.
  const confirmDispatch = api?.confirmDispatch?.bind(api);
  const canDispatch = api?.previewDispatch !== undefined;
  const blockedReason = whyBlocked({
    canDispatch,
    selected,
    seedUrl: seedUrl.trim(),
    offlineAfterS,
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
                {!selected.is_active && <Tag color="warning">DEACTIVATED</Tag>}
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

          <div className="sfd-field">
            <label htmlFor="sfd-seed">Seed URL</label>
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
                Where the crawl starts. The server normalizes it and shows you
                the result before anything runs.
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
                ...(templates?.templates ?? []).map((name) => ({
                  value: name,
                  label: name,
                })),
              ]}
            />
            <span className="sfd-hint">{describeTemplates(templates, templatesLoading)}</span>
          </div>

          {previewError && (
            <Alert
              type="error"
              showIcon
              style={{ marginBottom: 14 }}
              message={previewError}
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
          typedUrl={seedUrl.trim()}
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

/** Why the launch button is disabled, or `null` when it is not. */
function whyBlocked({
  canDispatch,
  selected,
  seedUrl,
  offlineAfterS,
}: {
  canDispatch: boolean;
  selected: WorkerSummary | null;
  seedUrl: string;
  offlineAfterS: number | null;
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
    return `This machine checked in ${formatCrawlTime(templates.reported_at)} and reported no saved templates. The crawl will use Screaming Frog's default configuration.`;
  }
  return `${templates.templates.length} template${templates.templates.length === 1 ? "" : "s"} reported ${formatCrawlTime(templates.reported_at)}.`;
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

/**
 * A per-attempt correlation id.
 *
 * `crypto.randomUUID` is deliberately not used: it is absent from insecure
 * origins and from some test environments, and this value only has to be unique
 * enough to tie one preview to its confirm in the logs.
 */
function newCorrelationId(): string {
  return `ui-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}
