import { Alert, Button, Modal, Table, Tag, Upload } from "antd";
import type { UploadFile } from "antd/es/upload/interface";
import { useEffect, useState } from "react";
import type { ReconciliationSummary, SavedReconciliation } from "../../adapters/adapterInterface";
import { API_BASE } from "../../adapters/httpAdapter";
import { downloadCsv, hostSlug, toCsv } from "../../lib/csv";
import { useCrawlStore } from "../../store/useCrawlStore";
import { useUiStore } from "../../store/useUiStore";
import "./jobs.css";

/**
 * Bytes accepted from one export.
 *
 * Decimal megabytes, not binary. The refusal message divides by 1e6 to name the
 * file's size, so a 1024-based limit told the operator their 84 MB file was
 * rejected by an "80 MB" cap and left them 4 MB to explain. The two now agree.
 */
const MAX_CSV_BYTES = 80 * 1_000_000;

/**
 * Plain-English meaning for each frog-side reason.
 *
 * The enum values are the engine's vocabulary; an analyst should not have to
 * learn it to read a gap. Only `MISSED_PAGE` is a defect and the wording says
 * so, because the whole table otherwise reads as a list of failures when four
 * of its five rows are the engine working correctly.
 */
const FROG_REASONS: Record<string, string> = {
  MISSED_PAGE: "Live pages the crawl never reached — merged into the tree",
  REDIRECT: "Redirect sources — not pages; their destinations are already held",
  CLIENT_ERROR: "4xx / 5xx — not pages",
  OFF_SITE: "A different host — out of scope by design",
  MEDIA_URL: "Images, scripts, stylesheets — refused by design",
  SPIDER_TRAP: "Relative-href crawl loops — refused by design",
  NON_INDEXABLE: "Live but canonicalised elsewhere or noindex",
};

const ENGINE_REASONS: Record<string, string> = {
  SITEMAP_ORPHAN: "Published, and no internal link reaches them — the finding",
  QUERY_VARIANT: "Same path with a query string Screaming Frog collapsed",
  REPEATED_SUFFIX_TRAP: "Fabricated by a relative-href loop — our defect",
  MALFORMED_MARKUP: "Built from broken HTML on the site — not URLs at all",
};

interface Props {
  jobId: string;
  label: string;
  open: boolean;
  onClose: () => void;
}

/**
 * Upload a Screaming Frog export and show the two-way gap.
 *
 * Deliberately a modal launched per job rather than a page: a reconciliation is
 * *about* one crawl, and a standalone screen would need its own job picker that
 * could disagree with the row the operator clicked.
 *
 * The whole feature is optional. This dialog is the only way to reach it, the
 * button that opens it is hidden when the adapter cannot reconcile, and a crawl
 * that never sees an export is unaffected.
 */
