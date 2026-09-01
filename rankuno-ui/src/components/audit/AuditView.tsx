import { Empty, Tag } from "antd";
import { useMemo, useState } from "react";
import { buildFindings, type Finding } from "../../lib/audit";
import { downloadCsv, hostSlug, toCsv } from "../../lib/csv";
import { useCrawlStore } from "../../store/useCrawlStore";
import { DuplicateTable } from "./DuplicateTable";
import { OrphanTable } from "./OrphanTable";
import "./audit.css";

const SEVERITY_COLOUR: Record<Finding["severity"], string> = {
  high: "error",
  medium: "warning",
  low: "default",
};

/**
 * Site defects found in the loaded crawl, as findings rather than a tree.
 *
 * Separate from the visualizer on purpose. The tree answers "where does this
 * page sit?" — one answer per page, because a node has one parent. An audit
 * answers "what is wrong here?", and a page can be an orphan *and* sit in a
 * mis-signposted URL silo *and* be one of five paginated variants. Forcing
 * those into the tree is what made OTHERS feel like a dumping ground.
 *
 * Every finding carries a count, evidence and an action. A count with no action
 * is trivia, and an action with no evidence is an assertion a client can refuse.
 */
export function AuditView(): JSX.Element {
  const result = useCrawlStore((state) => state.result);
  const findings = useMemo(() => (result ? buildFindings(result) : []), [result]);
  // Collapsed by default. The audit is read top to bottom as a summary, and a
  // 2,000-row table opened unasked buries the findings below it.
  const [openId, setOpenId] = useState<string | null>(null);

  if (!result) {
    return (
      <div className="au-wrap">
        <Empty description="No crawl loaded. Select one from the header, or start a new crawl." />
      </div>
    );
  }

  return (
    <div className="au-wrap">
      <div className="au-head">
        <h2>Audit</h2>
        <span className="au-sub">
          {result.base_url} · {result.pages.length.toLocaleString()} pages ·{" "}
          {result.discovery.pages_fetched.toLocaleString()} fetched
        </span>
      </div>

      {result.discovery.pages_fetched === 0 && (
        <div className="au-caveat">
          No page was fetched over the network on this crawl. Everything below rests on
          URL patterns alone — re-crawl before sending any of it to a client.
        </div>
      )}

      {findings.length === 0 ? (
        <Empty description="No findings. Either the site is unusually clean, or the crawl was too small to judge." />
      ) : (
        <div className="au-list">
          {findings.map((finding) => (
            <section className="au-card" key={finding.id}>
              <header>
                <Tag color={SEVERITY_COLOUR[finding.severity]}>{finding.severity}</Tag>
                <h3>{finding.title}</h3>
                {/* Only findings that carry a worklist get a control. A button
                    that expands to nothing is worse than no button. */}
                {(finding.pages || finding.groups) && (
                  <div className="au-actions">
                    {/* On the card, not only inside the drill-in. The export was
                        reachable solely by opening the table first, which meant
                        the artefact most of these cards exist to produce was two
                        clicks behind a control nobody could see. */}
                    <button
                      type="button"
                      className="rk-btn rk-btn-primary"
                      onClick={() => exportFinding(finding, result.base_url)}
                    >
                      Download CSV
                    </button>
                    <button
                      type="button"
                      className="rk-btn"
                      aria-expanded={openId === finding.id}
                      onClick={() => setOpenId(openId === finding.id ? null : finding.id)}
                    >
                      {openId === finding.id
                        ? "Hide list"
                        : // "sets" for a grouped finding: its count is clusters,
                          // not URLs, and "See all 262" beside a title reading
                          // "1,920 URLs" invites the reader to pair the wrong two
                          // numbers.
                          `See all ${finding.count.toLocaleString()}${finding.groups ? " sets" : ""}`}
                    </button>
                  </div>
                )}
              </header>
              <p className="au-detail">{finding.detail}</p>
              <p className="au-action">
                <strong>Action</strong> {finding.action}
              </p>
              {/* Evidence, not decoration. A finding a client cannot spot-check
                  is one they are entitled to disbelieve. */}
              {openId === finding.id && finding.groups ? (
                <DuplicateTable groups={finding.groups} baseUrl={result.base_url} />
              ) : openId === finding.id && finding.pages ? (
                <OrphanTable pages={finding.pages} baseUrl={result.base_url} />
              ) : (
                <ul className="au-examples">
                  {finding.examples.map((url) => (
                    <li key={url}>{url}</li>
                  ))}
                  {finding.count > finding.examples.length && (
                    <li className="au-more">
                      + {(finding.count - finding.examples.length).toLocaleString()} more
                    </li>
                  )}
                </ul>
              )}
            </section>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Write one finding's worklist to a CSV.
 *
 * Deliberately generic rather than per-finding. `OrphanTable` and
 * `DuplicateTable` each carry an export tuned to their columns, and those stay —
 * they know about orphan kinds and cluster survivors. This one answers the
 * blunter question an analyst asks first: *give me the URLs behind this number*,
 * without opening anything.
 *
 * A grouped finding keeps its clusters adjacent and numbered, because the set a
 * URL belongs to is the whole point of that finding and a flat list destroys it.
 */
function exportFinding(finding: Finding, baseUrl: string): void {
  const rows: (string | number | null)[][] = finding.groups
    ? finding.groups.flatMap((group, index) =>
        group.map((page) => [index + 1, page.url, page.primary_page_type, page.hierarchy_level]),
      )
    : (finding.pages ?? []).map((page) => [
        null,
        page.url,
        page.primary_page_type,
        page.hierarchy_level,
      ]);

  const csv = toCsv(["set", "url", "page_type", "hierarchy_level"], rows);
  downloadCsv(`${hostSlug(baseUrl)}-${finding.id.replace(/[^a-z0-9]+/gi, "-")}.csv`, csv);
}
