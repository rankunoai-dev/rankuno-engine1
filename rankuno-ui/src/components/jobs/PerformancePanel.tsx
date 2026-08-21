import { Alert, Modal, Table, Tag, Upload } from "antd";
import { useEffect, useState } from "react";
import type {
  Opportunity,
  PerformanceSummary,
  SectionPerformance,
} from "../../adapters/adapterInterface";
import { API_BASE } from "../../adapters/httpAdapter";
import { useCrawlStore } from "../../store/useCrawlStore";
import "./jobs.css";

/**
 * Bytes accepted from one export.
 *
 * Decimal megabytes, matching the message that reports the file's size, and
 * matching the server's own limit — a browser-side cap in binary megabytes
 * would tell somebody their 33 MB file was refused by a "32 MB" limit.
 *
 * Generous against a real export: the Search Console UI caps a download at
 * 1,000 rows and the API at 50,000, so these files are kilobytes.
 */
const MAX_EXPORT_BYTES = 32 * 1_000_000;

/**
 * Plain-English heading for each recommendation kind.
 *
 * The enum values are the engine's vocabulary. The person who acts on a row is
 * usually not the person who ran the crawl, so the panel never shows them raw.
 */
const KIND_LABELS: Record<string, string> = {
  orphan_with_traffic: "Earning clicks with no internal link",
  buried_with_traffic: "Earning clicks from deep in the navigation",
  indexed_crawl_trap: "Crawl traps Google has indexed",
  underperforming_sibling: "Ranking off page one beside a linked sibling",
};

/**
 * Why a kind could not be evaluated.
 *
 * Shown as prominently as the findings themselves. A list of recommendations
 * with a silent omission invites the reader to conclude the site has no
 * orphans, when the truth is that this crawl could not tell.
 */
const GAP_LABELS: Record<string, string> = {
  no_search_data:
    "No export row resolved to a crawled page, so nothing could be ranked.",
  inbound_links_unreliable:
    "This crawl counted no inbound links for most of its pages — the hallmark of a " +
    "crawl that stopped at its page ceiling. Link-based findings would be artefacts.",
};

interface Props {
  jobId: string;
  label: string;
  open: boolean;
  onClose: () => void;
}

/**
 * Attach Search Console data to a crawl and show what it says.
 *
 * A modal per job rather than a page, for the same reason as `ReconcilePanel`:
 * a performance report is *about* one crawl, and a standalone screen would need
 * its own job picker that could disagree with the row that was clicked.
 *
 * The order of what is shown is the argument of this component. Resolution
 * quality comes first, then coverage, then the numbers. Every total here is
 * derived from a join between Google's URLs and ours, and a reader who sees
 * section totals without knowing that a third of the export failed to resolve
 * is reading a confident understatement.
 */
