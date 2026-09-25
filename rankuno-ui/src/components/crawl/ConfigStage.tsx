/**
 * Stage 3: Configuration Selector.
 *
 * Choose crawl speed preset (Polite/Aggressive/Custom) or set custom rate & concurrency.
 * Shows warning if crawl time would exceed configured threshold.
 */

import { Alert, Form, InputNumber, Segmented, Space, Typography } from "antd";
import { useMemo } from "react";
import { CRAWL_SPEEDS } from "../../adapters/adapterInterface";
import type { CrawlConfigPreset } from "../../types/crawlWizard";
import {
  validateConcurrency,
  validateRate,
  estimateCrawlSeconds,
  formatCrawlTimeEstimate,
} from "../../lib/validation";

interface Props {
  configPreset: CrawlConfigPreset;
  customRate?: number;
  customConcurrency?: number;
  maxPages?: number | null;
  onPresetChange: (preset: CrawlConfigPreset) => void;
  onCustomRateChange: (rate: number | null) => void;
  onCustomConcurrencyChange: (concurrency: number | null) => void;
}

const CRAWL_TIME_WARNING_THRESHOLD_SECONDS = 6 * 3600; // 6 hours

/**
 * Stage 3: Configuration Selector.
 *
 * Allows choosing from presets (Polite/Aggressive) or defining custom rate/concurrency.
 */
export function ConfigStage({
  configPreset,
  customRate,
  customConcurrency,
  maxPages,
  onPresetChange,
  onCustomRateChange,
  onCustomConcurrencyChange,
}: Props): JSX.Element {
  // Get current rate and concurrency based on preset
  const currentPreset = useMemo(() => {
    if (configPreset === "custom") return null;
    return CRAWL_SPEEDS.find((s) => s.key === configPreset);
  }, [configPreset]);

  const currentRate = configPreset === "custom" ? customRate : currentPreset?.rate_limit_rps;
  const currentConcurrency = configPreset === "custom" ? customConcurrency : currentPreset?.concurrency;

  // Estimate crawl time
  const estimatedSeconds = useMemo(() => {
    if (!currentRate || currentRate <= 0 || !maxPages) return null;
    return estimateCrawlSeconds(maxPages, currentRate);
  }, [currentRate, maxPages]);

  const shouldShowWarning =
    estimatedSeconds !== null && estimatedSeconds > CRAWL_TIME_WARNING_THRESHOLD_SECONDS;

  const rateError = configPreset === "custom" ? validateRate(customRate) : null;
  const concurrencyError = configPreset === "custom" ? validateConcurrency(customConcurrency) : null;

  return (
    <div style={{ paddingBottom: 16 }}>
      <Typography.Title level={4} style={{ marginBottom: 16 }}>
        Choose crawl speed
      </Typography.Title>

      <Segmented
        block
        value={configPreset}
        onChange={(value) => onPresetChange(value as CrawlConfigPreset)}
        options={[
          ...CRAWL_SPEEDS.map((option) => ({
            label: option.label,
            value: option.key,
          })),
          { label: "Custom", value: "custom" },
        ]}
        style={{ marginBottom: 16 }}
      />

      {configPreset !== "custom" && currentPreset && (
        <div style={{ padding: 12, background: "#fafafa", borderRadius: 4, marginBottom: 16 }}>
          <Typography.Paragraph style={{ fontSize: 12, margin: 0, marginBottom: 8 }}>
            <strong>{currentPreset.label}</strong>
          </Typography.Paragraph>
          <Typography.Paragraph type="secondary" style={{ fontSize: 12, margin: 0, marginBottom: 4 }}>
            {currentPreset.detail}
          </Typography.Paragraph>
          <div style={{ fontSize: 12, color: "#666" }}>
            <div>Rate: {currentPreset.rate_limit_rps} req/sec</div>
            <div>Concurrency: {currentPreset.concurrency}</div>
          </div>
        </div>
      )}

      {configPreset === "custom" && (
        <Form layout="vertical" style={{ marginBottom: 16 }}>
          <Form.Item
            label="Requests per second"
            validateStatus={rateError ? "error" : ""}
            help={rateError}
            required
          >
            <InputNumber
              value={customRate}
              onChange={onCustomRateChange}
              min={0.05}
              max={25}
              step={0.05}
              placeholder="1.0"
              style={{ width: "100%" }}
            />
          </Form.Item>

          <Form.Item
            label="Concurrency"
            validateStatus={concurrencyError ? "error" : ""}
            help={concurrencyError}
            required
          >
            <InputNumber
              value={customConcurrency}
              onChange={onCustomConcurrencyChange}
              min={1}
              max={200}
              placeholder="5"
              style={{ width: "100%" }}
            />
          </Form.Item>
        </Form>
      )}

      <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
        A site's robots.txt Crawl-delay always takes precedence: the engine will never exceed the
        rate the site requests, even if this setting is faster.
      </Typography.Paragraph>

      {shouldShowWarning && (
        <Alert
          type="warning"
          showIcon
          style={{ marginTop: 16 }}
          message="Long estimated crawl time"
          description={`At ${currentRate} req/sec, crawling ${maxPages?.toLocaleString()} pages would take roughly ${formatCrawlTimeEstimate(estimatedSeconds)}. This is a lower bound (single-host floor) and the actual time depends on your network and the target server's response time.`}
        />
      )}

      {configPreset === "turbo" && (
        <Alert
          type="warning"
          showIcon
          style={{ marginTop: 16 }}
          message="High crawl rate"
          description="25 requests per second is real server load. Use this only on sites you own or have explicit permission to crawl at this rate."
        />
      )}
    </div>
  );
}
