import { Empty, Tag } from "antd";
import { useMemo } from "react";
import { buildFindings, type Finding } from "../../lib/audit";
import { useCrawlStore } from "../../store/useCrawlStore";
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
              </header>
              <p className="au-detail">{finding.detail}</p>
              <p className="au-action">
                <strong>Action</strong> {finding.action}
              </p>
              {/* Evidence, not decoration. A finding a client cannot spot-check
                  is one they are entitled to disbelieve. */}
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
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