export function PerformancePanel({ jobId, label, open, onClose }: Props): JSX.Element {
  const upload = useCrawlStore((state) => state.uploadGscExport);

  const [busy, setBusy] = useState(false);
  const [summary, setSummary] = useState<PerformanceSummary | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);

  // Reload the saved report whenever the dialog opens. Without this, closing it
  // discards a report whose input a person had to fetch from another product.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    void (async () => {
      const adapter = useCrawlStore.getState().adapter;
      if (!adapter?.getPerformance) return;
      try {
        const saved = await adapter.getPerformance(jobId);
        // `cancelled` because the operator can close and reopen on another job
        // faster than this resolves, and a late answer must not overwrite a
        // newer one.
        if (!cancelled && saved) {
          setSummary(saved.summary);
          setSavedAt(saved.created_at);
        }
      } catch {
        // A missing report is the normal case and not worth a banner: the drop
        // zone below is a perfectly good next step.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, jobId]);

  async function accept(file: File): Promise<void> {
    setProblem(null);
    if (file.size > MAX_EXPORT_BYTES) {
      setProblem(
        `That file is ${(file.size / 1e6).toFixed(0)} MB, over the ` +
          `${MAX_EXPORT_BYTES / 1e6} MB limit. A Search Console export is normally ` +
          `well under 1 MB — check you exported the Performance report and not a log.`,
      );
      return;
    }
    setBusy(true);
    try {
      // The `File` itself, never `file.text()`. The default download is a ZIP,
      // and decoding an archive to a string turns it into mojibake that parses
      // as nothing. Handing `fetch` the Blob also lets the browser stream it —
      // and `File.arrayBuffer` does not exist in jsdom, so reading it here
      // would cost this component its tests.
      const result = await upload(jobId, file);
      setSavedAt(null);
      if (result === null) {
        setProblem("The upload failed. See the error banner on the dashboard.");
      } else {
        setSummary(result);
      }
    } catch (cause) {
      setProblem(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onCancel={onClose}
      title={`Search Console — ${label}`}
      width={980}
      footer={null}
      destroyOnClose
    >
      <Upload.Dragger
        accept=".zip,.csv,.xlsx"
        multiple={false}
        showUploadList={false}
        disabled={busy}
        beforeUpload={(file) => {
          void accept(file as File);
          // `false` keeps antd from performing its own XHR upload. The store
          // owns the request.
          return false;
        }}
      >
        <p className="jb-drop-title">
          {busy ? "Reading the export…" : "Drop the Search Console export here"}
        </p>
        <p className="rc-drop-hint">
          Performance → Export. The ZIP straight from “Export → CSV” is fine — the
          pages tab is found inside it. Excel workbooks and a bare CSV work too.
        </p>
      </Upload.Dragger>

      {problem && <Alert type="error" showIcon message={problem} className="jb-alert" />}

      {summary && (
        <>
          {savedAt && (
            <Alert
              type="info"
              showIcon
              className="jb-alert"
              message={`Saved report from ${new Date(savedAt).toLocaleString()}. Drop a new export to replace it.`}
            />
          )}
          <Quality summary={summary} />
          <Sections summary={summary} />
          <Opportunities summary={summary} jobId={jobId} />
        </>
      )}
    </Modal>
  );
}

/**
 * How much of the export landed, and how much of the site it describes.
 *
 * Two different questions, and the second is the one nobody asks. A 1,000-row
 * UI export against a 12,000-page site resolves every row — a perfect match
 * rate — while describing 8% of the site. Only coverage says so.
 */
function Quality({ summary }: { summary: PerformanceSummary }): JSX.Element {
  const coverage = summary.pages ? summary.pages_with_data / summary.pages : 0;
  return (
    <>
      {!summary.is_reliable && (
        <Alert
          type="warning"
          showIcon
          className="jb-alert"
          message={`Only ${summary.match_rate_pct}% of the export matched a crawled page.`}
          description={
            "Every total below is missing the rest, and the loss is not spread evenly — " +
            "unresolved URLs usually share a structural cause, so one section absorbs most of it."
          }
        />
      )}
      <div className="jb-gap-heads">
        <Stat label="Rows read" value={summary.rows.toLocaleString()} />
        <Stat label="Matched a page" value={`${summary.match_rate_pct}%`} />
        <Stat
          label="Site covered"
          value={`${(coverage * 100).toFixed(1)}%`}
          hint={`${summary.pages_with_data.toLocaleString()} of ${summary.pages.toLocaleString()} pages`}
        />
        <Stat label="Clicks attributed" value={summary.rollup.site.clicks.toLocaleString()} />
        {summary.rollup.unattributed.clicks > 0 && (
          <Stat
            label="Clicks unattributed"
            value={summary.rollup.unattributed.clicks.toLocaleString()}
            hint={`${summary.rollup.unattributed.rows.toLocaleString()} rows reached no page`}
          />
        )}
      </div>
      {summary.source_name && (
        <p className="perf-source">
          Read from <b>{summary.source_name}</b>
          {summary.skipped_rows > 0 && ` · ${summary.skipped_rows} rows had no usable address`}
        </p>
      )}
    </>
  );
}

function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}): JSX.Element {
  return (
    <div className="jb-stat">
      <span className="jb-stat-v">{value}</span>
      <span className="jb-stat-l">{label}</span>
      {hint && <span className="jb-stat-hint">{hint}</span>}
    </div>
  );
}

/**
 * Top-level sections, which sum to the site row.
 *
 * Only depth 1. The rollup carries every trail prefix — 928 rows on a
 * 12,787-page crawl — and a flat table of all of them is not a thing anyone
 * reads. The tree already exists for going deeper.
 */
