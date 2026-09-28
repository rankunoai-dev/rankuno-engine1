import { ClockCircleOutlined, LoadingOutlined, WarningOutlined } from "@ant-design/icons";
import { Tooltip } from "antd";
import type { CrawlActivityView } from "../../adapters/adapterInterface";
import { useCrawlActivity } from "./useCrawlActivity";

type Tone = "idle" | "running" | "full";

function toneOf(activity: CrawlActivityView): Tone {
  // `rankuno_cap` comes from the server and is never assumed. A cap of 0 would
  // read as permanently full, so it is treated as "no limit reported".
  if (activity.rankuno_cap > 0 && activity.rankuno_active >= activity.rankuno_cap) return "full";
  return activity.rankuno_active + activity.sf_active > 0 ? "running" : "idle";
}

/**
 * How many crawls are running for the whole organisation, on any device.
 *
 * Distinct from `BackgroundPill`, which reports this browser session's own
 * crawls with progress: this is a server-wide count, so an operator can see
 * that the engine is busy before starting another crawl that would have to
 * wait, and can see a colleague's or another machine's Screaming Frog run.
 *
 * Renders nothing until there is a real answer. A failed or unsupported
 * endpoint must not leave a broken or misleading badge in every view's header.
 */
export function CrawlActivityIndicator(): JSX.Element | null {
  const activity = useCrawlActivity();
  if (activity === null) return null;

  const tone = toneOf(activity);
  const label = `Rankuno ${activity.rankuno_active}/${activity.rankuno_cap} · Screaming Frog ${activity.sf_active} active`;
  const tooltip =
    tone === "full"
      ? `Server is at capacity (${activity.rankuno_cap} concurrent crawls). New crawls will wait or be refused until one finishes.`
      : "Crawls running for your organisation, on any device.";

  return (
    <Tooltip title={tooltip}>
      {/* Focusable so the tooltip is reachable by keyboard, not just hover. */}
      <div
        className={`crawlact crawlact-${tone}`}
        role="status"
        aria-live="polite"
        aria-label={tone === "full" ? `${label}. Server at capacity.` : label}
        tabIndex={0}
      >
        {tone === "full" ? (
          <WarningOutlined className="crawlact-icon" aria-hidden="true" />
        ) : tone === "running" ? (
          <LoadingOutlined className="crawlact-icon crawlact-spin" aria-hidden="true" />
        ) : (
          <ClockCircleOutlined className="crawlact-icon" aria-hidden="true" />
        )}
        <span className="crawlact-item" aria-hidden="true">
          <span className="crawlact-name">Rankuno </span>
          <span className="crawlact-num">
            {activity.rankuno_active}/{activity.rankuno_cap}
          </span>
        </span>
        <span className="crawlact-sep" aria-hidden="true">
          |
        </span>
        <span className="crawlact-item" aria-hidden="true">
          <span className="crawlact-name">Screaming Frog </span>
          <span className="crawlact-num">{activity.sf_active}</span>
          <span className="crawlact-name"> active</span>
        </span>
        {tone === "full" && (
          // Colour is never the only signal for "full".
          <span className="crawlact-flag" aria-hidden="true">
            FULL
          </span>
        )}
      </div>
    </Tooltip>
  );
}
