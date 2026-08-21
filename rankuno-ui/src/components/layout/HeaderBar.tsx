import { FilePdfOutlined } from "@ant-design/icons";
import { Button, Select, Segmented, Space, Tooltip } from "antd";
import { fetchedPercent, formatRemaining } from "../../lib/duration";
import { formatCrawlTime } from "../../lib/time";
import { hostOf } from "../../lib/url";
import type { LiveJob } from "../../store/useCrawlStore";
import { isLive, newestLiveJob, useCrawlStore } from "../../store/useCrawlStore";
import { useUiStore } from "../../store/useUiStore";

interface Props {
  /** True when a header menu was parsed, so navigation grouping is meaningful. */
  navParsed: boolean;
  onNewCrawl: () => void;
  onPrint: () => void;
}

/**
 * The application header: crawl selector, actions, and background progress.
 *
 * Extracted from `DashboardShell` when crawling became non-blocking. The pill
 * is the reason: progress has to be visible from every tab, so it belongs to a
 * component that is mounted above the view switch rather than inside one of the
 * views.
 */
export function HeaderBar({ navParsed, onNewCrawl, onPrint }: Props): JSX.Element {
  const result = useCrawlStore((state) => state.result);
  const jobs = useCrawlStore((state) => state.jobs);
  const activeJobId = useCrawlStore((state) => state.activeJobId);
  const selectJob = useCrawlStore((state) => state.selectJob);
  const grouping = useCrawlStore((state) => state.grouping);
  const setGrouping = useCrawlStore((state) => state.setGrouping);
  const adapter = useCrawlStore((state) => state.adapter);
  const status = useCrawlStore((state) => state.status);
  const liveJobs = useCrawlStore((state) => state.liveJobs);

  // Computed in the render body rather than inside the selector: a selector
  // returning a fresh array would compare unequal on every store write and
  // re-render the header continuously during a crawl.
  const runningCount = Object.values(liveJobs).filter(isLive).length;
  const lead = newestLiveJob(liveJobs);

  return (
    <header className="hdr">
      {/*
        The site, once. This read `Rankuno Engine — https://www.gep.com/` while
        the selector beside it read `https://www.gep.com/ (+14 from Screaming
        Frog)`: the same address twice, taking half the bar between them, and
        the product name is already on the rail. The host alone is what an
        analyst checks to be sure they are looking at the right client.
      */}
      <h1>{result ? hostOf(result.base_url) : "No crawl loaded"}</h1>

      <Space size={8}>
        <Select
          size="small"
          style={{ minWidth: 260 }}
          value={activeJobId ?? undefined}
          onChange={selectJob}
          placeholder="Select a crawl"
          options={jobs.map((job) => ({
            value: job.id,
            label: job.label,
            crawledAt: job.crawledAt,
          }))}
          // Only the dropdown row is two-line. `label` stays a plain string so
          // the closed control keeps its single-line height — rendering the
          // timestamp there too would push the header taller every time a crawl
          // is selected.
          optionRender={(option) => (
            <div className="job-opt">
              <span className="job-opt-label">{option.data.label}</span>
              <span className="job-opt-time">{formatCrawlTime(option.data.crawledAt)}</span>
            </div>
          )}
        />
        {adapter?.startJob !== undefined && (
          // No longer a loading button. Crawls run in the background and the
          // engine takes three at once, so a second one is a legitimate action
          // while the first is still going.
          <Button size="small" type="primary" onClick={onNewCrawl}>
            New crawl
          </Button>
        )}
        {result && (
          <Button size="small" icon={<FilePdfOutlined />} onClick={onPrint}>
            PDF
          </Button>
        )}
        {/* The one control here whose effect is not obvious from its label:
            it changes what a lane *means*, not merely how rows are sorted. */}
        <Tooltip title="Group the tree by the site's own header menu, or by URL path depth. Navigation needs a menu the crawl could parse.">
          <Segmented
            size="small"
            value={grouping}
            onChange={(value) => setGrouping(value as "navigation" | "path")}
            options={[
              { label: "Navigation", value: "navigation", disabled: !navParsed },
              { label: "URL path", value: "path" },
            ]}
          />
        </Tooltip>
      </Space>

      {lead ? (
        <BackgroundPill lead={lead} runningCount={runningCount} />
      ) : (
        <div className={`perf${result?.discovery.truncated ? " stale" : ""}`}>
          {/*
            Pages, not nodes, and no "virtual list".

            `nodes` counted tree nodes, which include the structural groupings
            the tree needs to hold its children — 29,248 against 27,656 pages on
            kinsta. Putting that figure in the header beside a KPI card reading
            the smaller one is the same mismatch cycle 0022 fixed in the audit.
            "virtual list" was a note about how the pane is rendered, which is
            not a fact about the site.
          */}
          {result
            ? `${result.summary.pages_classified.toLocaleString()} pages${
                result.discovery.truncated ? " · partial crawl" : ""
              }`
            : status.toUpperCase()}
        </div>
      )}
    </header>
  );
}

/**
 * Live progress for background crawls, sitting where the perf readout was.
 *
 * Shows one crawl in detail and counts the rest. Rendering three full progress
 * lines in a 54px header would either shrink the type past legibility or push
 * the header taller, and the operator who needs all three is one click from the
 * jobs table that shows them properly.
 */
function BackgroundPill({ lead, runningCount }: { lead: LiveJob; runningCount: number }): JSX.Element {
  const setView = useUiStore((state) => state.setView);
  // `lead` is the most recently *started* crawl, per `newestLiveJob` — the one
  // the operator just submitted and is watching for. An earlier draft of this
  // comment said the oldest, which is a different job and would need a
  // different selector; the call site has always passed the newest.
  const telemetry = lead.telemetry;
  const completed = telemetry?.completed ?? 0;
  const discovered = telemetry?.discovered ?? 0;
  const percent = fetchedPercent(completed, discovered);

  return (
    <Tooltip title="Crawling in the background. Open the jobs tab for the full stream.">
      <button className="bgpill" type="button" onClick={() => setView("jobs")}>
        <span className="bgpill-spark" aria-hidden="true" />
        <span className="bgpill-host">{hostOf(lead.label)}</span>
        {discovered > 0 ? (
          <>
            <span className="bgpill-pct">{percent}%</span>
            <span className="bgpill-count">
              {completed.toLocaleString()} / {discovered.toLocaleString()}
            </span>
          </>
        ) : (
          <span className="bgpill-count">discovering…</span>
        )}
        <span className="bgpill-eta">
          {telemetry?.eta_seconds != null
            ? `~${formatRemaining(telemetry.eta_seconds)} left`
            : lead.status === "queued"
              ? "queued"
              : "estimating…"}
        </span>
        {runningCount > 1 && <span className="bgpill-more">+{runningCount - 1}</span>}
        <span className="bgpill-cta">View</span>
      </button>
    </Tooltip>
  );
}
