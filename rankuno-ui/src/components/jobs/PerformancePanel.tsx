import { Alert, Modal, Table, Tag, Upload } from "antd";
import { useEffect, useState } from "react";
import type {
  Opportunity,
  PerformanceSummary,
  SectionPerformance,
  UnmatchedGroup,
} from "../../adapters/adapterInterface";
import { API_BASE } from "../../adapters/httpAdapter";
import { downloadCsv, toCsv } from "../../lib/csv";
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
 * Findings listed per kind on screen.
 *
 * A reading limit, and only that. The download carries every scored row and the
 * heading says so. These were the same number until an analyst asked why a
 * section holding 202 findings offered a "Download 50" button: the panel's
 * readable length had quietly become the size of the deliverable.
 */
const DISPLAY_ROWS = 50;

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
  indexed_subdomain: "Google indexes a subdomain this crawl did not cover",
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
          <Quality summary={summary} jobId={jobId} />
          <Unmatched summary={summary} />
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
function Quality({
  summary,
  jobId,
}: {
  summary: PerformanceSummary;
  jobId: string;
}): JSX.Element {
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
      <div className="perf-downloads">
        <a
          className="perf-download"
          href={`${API_BASE}/jobs/${encodeURIComponent(jobId)}/matched.csv`}
        >
          Download the {summary.matched.toLocaleString()} matched pages
        </a>
        <a
          className="perf-download perf-download-muted"
          href={`${API_BASE}/jobs/${encodeURIComponent(jobId)}/unmatched.csv`}
        >
          Download the {(summary.rows - summary.matched).toLocaleString()} unmatched rows
        </a>
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
 * Plain-English meaning for each reason a row reached no page.
 *
 * `other_subdomain` leads because it is the one that is usually a finding
 * rather than an explanation.
 */
const REASON_LABELS: Record<string, string> = {
  other_subdomain: "A subdomain of this site the crawl never covered",
  off_site: "A different domain — another property",
  not_crawled: "On this site, but this crawl never reached it",
  ambiguous: "Several crawled pages claim this address",
  unparseable: "Not a URL",
};

/**
 * Where the rows that matched nothing went.
 *
 * Sits directly under the match rate and above every total, because it is the
 * arithmetic behind that percentage. "41.5% matched" asks to be taken on trust;
 * this partitions the other 58.5% by host, and the groups add back up.
 *
 * Grouped by host rather than by reason because that is the axis the answer
 * usually lies along — on the first real export the two largest groups were one
 * host each, 558 rows between them, and no other view would have put them side
 * by side.
 */
function Unmatched({ summary }: { summary: PerformanceSummary }): JSX.Element | null {
  const groups = summary.unmatched;
  if (groups === undefined) {
    // Absent, not empty. A report saved before this existed would otherwise
    // render nothing at all, and "the buttons are missing" is what that looks
    // like from the outside.
    return (
      <Alert
        type="info"
        showIcon
        className="jb-alert"
        message="This saved report predates the breakdown of unmatched rows."
        description="Drop the export in again to see which URLs did not match, and why."
      />
    );
  }
  if (groups.length === 0) return null;

  return (
    <>
      <h4 className="perf-heading">
        Rows that matched no page ({(summary.rows - summary.matched).toLocaleString()} of{" "}
        {summary.rows.toLocaleString()})
      </h4>
      <Table<UnmatchedGroup>
        dataSource={groups}
        rowKey={(group) => `${group.host}:${group.reason}`}
        size="small"
        pagination={false}
        scroll={{ y: 240 }}
        expandable={{
          expandedRowRender: (group) => (
            <ul className="perf-examples">
              {group.examples.map((url) => (
                <li key={url}>{url}</li>
              ))}
            </ul>
          ),
          rowExpandable: (group) => group.examples.length > 0,
        }}
        columns={[
          {
            title: "Host",
            dataIndex: "host",
            key: "host",
            render: (host: string) => <span className="perf-url">{host || "(no host)"}</span>,
          },
          {
            title: "Why",
            dataIndex: "reason",
            key: "reason",
            render: (reason: string) => REASON_LABELS[reason] ?? reason,
          },
          {
            title: "URLs",
            dataIndex: "urls",
            key: "urls",
            align: "right",
            render: (urls: number) => urls.toLocaleString(),
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
        ]}
      />
    </>
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
      <div className="perf-heading-row">
        <h4 className="perf-heading">
          Sections
          <Tag className="perf-kind-count">{roots.length}</Tag>
        </h4>
        {/* Stated because the two are easy to assume identical and are not.
            The visualizer groups a localised page under its URL locale prefix
            — `/de-de/…` becomes its own tab — while this rolls it up under the
            breadcrumb its page publishes, which is itself translated. On
            gep.com that is 30 sections here against 36 tabs there; on
            highradius.com both are 31 and the *sets* still differ. */}
        <span className="perf-kind-more">
          grouped by published breadcrumb — the visualizer&rsquo;s tabs also split by
          URL locale, so the two lists differ on a multilingual site
        </span>
      </div>
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
/** Columns of a recommendations export, matching the server's whole-report CSV. */
const OPPORTUNITY_HEADERS = [
  "kind",
  "score",
  "url",
  "section",
  "clicks",
  "impressions",
  "position",
  "inbound_internal_links",
  "reason",
] as const;

/**
 * One section's recommendations as a file.
 *
 * Built in the browser rather than added as a second server endpoint, because
 * the rows here **are** the rows the server would send. Capping happens in
 * `opportunity_scorer` before anything is stored, so the sidecar holds the same
 * top-N per kind that this panel received — a `?kind=` parameter on
 * `opportunities.csv` would re-serve this list from disk and call it complete.
 *
 * The header order matches the whole-report CSV so the two files concatenate.
 */
function exportSection(label: string, rows: readonly Opportunity[]): void {
  const csv = toCsv(
    OPPORTUNITY_HEADERS,
    rows.map((row) => [
      row.kind,
      row.score,
      row.url,
      row.section.join(" > "),
      row.clicks,
      row.impressions,
      row.position,
      row.inbound_internal_links,
      row.reason,
    ]),
  );
  downloadCsv(`${slug(label)}.csv`, csv);
}

/** `earning-clicks-with-no-internal-link` from a section heading. */
function slug(label: string): string {
  return (
    label
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "") || "recommendations"
  );
}

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
          <span className="perf-heading-actions">
            <a
              /* A class this file owns. The shared `rk-btn` is scoped to
                 `.rk-dash`, and this renders in a modal portal outside it — so
                 borrowing it would give an unstyled link that `tsc` cannot see. */
              className="perf-download"
              href={`${API_BASE}/jobs/${encodeURIComponent(jobId)}/opportunities.xlsx`}
              title="One sheet per recommendation kind, plus a contents page listing the kinds that were not evaluated."
            >
              Download Excel (one sheet per kind)
            </a>
            {/* Kept, and second. Anything already linking to the flat file
                keeps working, and a single sheet is still what someone piping
                this into another tool wants. */}
            <a
              className="perf-download-plain"
              href={`${API_BASE}/jobs/${encodeURIComponent(jobId)}/opportunities.csv`}
            >
              or a single CSV
            </a>
          </span>
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
        // Shown on screen; `rows` is what the download gets. Reading is
        // bounded here, the export is not.
        const visible = rows.slice(0, DISPLAY_ROWS);
        const dropped = report.truncated[kind] ?? 0;
        return (
          <div key={kind} className="perf-kind">
            <h5 className="perf-kind-title">
              {/* Severity sits on the group, not the row: every finding of a
                  kind shares it here, and a badge repeated down a column stops
                  being read. */}
              {rows.some((item) => item.severity === "critical") && (
                <Tag color="red" className="perf-kind-count">
                  Critical
                </Tag>
              )}
              {KIND_LABELS[kind] ?? kind}
              <Tag className="perf-kind-count">{report.found[kind] ?? rows.length}</Tag>
              {/* Never silent. A list that stops at 50 and says nothing reads
                  as "there were 50". */}
              {rows.length > visible.length && (
                <span className="perf-kind-more">
                  showing {visible.length} here · all {rows.length.toLocaleString()} in the
                  download
                </span>
              )}
              {/* A different truncation, and conflating the two is what made
                  the old message misleading. This one means the rows do not
                  exist: they were scored, counted, and discarded. */}
              {dropped > 0 && (
                <span className="perf-kind-more">
                  · {dropped.toLocaleString()} beyond the scoring ceiling were not kept
                </span>
              )}
              {/* Per section, because each one goes to a different person. The
                  internal-link findings are a content job and the navigation
                  depth findings are an information-architecture job; handing
                  either owner the combined file makes them filter it first. */}
              <button
                type="button"
                className="perf-download perf-download-sm"
                title={
                  dropped > 0
                    ? `Download all ${rows.length.toLocaleString()} scored rows. A further ${dropped.toLocaleString()} passed the filters but fell beyond the scoring ceiling and are not stored anywhere.`
                    : `Download all ${rows.length.toLocaleString()} rows`
                }
                onClick={() => exportSection(KIND_LABELS[kind] ?? kind, rows)}
              >
                Download {rows.length.toLocaleString()}
              </button>
            </h5>
            <Table<Opportunity>
              dataSource={visible}
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