function Sections({ summary }: { summary: PerformanceSummary }): JSX.Element {
  const roots = summary.rollup.sections
    .filter((section) => section.depth === 1)
    .sort((a, b) => b.clicks - a.clicks);

  return (
    <>
      <h4 className="perf-heading">Sections</h4>
      <Table<SectionPerformance>
        dataSource={roots}
        rowKey={(section) => section.path.join(" > ")}
        size="small"
        pagination={false}
        scroll={{ y: 260 }}
        columns={[
          { title: "Section", dataIndex: "label", key: "label" },
          {
            title: "Clicks",
            dataIndex: "clicks",
            key: "clicks",
            align: "right",
            render: (clicks: number) => clicks.toLocaleString(),
          },
          {
            title: "Impressions",
            dataIndex: "impressions",
            key: "impressions",
            align: "right",
            render: (value: number) => value.toLocaleString(),
          },
          {
            title: "CTR",
            key: "ctr",
            align: "right",
            render: (_: unknown, section) => `${(section.ctr * 100).toFixed(2)}%`,
          },
          {
            title: "Position",
            key: "position",
            align: "right",
            // An em dash, never 0. Position zero reads as better than rank 1 and
            // would sort an unmeasured section to the top of the table.
            render: (_: unknown, section) =>
              section.position === null ? "—" : section.position.toFixed(1),
          },
          {
            title: "Pages with data",
            key: "coverage",
            align: "right",
            render: (_: unknown, section) =>
              `${section.pages_with_data.toLocaleString()} / ${section.pages.toLocaleString()}`,
          },
        ]}
      />
    </>
  );
}

/**
 * The recommendations, grouped by kind, with what was skipped shown beside them.
 */
function Opportunities({
  summary,
  jobId,
}: {
  summary: PerformanceSummary;
  jobId: string;
}): JSX.Element {
  const report = summary.opportunities;
  const kinds = [...new Set(report.opportunities.map((item) => item.kind))];

  return (
    <>
      <div className="perf-heading-row">
        <h4 className="perf-heading">Recommendations</h4>
        {report.opportunities.length > 0 && (
          <a
            /* A class this file owns. The shared `rk-btn` is scoped to
               `.rk-dash`, and this renders in a modal portal outside it — so
               borrowing it would give an unstyled link that `tsc` cannot see. */
            className="perf-download"
            href={`${API_BASE}/jobs/${encodeURIComponent(jobId)}/opportunities.csv`}
          >
            Download CSV
          </a>
        )}
      </div>

      {Object.entries(report.skipped).map(([kind, gap]) => (
        <Alert
          key={kind}
          type="info"
          showIcon
          className="jb-alert"
          message={`Not evaluated: ${KIND_LABELS[kind] ?? kind}`}
          description={GAP_LABELS[gap] ?? gap}
        />
      ))}

      {kinds.map((kind) => {
        const rows = report.opportunities.filter((item) => item.kind === kind);
        const dropped = report.truncated[kind] ?? 0;
        return (
          <div key={kind} className="perf-kind">
            <h5 className="perf-kind-title">
              {KIND_LABELS[kind] ?? kind}
              <Tag className="perf-kind-count">{report.found[kind] ?? rows.length}</Tag>
              {/* Never silent. A list that stops at 50 and says nothing reads
                  as "there were 50". */}
              {dropped > 0 && (
                <span className="perf-kind-more">
                  showing the top {rows.length} of {report.found[kind]}
                </span>
              )}
            </h5>
            <Table<Opportunity>
              dataSource={rows}
              rowKey={(item) => `${item.kind}:${item.url}`}
              size="small"
              pagination={false}
              scroll={{ y: 220 }}
              columns={[
                {
                  title: "Page",
                  dataIndex: "url",
                  key: "url",
                  render: (url: string) => <span className="perf-url">{url}</span>,
                },
                {
                  title: "Clicks",
                  dataIndex: "clicks",
                  key: "clicks",
                  align: "right",
                  render: (clicks: number) => clicks.toLocaleString(),
                },
                {
                  title: "Impressions",
                  dataIndex: "impressions",
                  key: "impressions",
                  align: "right",
                  render: (value: number) => value.toLocaleString(),
                },
                { title: "Why", dataIndex: "reason", key: "reason" },
              ]}
            />
          </div>
        );
      })}

      {report.opportunities.length === 0 && Object.keys(report.skipped).length === 0 && (
        <Alert
          type="success"
          showIcon
          className="jb-alert"
          message="No recommendations from this export."
          description="Every kind was evaluated and none matched."
        />
      )}
    </>
  );
}
