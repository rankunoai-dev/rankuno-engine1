import { Alert, Button } from "antd";
import "./screaming-frog.css";

interface Props {
  /** Opens the existing engine crawl form (`LiveCrawlModal`). */
  onEngineCrawl: () => void;
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
 */
export function LaunchView({
  onEngineCrawl,
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
            <Button
              type="primary"
              onClick={onEngineCrawl}
              disabled={!canStartEngineCrawl}
            >
              Start an engine crawl
            </Button>
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

          {!canDispatchScreamingFrog && (
            <Alert
              type="info"
              showIcon
              message="Fixture mode — there is no engine to ask which machines are registered, so nothing can be dispatched."
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