export function ReconcilePanel({ jobId, label, open, onClose }: Props): JSX.Element {
  const reconcile = useCrawlStore((state) => state.reconcileScreamingFrog);
  const selectJob = useCrawlStore((state) => state.selectJob);
  const setView = useUiStore((state) => state.setView);

  const [busy, setBusy] = useState(false);
  const [summary, setSummary] = useState<ReconciliationSummary | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  // The URL lists behind the counts, held so each figure can be downloaded on
  // its own. The panel used to keep `saved.summary` and drop the rest, which
  // meant the addresses were fetched, parsed and then discarded one line later.
  const [lists, setLists] = useState<SavedReconciliation | null>(null);

  // Reload the last cross-check whenever the dialog opens. Without this, closing
  // it discarded a result that cost an export produced by hand in another tool,
  // and getting it back meant exporting and uploading 4 MB again.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    void (async () => {
      const adapter = useCrawlStore.getState().adapter;
      if (!adapter?.getReconciliation) return;
      try {
        const saved = await adapter.getReconciliation(jobId);
        // `cancelled` because the operator can close and reopen on another job
        // faster than this resolves, and a late answer must not overwrite a
        // newer one.
        if (!cancelled && saved) {
          setSummary(saved.summary);
          setSavedAt(saved.created_at);
          setLists(saved);
        }
      } catch {
        // A missing or unreadable cross-check is not worth a banner: the drop
        // zone below is a perfectly good next step.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, jobId]);

  function reset(): void {
    setSummary(null);
    setProblem(null);
    setSavedAt(null);
    setLists(null);
    setBusy(false);
  }

  async function accept(file: File): Promise<void> {
    setProblem(null);
    if (file.size > MAX_CSV_BYTES) {
      // Checked here as well as on the server. A 200 MB file read into a string
      // in the browser is a tab crash, which gives the operator no message at
      // all — the server's own refusal would never be reached.
      setProblem(
        `That file is ${(file.size / 1e6).toFixed(0)} MB. Export "Internal → HTML" ` +
          `rather than the full crawl, or trim it first.`,
      );
      return;
    }
    setBusy(true);
    try {
      // The `File` itself, never `file.text()` and never an ArrayBuffer.
      // Screaming Frog exports .csv and .xlsx side by side and the spreadsheet
      // is the one people reach for first; decoding a workbook to a string
      // turns it into mojibake that fails to parse server-side.
      //
      // Handing `fetch` the Blob lets the browser stream it rather than holding
      // a second copy of a 50 MB export in memory — and `File.arrayBuffer` does
      // not exist in jsdom, so reading it here would also cost the component
      // its tests.
      const result = await reconcile(jobId, file);
      setSavedAt(null);
      if (result === null) {
        setProblem("The reconciliation failed. See the error banner on the dashboard.");
      } else {
        setSummary(result);
        // The reconcile response carries the counts only. The per-figure
        // downloads need the addresses, and the server has just written them,
        // so read the sidecar back rather than widening the response shape.
        // A failure here costs the download buttons, not the result.
        try {
          const adapter = useCrawlStore.getState().adapter;
          const saved = await adapter?.getReconciliation?.(jobId);
          if (saved) setLists(saved);
        } catch {
          setLists(null);
        }
      }
    } catch (cause) {
      setProblem(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  function openMerged(): void {
    if (!summary) return;
    void (async () => {
      await selectJob(summary.job_id);
      setView("visualizer");
      onClose();
      reset();
    })();
  }

  return (
    <Modal
      open={open}
      title={`Cross-check against Screaming Frog — ${label}`}
      width={720}
      onCancel={() => {
        onClose();
        reset();
      }}
      footer={
        summary && summary.merged > 0 ? (
          <Button type="primary" onClick={openMerged}>
            Open merged tree ({summary.merged.toLocaleString()} added)
          </Button>
        ) : null
      }
      destroyOnClose
    >
      {summary === null ? (
        <>
          <p className="jb-dim">
            Export <b>Internal → HTML</b> from Screaming Frog as CSV and drop it
            here. Nothing is uploaded anywhere: the file is read in your browser
            and posted to the local engine on this machine.
          </p>
          <Upload.Dragger
            accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            maxCount={1}
            disabled={busy}
            showUploadList={false}
            // `beforeUpload` returning false stops antd from POSTing the file
            // itself. It has no endpoint to POST to — the store owns the
            // request — and letting it try produces a silent network error
            // beside a spinner that never stops.
            beforeUpload={(file: UploadFile & File) => {
              void accept(file);
              return false;
            }}
          >
            <p className="jb-drop-title">{busy ? "Reconciling…" : "Drop internal_html.csv or .xlsx"}</p>
            <p className="jb-dim">or click to choose a file</p>
          </Upload.Dragger>
          {problem && (
            <Alert type="error" showIcon message={problem} style={{ marginTop: 12 }} />
          )}
        </>
      ) : (
        <>
          {savedAt && (
            /* Says plainly that this is a stored result rather than one just
               computed, and offers the way to replace it. A cross-check read
               back weeks later against a site that has moved on is exactly how
               a stale number gets quoted to a client. */
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 12 }}
              message={`Saved cross-check from ${new Date(savedAt).toLocaleString()}`}
              description="Drop a newer export to replace it."
              action={
                <Button size="small" onClick={reset}>
                  New export
                </Button>
              }
            />
          )}
          <GapReport summary={summary} lists={lists} jobId={jobId} />
          {/* A plain anchor, not a fetch-and-blob. The endpoint already sets
              Content-Disposition, so the browser saves the file itself and the
              app never holds a second copy of a multi-megabyte export. */}
          {/* The workbook first. A real cross-check runs to 17,640 rows, and in
              one flat sheet the handful of pages the crawl actually missed sit
              below sixteen thousand differences that need no action. The CSV
              stays for anything that consumes it as a feed. */}
          <a
            className="jb-download"
            href={`${API_BASE}/jobs/${encodeURIComponent(jobId)}/reconciliation.xlsx`}
            download
          >
            Download the cross-check (Excel, one sheet per list)
          </a>
          <a
            className="jb-download jb-download-muted"
            href={`${API_BASE}/jobs/${encodeURIComponent(jobId)}/reconciliation.csv`}
            download
          >
            or as a single CSV
          </a>
        </>
      )}
    </Modal>
  );
}

/** The two-way gap, once an export has been read. */
function GapReport({
  summary,
  lists,
  jobId,
}: {
  summary: ReconciliationSummary;
  lists: SavedReconciliation | null;
  jobId: string;
}): JSX.Element {
  const site = hostSlug(summary.base_url);
  /** `gep.com-missed-pages.csv` — named for the site and the figure. */
  const name = (part: string) => `${site}-${part}.csv`;
  const rows = (
    map: Record<string, number>,
    labels: Record<string, string>,
  ): Array<{ key: string; reason: string; meaning: string; count: number }> =>
    Object.entries(map)
      .sort((a, b) => b[1] - a[1])
      .map(([reason, count]) => ({
        key: reason,
        reason,
        meaning: labels[reason] ?? "—",
        count,
      }));

  return (
    <div className="jb-gap">
      <div className="jb-gap-heads">
        <Stat
          label="Found by both"
          value={summary.in_both}
          urls={lists?.in_both}
          filename={name("found-by-both")}
          // Absent on every cross-check saved before the list was kept. Saying
          // so beats an unexplained missing button on one tile of four.
          unavailable="re-run the cross-check to list these"
        />
        <Stat
          label="Rows in export"
          value={summary.frog_rows}
          // Deliberately never downloadable: this is the file the analyst
          // uploaded. Storing 23,500 rows to hand back their own export would
          // double the sidecar to reproduce something they already have.
          unavailable="your own export"
        />
        <Stat
          label="Pages we missed"
          value={summary.missed_pages}
          tone="bad"
          urls={lists?.missed_pages}
          filename={name("pages-we-missed")}
        />
        <Stat
          label="Sitemap orphans"
          value={summary.orphans}
          tone="warn"
          urls={lists?.orphans}
          filename={name("sitemap-orphans")}
        />
      </div>

      {summary.merged > 0 ? (
        <Alert
          type="success"
          showIcon
          message={`${summary.merged.toLocaleString()} pages merged into a new crawl.`}
          description="The original crawl is unchanged. Merged pages carry a low confidence score because an export has no HTML to classify from."
        />
      ) : (
        <Alert
          type="info"
          showIcon
          message="Nothing to merge — no new job was created."
          description="Every live, in-scope page in the export was already in the crawl."
        />
      )}

      {/* Each table's own rows, with the reason column that makes them
          actionable. The whole-file download below carries both sides at once;
          these two are for handing one direction to one person. */}
      <h4 className="jb-gap-h">
        Screaming Frog found, we did not
        <GapDownload rows={lists?.frog_only} jobId={jobId} side="frog" />
      </h4>
      <Table
        size="small"
        pagination={false}
        dataSource={rows(summary.frog_reasons, FROG_REASONS)}
        columns={[
          {
            title: "Reason",
            dataIndex: "reason",
            render: (value: string) => (
              <Tag color={value === "MISSED_PAGE" ? "error" : "default"}>{value}</Tag>
            ),
          },
          { title: "What it means", dataIndex: "meaning" },
          { title: "URLs", dataIndex: "count", align: "right" as const, width: 80 },
        ]}
      />

      <h4 className="jb-gap-h">
        We found, Screaming Frog did not
        <GapDownload rows={lists?.engine_only} jobId={jobId} side="engine" />
      </h4>
      <Table
        size="small"
        pagination={false}
        dataSource={rows(summary.engine_reasons, ENGINE_REASONS)}
        columns={[
          {
            title: "Reason",
            dataIndex: "reason",
            render: (value: string) => (
              <Tag color={value === "SITEMAP_ORPHAN" ? "warning" : "default"}>{value}</Tag>
            ),
          },
          { title: "What it means", dataIndex: "meaning" },
          { title: "URLs", dataIndex: "count", align: "right" as const, width: 80 },
        ]}
      />

      {/* The two directions need opposite fixes, and that is the whole point of
          reading them side by side. Said in words because a table of enum names
          does not say it. */}
      <p className="jb-dim jb-gap-note">
        The two gaps call for opposite fixes: a page Screaming Frog reached and we
        did not is missing from your sitemaps; a page only we found has no
        internal link pointing at it.
      </p>
    </div>
  );
}

/**
 * Download for one side of the gap, carrying its reason column.
 *
 * `MEANINGS` is written out rather than left as an enum, for the same reason
 * the whole-file CSV does it: the person who acts on the row is usually not the
 * person who ran the cross-check.
 */
function GapDownload({
  rows,
  jobId,
  side,
}: {
  rows?: { url: string; reason: string }[] | undefined;
  jobId: string;
  /** Which half of the gap this heading owns. */
  side: "frog" | "engine";
}): JSX.Element | null {
  if (!rows || rows.length === 0) return null;
  return (
    <a
      className="jb-stat-dl jb-gap-dl"
      href={`${API_BASE}/jobs/${encodeURIComponent(jobId)}/reconciliation.xlsx?side=${side}`}
      title={`Download these ${rows.length.toLocaleString()} URLs as a workbook, one sheet per reason`}
    >
      Download {rows.length.toLocaleString()}
    </a>
  );
}

function Stat({
  label,
  value,
  tone,
  urls,
  filename,
  unavailable,
}: {
  label: string;
  value: number;
  tone?: "bad" | "warn";
  /** The addresses behind the figure, when they were recorded. */
  urls?: readonly string[] | undefined;
  filename?: string;
  /** Why this figure has no list, when it has none. */
  unavailable?: string;
}): JSX.Element {
  const has = urls !== undefined && urls.length > 0;
  return (
    <div className={`jb-stat${tone ? ` jb-stat-${tone}` : ""}`}>
      <span className="jb-stat-v">{value.toLocaleString()}</span>
      <span className="jb-stat-l">{label}</span>
      {/* A figure with a list gets a button; one without says why rather than
          showing a control that cannot work. A disabled button with no
          explanation reads as a defect in the app. */}
      {has ? (
        <button
          type="button"
          className="jb-stat-dl"
          title={`Download these ${urls.length.toLocaleString()} URLs`}
          onClick={() => downloadCsv(filename ?? "urls.csv", toCsv(["url"], urls.map((u) => [u])))}
        >
          Download {urls.length.toLocaleString()}
        </button>
      ) : (
        unavailable && <span className="jb-stat-why">{unavailable}</span>
      )}
    </div>
  );
}
