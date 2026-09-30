import { Alert, Button, Modal } from "antd";
import { useEffect, useRef, useState } from "react";
import type {
  DispatchConfirmRequest,
  DispatchPreview,
  UrlListView,
  WorkerJobAccepted,
} from "../../adapters/adapterInterface";
import { ApiError } from "../../adapters/httpAdapter";
import { formatClock } from "../../lib/duration";
import { formatCrawlTime } from "../../lib/time";
import "./screaming-frog.css";

interface Props {
  preview: DispatchPreview;
  /** The machine's display name. The preview carries only its id. */
  workerName: string;
  /**
   * What the operator typed, so a normalization can be pointed out.
   *
   * Omitted for a list-mode dispatch: nobody typed a URL there — the seed is
   * the source crawl's own root — so there is no difference to point out and
   * the note would be about text the operator never entered.
   */
  typedUrl?: string;
  confirm: (request: DispatchConfirmRequest) => Promise<WorkerJobAccepted>;
  onDispatched: (job: WorkerJobAccepted) => void;
  onClose: () => void;
  /** Close and return to the form with these values still in it. */
  onStartAgain: () => void;
}

/** How a confirm failure should be presented, and what to offer afterwards. */
interface Failure {
  message: string;
  /** The same token can still be spent — the server refused before using it. */
  canRetry: boolean;
}

/**
 * The second half of preview → confirm (ADR 0013).
 *
 * Running an external binary is `MANDATORY_HITL` and there is no auto-approve,
 * so this dialog is not a courtesy "are you sure": the single-use token minted
 * by the preview is the *only* evidence of approval the dispatch endpoint
 * accepts, and it expires. What is shown here is exactly what was approved —
 * the server's normalized URL, the template, the target machine — because the
 * confirm has to echo those values byte for byte or the token is refused.
 *
 * Three states carry their own handling rather than a generic error:
 *
 * * **Expiry while the dialog is open.** The token dies on a clock the operator
 *   cannot see otherwise, so the countdown is visible and expiry swaps the
 *   launch button for "Start again" rather than leaving a button that 403s.
 * * **A double click.** A `ref` guard, not `disabled` alone: React state is
 *   applied asynchronously and two clicks in the same tick both pass a state
 *   check. The second POST would 403 ("already used") — which is a true
 *   statement about a token and an alarming one about a crawl.
 * * **An offline machine.** `worker_online: false` on the *preview* means the
 *   confirm will 409, so it is said here, before the operator commits.
 *
 * When the preview carries a `url_list` (ADR 0023), the dialog also has to
 * show **what will be crawled**, not only where it starts. A confirmation
 * reading "12,431 URLs" with no way to check them is precisely what an
 * approval gate is supposed to prevent, so the source, the count, the
 * excluded-off-domain figure and a verbatim sample are all on screen before
 * the button is reachable. The `sha256` goes back untouched: the server
 * compares it inside the same statement that spends the token.
 */
