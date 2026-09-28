import { Alert, Button } from "antd";
import "./screaming-frog.css";

interface Props {
  /** Opens the existing engine crawl form (`LiveCrawlModal`). */
  onEngineCrawl: () => void;
  /** Enters the engine with no form open, on the view last used. */
  onOpenEngine: () => void;
  /** Switches to the Screaming Frog dispatch view. */
  onScreamingFrog: () => void;
  /** False in fixture mode, where no engine is reachable to accept a crawl. */
  canStartEngineCrawl: boolean;
  /** False in fixture mode: there is no org, no session and no worker fleet. */
  canDispatchScreamingFrog: boolean;
}

/**
 * The opening screen: two crawlers, named, with the difference stated.
 *
 * They are not two buttons for the same thing. The engine crawl runs on the
 * server, classifies pages and feeds the visualizer; the Screaming Frog crawl
 * runs a desktop binary on the operator's own Windows PC and returns a zip.
 * They have separate job stores, separate ids and separate status vocabularies,
 * and the one failure this screen exists to prevent is an operator reading a
 * dispatch as an engine crawl — or hunting for a Screaming Frog run in the
 * Crawl jobs table, where it will never appear.
 *
 * Unavailability is stated on the card rather than hiding it. A missing option
 * is indistinguishable from a feature that does not exist, and fixture mode is
 * exactly when someone needs to be told the engine is not answering.
 *
 * Each card carries two separate things: *starting* a crawl, and *entering* the
 * product. They were one control, and conflating them cost twice. Starting an
 * engine crawl needs a reachable engine, so in fixture mode that button is
 * correctly disabled — but with the rail now showing no product's tabs on this
 * screen, a disabled button was the only door, and there was none. It also
 * meant the only way to look at a crawl that already finished was to open the
 * new-crawl form and cancel it. "Open the engine" is neither: it is the door,
 * and it stays open whether or not anything can be crawled, because reading
 * stored results is not an engine operation.
 */
export function LaunchView({
  onEngineCrawl,
  onOpenEngine,
  onScreamingFrog,
  canStartEngineCrawl,
  canDispatchScreamingFrog,
}: Props): JSX.Element {
  return (
    <div className="sfl-wrap">
      <div className="sfl-head">
        <h2>Start a crawl</h2>
      </div>
      <p className="sfl-sub">
        Two crawlers, run separately and tracked separately. Pick the one that
        answers the question you have.
      </p>

      <div className="sfl-cards">
        <section className="sfl-card" aria-labelledby="sfl-engine-title">
          <span className="sfl-where">Runs on the server</span>
          <h3 id="sfl-engine-title">Rankuno engine crawl</h3>
          <p>
            Our own crawler. Discovers the site, classifies every page, builds
            the hierarchy, and feeds the visualizer, the audit and the Search
            Console reports.
          </p>
          <ul className="sfl-points">
            <li>Starts immediately; runs in the background.</li>
            <li>
              Progress and results appear under <strong>Crawl jobs</strong>.
            </li>
            <li>Nothing needs to be installed.</li>
          </ul>

          {!canStartEngineCrawl && (
            <Alert
              type="info"
              showIcon
              message="Fixture mode — the engine is not reachable, so no crawl can be started. The bundled results are still browsable."
            />
          )}

          <div className="sfl-actions">
            <div className="sfl-actions-row">
              <Button
                type="primary"
                onClick={onEngineCrawl}
                disabled={!canStartEngineCrawl}
              >
                Start an engine crawl
              </Button>
              {/* Never disabled. Browsing results that already exist asks
                  nothing of the engine, and this is the only way in. */}
              <Button onClick={onOpenEngine} aria-describedby="sfl-engine-open-hint">
                Open the engine
              </Button>
            </div>
            <span className="sfl-actions-hint" id="sfl-engine-open-hint">
              Opens the visualizer, audit, Search Console reports and crawl jobs
              for results already stored. Starts nothing.
            </span>
          </div>
        </section>

        <section className="sfl-card" aria-labelledby="sfl-frog-title">
          <span className="sfl-where">Runs on your PC</span>
          <h3 id="sfl-frog-title">Screaming Frog crawl</h3>
          <p>
            Screaming Frog is a Windows desktop application and this dashboard
            runs in a Linux container, so the crawl runs on a machine you
            control — your PC, with the Rankuno worker daemon on it — and the
            finished export is uploaded back here as a zip.
          </p>
          <ul className="sfl-points">
            <li>Needs that machine registered, running and awake.</li>
            <li>You approve the exact URL, template and machine before it starts.</li>
            <li>
              These jobs are listed under <strong>Screaming Frog</strong>, not
              Crawl jobs.
            </li>
          </ul>

          {/* The door for this side lives on the notice rather than beside the
              button, because here the button *is* the door whenever it is
              enabled — a second control next to it would do the identical
              thing. Only when dispatch is impossible is a way in missing, and
              the Screaming Frog view states that case for itself (no engine to
              ask, no machine registered) rather than being unreachable. */}
          {!canDispatchScreamingFrog && (
            <Alert
              type="info"
              showIcon
              message="Fixture mode — there is no engine to ask which machines are registered, so nothing can be dispatched."
              action={
                <Button size="small" onClick={onScreamingFrog}>
                  Open Screaming Frog
                </Button>
              }
            />
          )}

          <div className="sfl-actions">
            <Button onClick={onScreamingFrog} disabled={!canDispatchScreamingFrog}>
              Set up a Screaming Frog crawl
            </Button>
          </div>
        </section>
      </div>

      <p className="sfl-foot">
        Neither replaces the other. The engine crawl is what the rest of this
        dashboard is built on; a Screaming Frog run is a second opinion you can
        cross-check against a finished engine crawl from the Crawl jobs table.
      </p>
    </div>
  );
}
