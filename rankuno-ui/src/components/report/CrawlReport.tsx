import type { PageClassificationOutput } from "../../types/schema";
import { OTHERS_LANE, LEVEL_BADGE, type DashModel } from "../../lib/dashboardModel";
import "./report.css";

/** Rows included in the printed tree. */
export const REPORT_ROW_LIMIT = 3_000;

/**
 * Format a count that a saved result may predate.
 *
 * Job results are persisted to disk and re-read months later, so a stored
 * result can be missing a field the current schema declares — the types
 * describe what the *engine* emits today, not what is on disk. Calling
 * `.toLocaleString()` on the resulting `undefined` throws, and a throw in
 * render blanks the whole dashboard. `media_skipped` did exactly that the day
 * it was added.
 */
function count(value: number | undefined): string {
  return value === undefined ? "—" : value.toLocaleString();
}

interface Props {
  model: DashModel;
  result: PageClassificationOutput;
  generatedAt: Date;
}

/**
 * The printable report.
 *
 * Rendered off-screen and revealed only by `@media print`, because the on-screen
 * tree is virtualized: printing what is visible would produce the ~25 rows that
 * happen to be mounted. A report has to build its own full list.
 *
 * Capped at `REPORT_ROW_LIMIT` rows, and the cap is stated on the page rather
 * than applied silently — a truncated report that looks complete is worse than
 * one that says where it stopped.
 */
