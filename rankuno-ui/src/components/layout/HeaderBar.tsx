import {
  DisconnectOutlined,
  ExperimentOutlined,
  RadarChartOutlined,
  WarningOutlined,
} from "@ant-design/icons";
import { Alert, Button, Select, Space, Statistic, Tag, Typography } from "antd";
import { useState } from "react";
import { useCrawlStore } from "../../store/useCrawlStore";
import { LiveCrawlModal } from "./LiveCrawlModal";

const STATUS_COLOR: Record<string, string> = {
  idle: "default",
  queued: "processing",
  running: "processing",
  succeeded: "success",
  partial: "warning",
  failed: "error",
};

/**
 * Crawl selector plus the headline numbers.
 *
 * Truncation and synthetic-data warnings are surfaced here rather than buried,
 * because both are ways a user can confidently misread the screen: a truncated
 * crawl looks like a complete site, and synthetic data looks like a real one.
 */
export function HeaderBar(): JSX.Element {
  const jobs = useCrawlStore((state) => state.jobs);
  const activeJobId = useCrawlStore((state) => state.activeJobId);
  const selectJob = useCrawlStore((state) => state.selectJob);
  const status = useCrawlStore((state) => state.status);
  const error = useCrawlStore((state) => state.error);
  const result = useCrawlStore((state) => state.result);
  const adapter = useCrawlStore((state) => state.adapter);
  const liveMessage = useCrawlStore((state) => state.liveMessage);
  const [crawlOpen, setCrawlOpen] = useState(false);

  // Presence of `startJob` is the capability check. `MockAdapter` reads files
  // generated ahead of time and genuinely cannot start a crawl, so offering the
  // button against it would be offering an action that cannot work.
  const canStartCrawl = adapter?.startJob !== undefined;
  const active = jobs.find((job) => job.id === activeJobId);
  const discovery = result?.discovery;
  const summary = result?.summary;
  const reserveExhausted =
    discovery !== undefined &&
    discovery.dom_reserve > 0 &&
    discovery.dom_reserve_used >= discovery.dom_reserve;

  // A crawl that fetched no page still produces classifications — Layer 0 reads
  // the URL string and is confident about it. Without this banner those look
  // exactly like classifications drawn from real page content.
  const noPagesFetched = discovery !== undefined && discovery.pages_fetched === 0;

  return (
    <div style={{ borderBottom: "1px solid #1e293b", background: "#0a0d14" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 20,
          padding: "10px 18px",
          flexWrap: "wrap",
        }}
      >
        <Typography.Title level={5} style={{ margin: 0, whiteSpace: "nowrap" }}>
          <span style={{ color: "#00f2fe" }}>Rankuno</span>{" "}
          <span style={{ color: "#64748b", fontWeight: 400 }}>Site Architecture</span>
        </Typography.Title>

        <Select
          style={{ minWidth: 300 }}
          value={activeJobId ?? undefined}
          onChange={selectJob}
          placeholder="Select a crawl"
          options={jobs.map((job) => ({
            value: job.id,
            label: (
              <Space size={6}>
                {job.synthetic && <ExperimentOutlined style={{ color: "#a855f7" }} />}
                <span>{job.label}</span>
              </Space>
            ),
          }))}
        />

        {canStartCrawl && (
          <Button
            type="primary"
            icon={<RadarChartOutlined />}
            loading={status === "running" || status === "queued"}
            onClick={() => setCrawlOpen(true)}
          >
            New crawl
          </Button>
        )}

        <Tag color={STATUS_COLOR[status] ?? "default"}>{status.toUpperCase()}</Tag>

        {liveMessage && (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {liveMessage}
          </Typography.Text>
        )}

        {summary && discovery && (
          <Space size={26}>
            <Statistic
              title="Pages"
              value={summary.pages_classified}
              valueStyle={{ fontSize: 16 }}
            />
            <Statistic
              title="Orphans"
              value={summary.orphan_pages}
              valueStyle={{ fontSize: 16, color: summary.orphan_pages ? "#f59e0b" : undefined }}
            />
            <Statistic
              title="Sitemap-omitted"
              value={discovery.dom_only}
              valueStyle={{ fontSize: 16 }}
            />
            <Statistic
              title="Unclassified"
              value={summary.unknown_pages}
              valueStyle={{ fontSize: 16, color: summary.unknown_pages ? "#f87171" : undefined }}
            />
            <Statistic
              title="Low confidence"
              value={summary.low_confidence_pages}
              valueStyle={{ fontSize: 16 }}
            />
          </Space>
        )}
      </div>

      {error && <Alert type="error" banner showIcon message={error} />}

      {active?.synthetic && (
        <Alert
          type="warning"
          banner
          showIcon
          icon={<ExperimentOutlined />}
          message="Synthetic dataset — generated for performance testing. Not crawl output, and not evidence about the engine."
        />
      )}

      {noPagesFetched && (
        <Alert
          type="error"
          banner
          showIcon
          icon={<DisconnectOutlined />}
          message={
            discovery.fetch_failures > 0
              ? `0 pages fetched over the network — ${discovery.fetch_failures} requests were refused by the server. Classifications rest on URL string patterns alone and are not evidence about this site.`
              : "0 pages fetched over the network. Classifications rest on URL string patterns alone and are not evidence about this site."
          }
        />
      )}

      {discovery?.truncated && (
        <Alert
          type="warning"
          banner
          showIcon
          icon={<WarningOutlined />}
          message={
            reserveExhausted
              ? `Crawl truncated, and the DOM reserve was exhausted (${discovery.dom_reserve_used}/${discovery.dom_reserve}). Pages absent from the sitemap are still being dropped — raise the reserve or the page ceiling.`
              : "Crawl stopped at its page ceiling. This is a partial view of the site, not the whole of it."
          }
        />
      )}

      <LiveCrawlModal open={crawlOpen} onClose={() => setCrawlOpen(false)} />
    </div>
  );
}
