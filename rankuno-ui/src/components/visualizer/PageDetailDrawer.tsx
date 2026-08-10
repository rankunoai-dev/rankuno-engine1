import {
  Alert,
  Descriptions,
  Drawer,
  Empty,
  Progress,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { LEVEL_COLORS, LEVEL_LABELS, PAGE_TYPE_COLORS } from "../../constants/colors";
import { useCrawlStore, useSelectedProfile } from "../../store/useCrawlStore";
import type { SignalScore } from "../../types/schema";

/** Threshold below which the engine escalates to the paid LLM layer. */
const CONFIDENCE_THRESHOLD = 0.85;

/**
 * Evidence for one page.
 *
 * Deliberately leads with what is *wrong* — orphan status, low confidence,
 * missing signals — rather than presenting every classification as equally
 * certain. On real crawls 98% of pages fell below the confidence threshold, so
 * a drawer that renders them all identically would be actively misleading.
 */
export function PageDetailDrawer(): JSX.Element {
  const open = useCrawlStore((state) => state.drawerOpen);
  const close = useCrawlStore((state) => state.closeDrawer);
  const profile = useSelectedProfile();

  return (
    <Drawer
      open={open}
      onClose={close}
      width={560}
      title={profile ? "Page evidence" : "No page selected"}
      styles={{ body: { padding: 16 } }}
    >
      {!profile ? (
        <Empty description="Select a node to inspect its signals" />
      ) : (
        <Space direction="vertical" size={14} style={{ width: "100%" }}>
          <Typography.Link href={profile.url} target="_blank" rel="noopener noreferrer">
            {profile.url}
          </Typography.Link>

          {profile.inbound_internal_links_count === 0 && (
            <Alert
              type="warning"
              showIcon
              message="Orphan page"
              description="No internal link points here, so neither users nor crawlers reach it by navigation. A genuine SEO finding, not a crawl artefact."
            />
          )}

          {profile.final_confidence_score < CONFIDENCE_THRESHOLD && (
            <Alert
              type="info"
              showIcon
              message="Below the escalation threshold"
              description={`Confidence ${(profile.final_confidence_score * 100).toFixed(0)}% is under ${CONFIDENCE_THRESHOLD * 100}%. The engine would escalate this page to the governed LLM layer if one were wired in.`}
            />
          )}

          {profile.primary_page_type === "UNKNOWN" && (
            <Alert
              type="error"
              showIcon
              message="Unclassified"
              description="Phase 1 targets zero UNKNOWN pages, so this is a defect signal rather than a normal outcome."
            />
          )}

          <div>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              Consensus confidence
            </Typography.Text>
            <Progress
              percent={Math.round(profile.final_confidence_score * 100)}
              status={
                profile.final_confidence_score >= CONFIDENCE_THRESHOLD ? "success" : "normal"
              }
              strokeColor={
                profile.final_confidence_score >= CONFIDENCE_THRESHOLD ? "#10b981" : "#f59e0b"
              }
            />
          </div>

          <Descriptions size="small" column={1} bordered>
            <Descriptions.Item label="Hierarchy level">
              <Tag color={LEVEL_COLORS[profile.hierarchy_level]}>
                {LEVEL_LABELS[profile.hierarchy_level]} · {profile.hierarchy_level}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="Page type">
              <Tag color={PAGE_TYPE_COLORS[profile.primary_page_type]}>
                {profile.primary_page_type}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="Search intent">{profile.search_intent}</Descriptions.Item>
            <Descriptions.Item label="Conversion role">
              {profile.conversion_role}
            </Descriptions.Item>
            {/* Path depth, not click depth. Conflating them is the click-depth
                fallacy the engine exists to avoid. */}
            <Descriptions.Item label="Path depth">{profile.depth_from_l0}</Descriptions.Item>
            <Descriptions.Item label="Internal links">
              in {profile.inbound_internal_links_count} · out{" "}
              {profile.outbound_internal_links_count}
            </Descriptions.Item>
            <Descriptions.Item label="Settled by">
              {profile.consensus_method}
            </Descriptions.Item>
          </Descriptions>

          <div>
            <Typography.Text strong style={{ fontSize: 13 }}>
              Signals evaluated ({profile.signals_evaluated.length} of 6)
            </Typography.Text>
            <Typography.Paragraph type="secondary" style={{ fontSize: 11, marginTop: 4 }}>
              Only signals that had an opinion appear. An absent signal is not a
              low score — it means that evidence was unavailable for this page.
            </Typography.Paragraph>
            <Table<SignalScore>
              size="small"
              pagination={false}
              rowKey={(row) => row.source}
              dataSource={[...profile.signals_evaluated]}
              columns={[
                { title: "Source", dataIndex: "source", width: 170 },
                {
                  title: "Suggested",
                  render: (_, row) => (
                    <span style={{ fontSize: 11 }}>
                      {LEVEL_LABELS[row.suggested_level]} · {row.suggested_page_type}
                    </span>
                  ),
                },
                {
                  title: "Conf.",
                  dataIndex: "confidence",
                  width: 64,
                  render: (value: number) => `${(value * 100).toFixed(0)}%`,
                },
              ]}
            />
          </div>

          {profile.signals_evaluated.some((signal) => signal.notes) && (
            <div>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                Evidence notes
              </Typography.Text>
              {profile.signals_evaluated
                .filter((signal) => signal.notes)
                .map((signal) => (
                  <Typography.Paragraph
                    key={signal.source}
                    style={{ fontSize: 11, marginBottom: 4 }}
                  >
                    <Tag>{signal.source}</Tag> {signal.notes}
                  </Typography.Paragraph>
                ))}
            </div>
          )}
        </Space>
      )}
    </Drawer>
  );
}
