import type { PageClassificationOutput } from "../../types/schema";
import { OTHERS_LANE, LEVEL_BADGE, type DashModel } from "../../lib/dashboardModel";
import "./report.css";

/**
 * Deepest tree level printed.
 *
 * A site architecture report is about *sections*, and this is where that
 * becomes a rule rather than an aspiration. Printed rows are roots, their
 * categories, and the sections inside those; individual leaf pages are left to
 * the interactive tree, where they can be searched, and to CSV, where they can
 * be sorted.
 *
 * Depth alone does not express this and measuring proved it. On kinsta.com the
 * first three levels hold 6,026 nodes — 3,456 of them individual pages, because
 * a page whose breadcrumb reads `Blog` lands at depth 1 with nothing beneath
 * it. Cutting on depth alone would have printed **134 pages**, worse than the
 * 70 it was meant to fix; the old row cap was all that hid this. A node earns a
 * row by *holding* something, not by sitting high in the tree.
 *
 * The alternative it replaces was a flat count: the first 3,000 nodes in tree
 * order. On a 29,248-node kinsta.com crawl that printed 70 A4 pages while
 * omitting 90% of the site, and the 10% it kept was chosen by traversal order
 * rather than by meaning — every section under `Contact` survived and nothing
 * under `Resources` did. It also broke printing outright: Microsoft Print to
 * PDF spools the whole document before writing it, and the Windows spooler
 * aborts a job that size with "Printing failed. Please check your printer".
 */
export const REPORT_MAX_DEPTH = 2;

/**
 * Hard ceiling on printed rows, kept as a backstop rather than a policy.
 *
 * Depth is what decides what belongs in the report; this only stops a
 * pathological site — one with tens of thousands of top-level sections — from
 * producing an unprintable document anyway.
 */
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
  const rows = flatten(model, REPORT_ROW_LIMIT, REPORT_MAX_DEPTH);
  const sections = countSections(model, REPORT_MAX_DEPTH);
  // Deliberately two numbers, not one. Leaves omitted *by design* and rows
  // dropped because the report hit its ceiling are different facts, and
  // collapsing them into "26,248 omitted" is what made the old notice read as
  // an apology for a broken report rather than a statement of scope.
  const deeper = model.nodes.length - sections;
  const truncated = sections - rows.length;

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
            {/* A finding about the client's site, not about the crawl: a
                segment repeating inside one path. */}
            <th>Repeating-path URLs skipped</th>
            <td>{count(discovery.traps_skipped)}</td>
          </tr>
          <tr>
            {/* Counted apart because the client's fix is different and much
                smaller: one template emitting an href with no leading slash
                gives a single page an address under every parent on the site.
                On one crawl this was 36% of everything discovered. */}
            <th>Template-loop URLs skipped</th>
            <td>{count(discovery.loop_urls_skipped)}</td>
          </tr>
          <tr>
            {/* Also a finding about the client's HTML rather than the crawl:
                an unclosed anchor or a smart-quoted attribute makes the parser
                read prose as a link. These were never pages. */}
            <th>Malformed links skipped</th>
            <td>{count(discovery.malformed_skipped)}</td>
            <th />
            <td />
          </tr>
          <tr>
            {/* Counted from the tree this report is printing, not from
                `nav_coverage`.

                This began as a workaround: `nav_coverage` counted the header
                menu alone and knew nothing about breadcrumbs, so once pages
                began being placed by their own trail the two diverged — 5,834
                in OTHERS on gep.com against 1,210 in the tree below. Cycle 0022
                fixed the metric at source, so the two now agree on a fresh
                crawl.

                Still counted from the tree, for two reasons that outlive the
                bug: a result stored before 0022 carries the old menu-only
                numbers and would print them, and this table is a description of
                the tree beside it — deriving it from anything else reintroduces
                the possibility of a headline contradicting the rows under it. */}
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
      {/* Scope, not an apology. This is the whole architecture down to section
          level; what is missing is missing on purpose and recoverable. */}
      <p className="rep-note">
        Every section on the site, {REPORT_MAX_DEPTH + 1} levels deep —{" "}
        {rows.length.toLocaleString()} of {model.nodes.length.toLocaleString()} nodes.
        {deeper > 0 && (
          <>
            {" "}
            The {deeper.toLocaleString()} pages and deeper sub-sections inside them are
            omitted for print clarity; browse them in the interactive tree, or export
            the full URL list to CSV.
          </>
        )}
      </p>
      {truncated > 0 && (
        <p className="rep-warn">
          This site has more sections than one report can hold —{" "}
          {truncated.toLocaleString()} were dropped at the {REPORT_ROW_LIMIT.toLocaleString()}
          -row ceiling. The structure below is incomplete.
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
function flatten(
  model: DashModel,
  limit: number,
  maxDepth: number,
): Array<{ index: number; depth: number }> {
  const rows: Array<{ index: number; depth: number }> = [];
  const stack: Array<{ index: number; depth: number }> = [];
  for (let k = model.roots.length - 1; k >= 0; k -= 1) {
    stack.push({ index: model.roots[k]!, depth: 0 });
  }

  while (stack.length > 0 && rows.length < limit) {
    const row = stack.pop()!;
    rows.push(row);
    const node = model.nodes[row.index];
    // Children are not pushed past the cut, so the walk stops descending rather
    // than walking the whole tree and discarding most of it. On kinsta.com that
    // is 29,248 nodes visited against roughly 300 kept.
    if (!node || row.depth >= maxDepth) continue;
    for (let k = node.kids.length - 1; k >= 0; k -= 1) {
      const kid = model.nodes[node.kids[k]!];
      // A childless node below the top level is an individual page, and this
      // report is about sections. Roots are kept whatever they hold: a
      // top-level tab pointing at one page is still part of the architecture.
      if (kid && kid.kids.length === 0) continue;
      stack.push({ index: node.kids[k]!, depth: row.depth + 1 });
    }
  }
  return rows;
}

/** Sections the report would print with no row ceiling, for the omission notice. */
function countSections(model: DashModel, maxDepth: number): number {
  let total = 0;
  const stack: Array<{ index: number; depth: number }> = model.roots.map((index) => ({
    index,
    depth: 0,
  }));
  while (stack.length > 0) {
    const row = stack.pop()!;
    total += 1;
    const node = model.nodes[row.index];
    if (!node || row.depth >= maxDepth) continue;
    for (const kid of node.kids) {
      if (model.nodes[kid]?.kids.length) stack.push({ index: kid, depth: row.depth + 1 });
    }
  }
  return total;
}
