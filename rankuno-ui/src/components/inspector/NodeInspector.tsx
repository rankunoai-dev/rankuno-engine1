import {
  LANE_DESCRIPTIONS,
  LEVEL_BADGE,
  PATH_LANE_DESCRIPTIONS,
  LANE_LABELS,
  METHOD_LABELS,
  METHOD_ORDER,
  TRAIL_SOURCE_BADGE,
  TRAIL_SOURCE_REASON,
  UNAVAILABLE_METHODS,
  type DashModel,
} from "../../lib/dashboardModel";
import { useCrawlStore } from "../../store/useCrawlStore";
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
  // Whether the tree on screen came from a menu. When it did not, the lane
  // numbers are URL-path depth and must not be described as menu positions.
  const navGrouped = useCrawlStore(
    (state) => state.grouping === "navigation" && (state.result?.navigation?.roots.length ?? 0) > 0,
  );

  if (!node) {
    return <div className="inspect" />;
  }

  const profile = node.profile;
  // The trail as the engine settled it. Named `breadcrumb_path` for history —
  // it holds the menu path whenever the menu won, which is exactly why the
  // badge above it has to say which one this is.
  const trail = profile?.breadcrumb_path ?? [];

  return (
    <div className="inspect">
      <dl className="kv">
        <div>
          <dt>URL</dt>
          <dd>{node.url}</dd>
        </div>
        {/* Two separate facts, deliberately on two rows. "Position" is where
            the node sits in the tree currently on screen; "Classified" is what
            the engine decided the page is. Collapsing them into one chip is
            what made a flat site read as though every page were a top-level
            navigation tab. */}
        <div>
          <dt>Position</dt>
          <dd>
            <span className={`lvchip ${LANE_CLASS[node.lv]}`}>{LANE_LABELS[node.lv]}</span>
            &nbsp;{(navGrouped ? LANE_DESCRIPTIONS : PATH_LANE_DESCRIPTIONS)[node.lv]}
          </dd>
        </div>
        {profile && (
          <div>
            <dt>Classified</dt>
            <dd>
              <span className={`lvchip ${LANE_CLASS[LEVEL_BADGE[profile.hierarchy_level].lane]}`}>
                {LEVEL_BADGE[profile.hierarchy_level].label}
              </span>
              &nbsp;{profile.hierarchy_level}
              <span className="dim">
                &nbsp;· {profile.depth_from_l0} levels below the root
              </span>
            </dd>
          </div>
        )}
        {/* Deliberately above "Menu vs URL", and shown for grouping nodes too.
            The question a reader has on opening this drawer is "why is it
            here?", and until now the drawer answered "what is it?" and left the
            first question to be inferred from a trail whose origin the result no
            longer recorded. */}
        <div>
          <dt>Placed by</dt>
          <dd>
            {model.hasProvenance ? (
              <>
                <span className={`srcchip src-${node.src}`}>{TRAIL_SOURCE_BADGE[node.src]}</span>
                <div className="dim reason">{TRAIL_SOURCE_REASON[node.src]}</div>
              </>
            ) : (
              /* Not the same as "nothing placed it". This crawl predates the
                 field, so the engine never recorded an answer either way. */
              <div className="dim reason">
                This crawl was run before the engine recorded what placed each page. Re-crawl
                to see whether the header menu or a published breadcrumb put it here.
              </div>
            )}
            {trail.length > 0 && (
              <div className="trail">
                {trail.join("  ›  ")}
              </div>
            )}
          </dd>
        </div>
        {profile && (
          <div>
            <dt>Menu vs URL</dt>
            <dd>
              <div>{urlPath(profile.url)}</div>
              {siloMismatch(profile.url, profile.breadcrumb_path) ? (
                /* Worth surfacing, not hiding. HighRadius serves
                   `/software/speed-to-value/` from the Resources menu, and
                   1,113 pages sit under `/software/` with no `Software` tab at
                   all. Google infers a silo from the URL; a visitor is offered
                   a different one. That divergence is the finding. */
                <div className="warn">
                  URL silo <strong>/{firstSegment(profile.url)}/</strong> does not appear in
                  this page's menu path — search engines and visitors see different
                  structures.
                </div>
              ) : (
                <div className="dim">Menu path and URL structure agree.</div>
              )}
            </dd>
          </div>
        )}
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

/** Path only — the host is on every row and repeating it wastes the column. */
function urlPath(url: string): string {
  try {
    const { pathname, search } = new URL(url);
    return `${pathname}${search}`;
  } catch {
    return url;
  }
}

/** First path segment, which is the silo a search engine infers. */
function firstSegment(url: string): string {
  try {
    return new URL(url).pathname.split("/").filter(Boolean)[0] ?? "";
  } catch {
    return "";
  }
}

/**
 * Whether the URL's top-level silo is absent from the page's menu path.
 *
 * Compared loosely — segment against label, case- and separator-insensitive —
 * because the two are written by different people for different audiences:
 * `/order-to-cash/` against "Order To Cash". An exact match would report a
 * mismatch on almost every page and the signal would be worthless.
 *
 * A single-segment URL is never a mismatch: it has no silo to disagree with.
 */
function siloMismatch(url: string, trail: readonly string[]): boolean {
  const segment = firstSegment(url);
  if (!segment || trail.length === 0) return false;
  try {
    if (new URL(url).pathname.split("/").filter(Boolean).length < 2) return false;
  } catch {
    return false;
  }
  const flat = (text: string) => text.toLowerCase().replace(/[^a-z0-9]/g, "");
  const needle = flat(segment);
  return !trail.some((label) => flat(label).includes(needle) || needle.includes(flat(label)));
}
