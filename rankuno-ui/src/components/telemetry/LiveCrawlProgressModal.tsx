import { Modal, Progress, Tag, Typography } from "antd";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useCrawlStore } from "../../store/useCrawlStore";
import "./telemetry.css";

/**
 * Live progress for a running crawl.
 *
 * Every number here comes from the engine's progress sink. The one thing this
 * component computes itself is elapsed time, because that is a property of the
 * browser session rather than of the crawl.
 *
 * Deliberately not dismissible while running: closing it would leave a crawl
 * consuming one of three concurrency slots with no indication anywhere that it
 * is still going.
 */
export function LiveCrawlProgressModal(): JSX.Element {
  const status = useCrawlStore((state) => state.status);
  const telemetry = useCrawlStore((state) => state.telemetry);
  const message = useCrawlStore((state) => state.liveMessage);
  const startedAt = useCrawlStore((state) => state.startedAt);

  const running = status === "running" || status === "queued";
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!running || startedAt === null) return;
    const timer = window.setInterval(
      () => setElapsed(Math.floor((Date.now() - startedAt) / 1000)),
      1_000,
    );
    return () => window.clearInterval(timer);
  }, [running, startedAt]);

  const completed = telemetry?.completed ?? 0;
  const discovered = telemetry?.discovered ?? 0;
  const percent = discovered > 0 ? Math.min(100, Math.round((completed / discovered) * 100)) : 0;

  return (
    <Modal
      open={running}
      title="Crawling"
      footer={null}
      closable={false}
      maskClosable={false}
      width={620}
    >
      <div className="tel-head">
        <Tag color="processing">{status.toUpperCase()}</Tag>
        <span className="tel-clock">{formatClock(elapsed)}</span>
        {telemetry && telemetry.rate_per_sec > 0 && (
          <span className="tel-rate">{telemetry.rate_per_sec.toFixed(1)} pages/sec</span>
        )}
      </div>

      <Progress
        percent={percent}
        status="active"
        strokeColor={{ "0%": "#00f2fe", "100%": "#4facfe" }}
        format={() =>
          discovered > 0 ? `${completed.toLocaleString()} / ${discovered.toLocaleString()}` : "…"
        }
      />

      <div className="tel-eta">
        {/* The engine withholds an ETA until a rate means something. Rendering
            "0 sec remaining" during that window would be worse than saying the
            estimate is not ready. */}
        {telemetry?.eta_seconds != null
          ? `~ ${formatRemaining(telemetry.eta_seconds)} remaining`
          : discovered > 0
            ? "Estimating…"
            : "Discovering URLs…"}
      </div>

      <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 8 }}>
        {message ?? "Crawling at polite per-host request rates."}
      </Typography.Paragraph>

      {/* Said plainly, because the ratio is not "percent complete". The
          denominator is every URL discovered, and most of those come from the
          sitemap and are never fetched — so a sitemap-heavy crawl finishes well
          short of 100% and that is the correct outcome, not a stall. */}
      {discovered > 0 && (
        <Typography.Paragraph type="secondary" style={{ fontSize: 11, marginBottom: 8 }}>
          Pages <em>fetched</em> against URLs <em>discovered</em>. Sitemap URLs
          count toward the total but are not fetched, so a sitemap-heavy crawl
          completes below 100%.
        </Typography.Paragraph>
      )}

      <UrlTicker urls={telemetry?.recent_items ?? []} />

      <Typography.Text type="secondary" style={{ fontSize: 11 }}>
        {/* Stated because the ticker looks like a complete log and is not. */}
        Showing the last {telemetry?.recent_items.length ?? 0} of{" "}
        {completed.toLocaleString()} fetched — the stream is capped so polling
        stays cheap on large crawls.
      </Typography.Text>
    </Modal>
  );
}

/**
 * The most recently fetched URLs, newest at the bottom.
 *
 * Auto-scrolls only when the user is already at the bottom. Yanking the view
 * down while someone is reading an earlier line makes the panel unusable.
 */
function UrlTicker({ urls }: { urls: readonly string[] }): JSX.Element {
  const box = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);

  useLayoutEffect(() => {
    const element = box.current;
    if (element && pinned.current) element.scrollTop = element.scrollHeight;
  }, [urls]);

  return (
    <div
      className="tel-stream"
      ref={box}
      onScroll={(event) => {
        const element = event.currentTarget;
        pinned.current =
          element.scrollHeight - element.scrollTop - element.clientHeight < 24;
      }}
    >
      {urls.length === 0 ? (
        <div className="tel-line tel-idle">waiting for the first page…</div>
      ) : (
        urls.map((url, index) => (
          <div
            key={`${url}-${index}`}
            className={`tel-line${index === urls.length - 1 ? " tel-newest" : ""}`}
          >
            <span className="tel-dot" />
            {url}
          </div>
        ))
      )}
    </div>
  );
}

/** `mm:ss`, or `h:mm:ss` past an hour. */
function formatClock(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = seconds % 60;
  const mm = String(minutes).padStart(2, "0");
  const ss = String(rest).padStart(2, "0");
  return hours > 0 ? `${hours}:${mm}:${ss}` : `${mm}:${ss}`;
}

/**
 * A remaining-time phrase.
 *
 * Rounded coarsely on purpose: the estimate is not accurate to the second, and
 * a display that counts down precisely implies a confidence it does not have.
 */
function formatRemaining(seconds: number): string {
  if (seconds < 60) return `${Math.max(1, Math.round(seconds))} sec`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  if (minutes < 60) return rest > 0 ? `${minutes} min ${rest} sec` : `${minutes} min`;
  return `${Math.floor(minutes / 60)} hr ${minutes % 60} min`;
}