export function DispatchConfirmModal({
  preview,
  workerName,
  typedUrl,
  confirm,
  onDispatched,
  onClose,
  onStartAgain,
}: Props): JSX.Element {
  const [submitting, setSubmitting] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);
  const secondsLeft = useCountdown(preview.expires_at);
  // Sync, unlike state: two clicks in one tick both read the same stale state,
  // and the second would spend a token that no longer exists.
  const spent = useRef(false);
  const expired = secondsLeft <= 0;

  async function launch(): Promise<void> {
    if (spent.current) return;
    spent.current = true;
    setSubmitting(true);
    setFailure(null);
    try {
      const accepted = await confirm({
        token: preview.token,
        // The server's normalized values, never the operator's input. A
        // difference of one character here is a 403.
        seed_url: preview.seed_url,
        template_name: preview.template_name,
        correlation_id: preview.correlation_id,
        // Echoed verbatim. Not recomputed from `sample`, which holds only the
        // first few URLs, and not normalised: the digest names the exact bytes
        // the worker will fetch, and any transformation of it here would turn
        // a correct approval into a 403.
        ...(preview.url_list ? { url_list_sha256: preview.url_list.sha256 } : {}),
      });
      onDispatched(accepted);
    } catch (cause) {
      const described = describeFailure(cause, preview.url_list != null);
      // Only unlock when the token survived the refusal. A 403 means it is
      // gone, and re-posting it would fail identically forever.
      if (described.canRetry) spent.current = false;
      setFailure(described);
    } finally {
      setSubmitting(false);
    }
  }

  const blocked = !preview.worker_online || expired;

  return (
    <Modal
      open
      title="Confirm this Screaming Frog crawl"
      onCancel={onClose}
      width={560}
      footer={[
        <Button key="cancel" onClick={onClose}>
          Cancel
        </Button>,
        expired || (failure !== null && !failure.canRetry) ? (
          <Button key="again" type="primary" onClick={onStartAgain}>
            Start again
          </Button>
        ) : (
          <Button
            key="launch"
            type="primary"
            loading={submitting}
            disabled={blocked}
            onClick={() => void launch()}
          >
            Launch on {workerName}
          </Button>
        ),
      ]}
    >
      <p className="sfc-normalized">
        Nothing has started yet. This is what will run, and it is exactly what
        the approval covers — the crawl cannot be altered after this point
        without approving it again.
      </p>

      <dl className="sfc-rows">
        <dt>Machine</dt>
        <dd>
          {workerName} <span className="sfc-none">({preview.worker_id})</span>
        </dd>
        <dt>{preview.url_list ? "Site" : "Seed URL"}</dt>
        <dd>{preview.seed_url}</dd>
        <dt>Template</dt>
        <dd>
          {preview.template_name ?? (
            <span className="sfc-none">
              None — Screaming Frog's own default configuration on that machine
            </span>
          )}
        </dd>
      </dl>

      {preview.url_list && <UrlListSummary list={preview.url_list} />}

      {typedUrl !== undefined && preview.seed_url !== typedUrl && (
        <p className="sfc-normalized">
          The address above is the server's normalized form of what you typed
          (<code>{typedUrl}</code>). The normalized one is what will be crawled.
        </p>
      )}

      {!preview.worker_online && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 12 }}
          message={`${workerName} is not checked in.`}
          description={`Launching would be refused. ${
            preview.worker_last_seen_at === null
              ? "This machine has never checked in."
              : `Last seen ${formatCrawlTime(preview.worker_last_seen_at)}.`
          } Start the Rankuno worker daemon on that PC, then start again.`}
        />
      )}

      {expired ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message="This approval has expired."
          description="Approvals are short-lived on purpose: one stands for one crawl, at one moment. Nothing was started. Start again to get a fresh one."
        />
      ) : (
        <p className="sfc-countdown">
          Approval expires in <strong>{formatClock(secondsLeft)}</strong>.
        </p>
      )}

      {failure && (
        <Alert
          type={failure.canRetry ? "error" : "warning"}
          showIcon
          style={{ marginTop: 12 }}
          message={failure.message}
        />
      )}
    </Modal>
  );
}

/**
 * What a list-mode dispatch will actually audit.
 *
 * Four things, and each is here because its absence would let a false
 * approval through:
 *
 * * **List mode is not a site crawl.** Screaming Frog is given `--crawl-list`
 *   and audits exactly these addresses; it does not follow links outward.
 *   Said in the dialog, not in a tooltip, because an operator who reads this
 *   as a crawl of the site will read the export as a site audit.
 * * **The source.** "Orphans Only" and "All Discovered URLs" differ by orders
 *   of magnitude, and the label is the server's own wording. A pasted list
 *   names itself.
 * * **What the paste lost.** Lines that could not be read, and addresses given
 *   an assumed `https://`, are both stated here rather than only on the form
 *   the operator has already scrolled past. Each is a difference between what
 *   was pasted and what will be crawled, and this is the last screen before it
 *   becomes true.
 * * **Duplicates.** Removed, and said so. The count above is post-dedupe and is
 *   what gets crawled; without this line an operator who pasted 400 lines and
 *   is shown 380 has no way to tell a silent loss from a deliberate one.
 * * **The exclusions.** `counts.off_domain_dropped` is the number behind
 *   "Excluded N external URLs", shown with the domain that produced it — a
 *   count with no rule beside it cannot be checked.
 * * **A sample.** The one thing that makes a five-figure count checkable by a
 *   human at all. Rendered as text nodes; these are URLs from a crawled site,
 *   outside the trust boundary.
 */
