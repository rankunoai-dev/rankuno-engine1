import {
  LANE_DESCRIPTIONS,
  LANE_LABELS,
  METHOD_LABELS,
  METHOD_ORDER,
  UNAVAILABLE_METHODS,
  type DashModel,
} from "../../lib/dashboardModel";
import { useDashboardStore } from "../../store/useDashboardStore";

const LANE_CLASS = ["p0", "p1", "p2", "p3", "po"];

interface Props {
  model: DashModel;
}

/**
 * Metadata for the focused node, and how it was classified.
 *
 * Every row is a field the engine actually produces. The reference design also
 * carried a per-page "WAF status" row, which it computed as `index % 7` — the
 * engine has no per-page block status, only a crawl-level `fetch_failures`
 * count, so that row is not reproduced here.
 */
export function NodeInspector({ model }: Props): JSX.Element {
  const focus = useDashboardStore((state) => state.focus);
  const node = focus === null ? null : model.nodes[focus];

  if (!node) {
    return <div className="inspect" />;
  }

  const profile = node.profile;

  return (
    <div className="inspect">
      <dl className="kv">
        <div>
          <dt>URL</dt>
          <dd>{node.url}</dd>
        </div>
        <div>
          <dt>Position</dt>
          <dd>
            <span className={`lvchip ${LANE_CLASS[node.lv]}`}>{LANE_LABELS[node.lv]}</span>
            &nbsp;{LANE_DESCRIPTIONS[node.lv]}
          </dd>
        </div>
        <div>
          <dt>Subtree</dt>
          <dd>
            {node.kids.length.toLocaleString()} children · {node.cnt.toLocaleString()} pages
          </dd>
        </div>

        {profile ? (
          <>
            <div>
              <dt>Page type</dt>
              <dd>
                {profile.primary_page_type} · {profile.hierarchy_level}
              </dd>
            </div>
            <div>
              <dt>Confidence</dt>
              <dd className={profile.final_confidence_score >= 0.85 ? "ok" : "warn"}>
                {(profile.final_confidence_score * 100).toFixed(0)}% ·{" "}
                {METHOD_LABELS[profile.consensus_method]}
              </dd>
            </div>
            <div>
              <dt>Internal links</dt>
              {/* Zero inbound links is a real SEO finding: nothing on the site
                  points here, so neither users nor crawlers reach it. */}
              <dd className={profile.inbound_internal_links_count === 0 ? "warn" : ""}>
                {profile.inbound_internal_links_count} in · {profile.outbound_internal_links_count}{" "}
                out
                {profile.inbound_internal_links_count === 0 && " · orphan"}
              </dd>
            </div>
            <div>
              <dt>Nav parent</dt>
              <dd>{profile.nav_parent_url ?? "— not in any menu section"}</dd>
            </div>
          </>
        ) : (
          <div>
            <dt>Node</dt>
            {/* A grouping node exists to hold children; it is not a page the
                crawl returned, and showing blank classification fields for it
                would read as a page that failed to classify. */}
            <dd>Structural grouping — not a crawled page</dd>
          </div>
        )}
      </dl>

      <div className="trace">
        <h5>Classifier cascade</h5>
        {profile ? (
          METHOD_ORDER.map((method) => {
            const resolved = profile.consensus_method === method;
            const unavailable = UNAVAILABLE_METHODS.has(method);
            return (
              <div
                key={method}
                className={`step${resolved ? " hit" : ""}${unavailable && !resolved ? " unavailable" : ""}`}
              >
                <b>{METHOD_LABELS[method].split(" · ")[0]}</b>
                <span className="res">
                  {resolved
                    ? "✓ resolved here"
                    : unavailable
                      ? "not implemented"
                      : "no match — cascaded"}
                </span>
              </div>
            );
          })
        ) : (
          <div className="step">
            <span className="res">No classification — structural node.</span>
          </div>
        )}

        {profile && profile.signals_evaluated.length > 0 && (
          <div style={{ marginTop: 8, fontSize: 10.5, color: "var(--faint)" }}>
            {profile.signals_evaluated.length} signal
            {profile.signals_evaluated.length === 1 ? "" : "s"} evaluated:{" "}
            {profile.signals_evaluated.map((signal) => signal.source).join(", ")}
          </div>
        )}
      </div>
    </div>
  );
}
