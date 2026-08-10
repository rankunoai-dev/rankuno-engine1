import { DisconnectOutlined, InboxOutlined } from "@ant-design/icons";
import { Empty, Typography } from "antd";
import { useCrawlStore } from "../../store/useCrawlStore";

/**
 * What both panes show when there is no tree to render.
 *
 * Shared rather than duplicated because the two panes sit side by side: any
 * difference between them reads as one of them being broken.
 *
 * A failed crawl clears the previous result deliberately — leaving the last
 * site's tree on screen under a new crawl's label is how someone ends up
 * reading one site's structure believing it is another's. But clearing it left
 * a generic "No crawl loaded" that says nothing about what happened or what to
 * do next, which is the gap this closes.
 */
export function CrawlEmptyState(): JSX.Element {
  const status = useCrawlStore((state) => state.status);
  const error = useCrawlStore((state) => state.error);
  const jobs = useCrawlStore((state) => state.jobs);

  if (status !== "failed") {
    return (
      <Empty
        image={<InboxOutlined style={{ fontSize: 44, color: "#334155" }} />}
        description={
          <Typography.Text type="secondary">
            {jobs.length > 0
              ? "Select a crawl from the dropdown above."
              : "No crawl loaded."}
          </Typography.Text>
        }
        style={{ marginTop: 80 }}
      />
    );
  }

  // The banner above already carries the full engine message. Repeating it here,
  // in both panes, would put three copies of the same paragraph on one screen.
  // This says only what the banner does not: what to do now.
  const refused = (error ?? "").toLowerCase().includes("refused");

  return (
    <Empty
      image={<DisconnectOutlined style={{ fontSize: 44, color: "#7f1d1d" }} />}
      description={
        <div style={{ maxWidth: 420, margin: "0 auto" }}>
          <Typography.Paragraph style={{ color: "#f87171", marginBottom: 6 }}>
            {refused
              ? "This crawl failed: the target server refused every request."
              : "This crawl failed and produced no result."}
          </Typography.Paragraph>
          {refused && (
            <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 6 }}>
              The site is blocking automated clients at its edge (a WAF or bot
              protection). No crawl setting will change that — access has to be
              arranged with the site owner.
            </Typography.Paragraph>
          )}
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            Select a previous successful crawl from the dropdown above.
          </Typography.Text>
        </div>
      }
      style={{ marginTop: 70 }}
    />
  );
}