function UrlListSummary({ list }: { list: UrlListView }): JSX.Element {
  const excluded = list.counts.off_domain_dropped;
  return (
    <section className="sfc-list" aria-labelledby="sfc-list-h">
      <h4 id="sfc-list-h" className="sfc-list-h">
        {list.url_count.toLocaleString()} URL{list.url_count === 1 ? "" : "s"} from{" "}
        {list.source_label}
      </h4>
      <p className="sfc-list-mode">
        <strong>List mode.</strong> Screaming Frog audits exactly these{" "}
        {list.url_count.toLocaleString()} addresses and does not spider outward
        from them. The result is not a crawl of the site.
      </p>
      <dl className="sfc-rows">
        <dt>URLs</dt>
        <dd>
          {list.url_count.toLocaleString()}{" "}
          <span className="sfc-none">({labelFor(list.source)})</span>
        </dd>
        {list.paste != null && list.paste.malformed_dropped > 0 && (
          <>
            <dt>Not read</dt>
            <dd>
              {list.paste.malformed_dropped.toLocaleString()} line
              {list.paste.malformed_dropped === 1 ? "" : "s"}{" "}
              <span className="sfc-none">
                — could not be read as a web address, and are not in this list
              </span>
            </dd>
          </>
        )}
        {list.paste != null && list.paste.scheme_added > 0 && (
          <>
            <dt>Assumed https</dt>
            <dd>
              {list.paste.scheme_added.toLocaleString()} address
              {list.paste.scheme_added === 1 ? "" : "es"}{" "}
              <span className="sfc-none">— pasted with no scheme</span>
            </dd>
          </>
        )}
        {list.counts.duplicates_dropped > 0 && (
          <>
            <dt>Duplicates</dt>
            <dd>
              {list.counts.duplicates_dropped.toLocaleString()} removed{" "}
              <span className="sfc-none">
                — the same page twice is one fetch, and would spend two of the
                licence's URLs on it
              </span>
            </dd>
          </>
        )}
        {excluded > 0 && (
          <>
            <dt>Excluded</dt>
            <dd>
              {excluded.toLocaleString()} external URL{excluded === 1 ? "" : "s"}{" "}
              <span className="sfc-none">
                {list.registrable_domain
                  ? `— outside ${list.registrable_domain}`
                  : "— outside the crawled domain"}
              </span>
            </dd>
          </>
        )}
      </dl>
      {list.sample.length > 0 && (
        <>
          <p className="sfc-normalized">
            The first {list.sample.length.toLocaleString()} of them, exactly as
            they will be sent:
          </p>
          <ul className="sfc-sample">
            {list.sample.map((url) => (
              <li key={url}>{url}</li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

/**
 * A plain-English name for a source, for the line beside the count.
 *
 * Deliberately short: `UrlListSourceOption.label` is the server's wording and
 * is already shown on the picker and in the heading above, so repeating it
 * here in full would read as two different facts.
 */
function labelFor(source: UrlListView["source"]): string {
  if (source === "orphans") return "orphans only";
  if (source === "pasted") return "exactly the list you pasted";
  return "all discovered URLs";
}

/**
 * Seconds until `expiresAt`, ticking once a second and never below zero.
 *
 * Stops once it reaches zero: an expired token cannot become valid again, and a
 * dialog left open should not wake the tab once a second forever.
 */
function useCountdown(expiresAt: string): number {
  const [seconds, setSeconds] = useState(() => secondsUntil(expiresAt));

  useEffect(() => {
    setSeconds(secondsUntil(expiresAt));
    const timer = window.setInterval(() => {
      const next = secondsUntil(expiresAt);
      setSeconds(next);
      if (next <= 0) window.clearInterval(timer);
    }, 1_000);
    return () => window.clearInterval(timer);
  }, [expiresAt]);

  return seconds;
}

/** Whole seconds until an ISO instant, floored at zero. */
function secondsUntil(expiresAt: string): number {
  const ms = new Date(expiresAt).getTime() - Date.now();
  // An unparseable timestamp reads as expired rather than as infinite time.
  // Refusing to launch is the safe direction; the server would refuse anyway.
  if (Number.isNaN(ms)) return 0;
  return Math.max(0, Math.ceil(ms / 1000));
}

/**
 * Turn a refused confirm into something an operator can act on.
 *
 * The server's own `detail` is used verbatim wherever it already says what to
 * do — the 409 names the worker and tells you to start the daemon, and
 * paraphrasing it would only lose the worker id.
 *
 * `hadList` is not decoration. A `404` means "unknown worker" for an ordinary
 * crawl and "the approved URL list is gone" for a list one, and the second is
 * the failure mode this feature introduced: the list is stored under a
 * retention window and the confirm re-checks the digest, so an approval can
 * outlive the bytes it names. Telling that operator their PC was unregistered
 * would send them to the wrong machine entirely.
 */
function describeFailure(cause: unknown, hadList: boolean): Failure {
  if (!(cause instanceof ApiError)) {
    return {
      message:
        cause instanceof Error
          ? cause.message
          : "The dispatch failed for an unknown reason.",
      canRetry: true,
    };
  }

  switch (cause.status) {
    case 403:
      // Covers expired, already-used and a mismatched url/template. Worded for
      // the common cause — a second click — because that is the one that would
      // otherwise read as "something went wrong with my crawl".
      return {
        message:
          "This approval is no longer valid: it was already used, it expired, or the details changed. Nothing was dispatched twice. Check the list below, and start again if the crawl is not there.",
        canRetry: false,
      };
    case 409:
      return { message: cause.message, canRetry: true };
    case 429:
      return {
        message: `Only one Screaming Frog crawl runs at a time, and the limit is currently reached. Wait for the running one to finish, then start again. (${cause.message})`,
        canRetry: true,
      };
    case 404:
      // Two different 404s answer this route, and they are not the same news.
      // In list mode the likely one is the *list*: its bytes are stored with a
      // retention window, and a confirm naming bytes that have expired is
      // refused before the token is touched. The server's own detail already
      // says which and says to preview again, so it is shown verbatim rather
      // than wrapped in a sentence about a machine that is probably fine.
      return hadList
        ? { message: cause.message, canRetry: false }
        : {
            message: `That machine is no longer registered. ${cause.message}`,
            canRetry: false,
          };
    default:
      return { message: cause.message, canRetry: true };
  }
}