export function CrawlReport({ model, result, generatedAt }: Props): JSX.Element {
  const { summary, discovery, nav_coverage: coverage } = result;
  // Counted over *pages*, not tree nodes. `model.nodes` includes the section
  // nodes the tree needs to hold its children — 14,500 nodes for 10,816 pages on
  // highradius — so subtracting from it produced "13,871 placed (96%)" against
  // 10,816 classified. A headline larger than the total it is a share of.
  const inOthers = model.nodes.filter((n) => n.profile && n.lv === OTHERS_LANE).length;
  const placed = model.nodes.filter((n) => n.profile).length - inOthers;
  const rows = flatten(model, REPORT_ROW_LIMIT);
  const omitted = model.nodes.length - rows.length;

  return (
    <div className="rk-report" aria-hidden="true">
      <header className="rep-head">
        <h1>Site architecture report</h1>
        <p className="rep-sub">
          {result.base_url} · generated {generatedAt.toLocaleString()}
        </p>
      </header>

      {/* Every caveat the screen carries is repeated here. A PDF outlives the
          session it came from and will be read by someone who never saw the
          banners. */}
      {discovery.stopped_reason && (
        <p className="rep-warn">
          Crawl stopped early — {discovery.stopped_reason}. The pages below are
          real, but this is not the whole site and how much is missing is
          unknown.
        </p>
      )}
      {discovery.truncated && (
        <p className="rep-warn">
          Crawl stopped at its page ceiling of {count(discovery.total_urls)} URLs.
          This is a partial view of the site.
        </p>
      )}
      {discovery.pages_fetched === 0 && (
        <p className="rep-warn">
          No page was fetched over the network. Classifications below rest on URL
          string patterns alone.
        </p>
      )}

      <table className="rep-kpi">
        <tbody>
          <tr>
            <th>URLs classified</th>
            <td>{count(summary.pages_classified)}</td>
            <th>Discovered</th>
            <td>{count(discovery.total_urls)}</td>
          </tr>
          <tr>
            <th>Pages fetched</th>
            <td>{count(discovery.pages_fetched)}</td>
            <th>Refused</th>
            <td>{count(discovery.fetch_failures)}</td>
          </tr>
          <tr>
            {/* Not a failure. An image sitemap listing 300 uploads is normal;
                what is misleading is a report that counts them as pages. */}
            <th>Media skipped</th>
            <td>{count(discovery.media_skipped)}</td>
            {/* A finding about the client's site, not about the crawl. */}
            <th>Loop URLs skipped</th>
            <td>{count(discovery.traps_skipped)}</td>
          </tr>
          <tr>
            {/* Counted from the tree this report is printing, not from
                `nav_coverage`. That field is computed from the header menu
                alone and knows nothing about breadcrumbs, so once pages began
                being placed by their own trail the two diverged: it reported
                5,834 in OTHERS on gep.com while the tree below held 1,210. A
                headline number contradicting the table under it is worse than
                no headline number. */}
            <th>Placed in a section</th>
            <td>
              {placed.toLocaleString()}
              {placed + inOthers > 0 &&
                ` (${Math.round((placed / (placed + inOthers)) * 100)}%)`}
            </td>
            <th>OTHERS</th>
            <td>{inOthers.toLocaleString()}</td>
          </tr>
          <tr>
            {/* Kept, but named for what it measures. The header menu is one
                source of placement and no longer the only one. */}
            <th>In header menu</th>
            <td>{count(coverage.exact_matches + coverage.inherited_matches)}</td>
            <th>Menu entries</th>
            <td>{count(coverage.nav_entries)}</td>
          </tr>
          <tr>
            <th>Orphans</th>
            <td>{count(summary.orphan_pages)}</td>
            <th>Unclassified</th>
            <td>{count(summary.unknown_pages)}</td>
          </tr>
          <tr>
            <th>LLM spend</th>
            <td>${summary.llm_spend_usd.toFixed(2)}</td>
            <th>Escalated</th>
            <td>
              {count(summary.escalated_to_llm)} (
              {(summary.escalation_rate * 100).toFixed(2)}%)
            </td>
          </tr>
        </tbody>
      </table>

      <h2>Sections</h2>
      <p className="rep-note">
        {inOthers > 0 ? (
          <>
            <strong>OTHERS</strong> holds {inOthers.toLocaleString()} pages that neither
            the header menu nor a page's own breadcrumb places in a section.
          </>
        ) : (
          "Every page sits under a navigation section."
        )}
      </p>

      <h2>Structure</h2>
      {omitted > 0 && (
        <p className="rep-warn">
          Showing the first {rows.length.toLocaleString()} of{" "}
          {model.nodes.length.toLocaleString()} nodes; {omitted.toLocaleString()} omitted
          to keep this report printable.
        </p>
      )}

      <table className="rep-tree">
        <thead>
          <tr>
            <th>Path</th>
            <th>Level</th>
            <th>Depth</th>
            <th>Type</th>
            <th>Conf.</th>
            <th>In</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ index, depth }) => {
            const node = model.nodes[index]!;
            const profile = node.profile;
            return (
              <tr key={index}>
                <td style={{ paddingLeft: 4 + depth * 12 }}>
                  {node.label}
                  {!profile && <span className="rep-dim"> · not crawled</span>}
                </td>
                {/* The engine's classification, matching the on-screen tree.
                    Showing the lane here instead made the two disagree: the
                    same node read `L1` in the PDF and `L3` on screen. */}
                <td>{profile ? LEVEL_BADGE[profile.hierarchy_level].label : "—"}</td>
                {/* Level is a *role* — hub or leaf — and says nothing about how
                    deep a page sits. On gep.com 4,386 pages are leaves at depths
                    4 to 7, and reading level alone made that look like a tree
                    three levels tall. The engine records depth to 15; this is
                    where it becomes visible. */}
                <td>{profile ? profile.depth_from_l0 : "—"}</td>
                <td>{profile?.primary_page_type ?? "—"}</td>
                <td>
                  {profile ? `${Math.round(profile.final_confidence_score * 100)}%` : "—"}
                </td>
                <td className={profile?.inbound_internal_links_count === 0 ? "rep-flag" : ""}>
                  {profile?.inbound_internal_links_count ?? "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <footer className="rep-foot">
        Rankuno AI Engine · {result.base_url} ·{" "}
        {model.laneCounts[OTHERS_LANE]?.toLocaleString() ?? 0} nodes in OTHERS
      </footer>
    </div>
  );
}

/** Depth-first order, capped. Iterative for the same reason the tree build is. */
function flatten(model: DashModel, limit: number): Array<{ index: number; depth: number }> {
  const rows: Array<{ index: number; depth: number }> = [];
  const stack: Array<{ index: number; depth: number }> = [];
  for (let k = model.roots.length - 1; k >= 0; k -= 1) {
    stack.push({ index: model.roots[k]!, depth: 0 });
  }

  while (stack.length > 0 && rows.length < limit) {
    const row = stack.pop()!;
    rows.push(row);
    const node = model.nodes[row.index];
    if (!node) continue;
    for (let k = node.kids.length - 1; k >= 0; k -= 1) {
      stack.push({ index: node.kids[k]!, depth: row.depth + 1 });
    }
  }
  return rows;
}
