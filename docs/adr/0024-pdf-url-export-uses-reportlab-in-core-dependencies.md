# ADR 0024: The PDF URL export uses reportlab, added to core dependencies

- **Status**: Accepted
- **Date**: 2026-09-29
- **Deciders**: AI Lead, Lead AI Systems Engineer

---

## Context

`GET /jobs/{job_id}/urls.xlsx` already gives an operator every URL a crawl found, one click from
the job-row menu, no panel to open first. The same list as a PDF was requested as its sibling: a
flat, printable "every URL this crawl found", for the case an operator wants to attach it to an
email or a client deliverable rather than open a spreadsheet.

Two Python PDF options were considered.

## Decision

### 1. reportlab, not weasyprint

**weasyprint** renders HTML/CSS to PDF, which would have let the PDF reuse `CrawlReport.tsx`'s own
markup. It was rejected: weasyprint depends on Pango, Cairo and GDK-PixBuf — an OS-level GTK3
runtime — which has no plain `pip install` path on Windows. ADR 0004 commits this engine to a local
Windows workstation first; a dependency that needs a separately-installed native runtime is exactly
the complication that ADR exists to avoid, and it would be the only dependency in this project with
that shape.

**reportlab** ships as a pure Python wheel (`reportlab>=4.0,<5.0`, with `Pillow` pulled in
transitively) — `pip install` and nothing else, on the same footing as `openpyxl`, `psycopg[binary]`
and every other dependency already in this file.

The tradeoff taken: reportlab draws a table by hand (`SimpleDocTemplate` + `Table` + `Paragraph`
cells), rather than reusing existing HTML/CSS. `MasterURLReport.generate_pdf`
(`src/modules/seo/page_classifier/reports.py`) duplicates the "All URLs" sheet's eleven columns as
a second, hand-built row-construction path (`_pdf_row`) rather than sharing one with
`_sheet_all_urls` — openpyxl accepts typed values, reportlab's `Paragraph` cells need pre-formatted
text, so the two cannot share a single per-page transform without one of them going through a
needless string round-trip. Accepted: eleven columns is a small enough surface that a test
(`TestGeneratePdf::test_row_matches_the_all_urls_sheet_column_for_column`,
`tests/modules/seo/page_classifier/test_reports.py`) pinning the two outputs to agree is cheaper
than a shared abstraction would be.

### 2. Core dependency, not the `seo` extra

`reportlab` is declared in `pyproject.toml`'s core `dependencies`, beside `openpyxl`, not in the
`seo` extras block. This follows `openpyxl`'s own precedent exactly: `reports.py` is a
`modules/seo/page_classifier` component, but `download_urls_workbook` and `download_urls_pdf`
(`src/api/server.py`) import it directly from `src/api`, which only ever installs core. Moving
`reportlab` to the `seo` extra would make `src/api/server.py` fail to import on a bootstrap that did
not also install `seo` — the same failure `openpyxl`'s placement already avoids.

This is recorded as an open question, not a settled one, because it works against
`pyproject.toml`'s own comment on the core dependency list: "Keep this list MINIMAL — the core layer
must stay importable without any domain/vendor SDK installed. Domain libraries belong in the
optional extras below." Two dependencies now sit in core specifically because a `seo`-module file is
imported from `src/api` without the `seo` extra as a precondition. The clean fix is either (a) move
`reports.py`'s two-dependency surface behind a lazy import inside the two route handlers so `seo` can
stay optional again, or (b) declare `src/api` as requiring the `seo` extra outright and stop treating
"importable with core alone" as a guarantee `reports.py`'s callers can rely on. Neither is done here;
this ADR is precedent for a third dependency landing the same way, and whoever adds one should read
this paragraph, not just the "keep it MINIMAL" comment, before doing the same thing a third time.

`reportlab` ships no `py.typed` marker (confirmed: no such file under its installed package), so
`mypy --strict` needs the same `ignore_missing_imports` override already carried for `openpyxl` and
`celery`.

## Alternatives considered

**weasyprint.** Rejected per Decision 1 — the native-runtime requirement contradicts ADR 0004.

**Share one row-construction method between `.xlsx` and `.pdf`.** Rejected per Decision 1's tradeoff
note: the two libraries want differently-typed cell values, and a shared method would need to route
through string formatting either way, at which point it is not actually one method's worth of logic
being saved.

**`window.print()` on the existing `CrawlReport.tsx` markup.** Rejected before this ADR, not by it —
see commit `aa95cb4`: it fails outright above roughly 3,000 rows, which is well inside ADR 0001's
20k–500k URL scale target.

## Consequences

**Accepted.** Two core dependencies (`openpyxl`, `reportlab`) now exist only because
`reports.py` is reachable from `src/api` without the `seo` extra — recorded above as an open
question this ADR does not resolve.

**Accepted.** `_pdf_row` and `_sheet_all_urls` are two independent per-page transforms over the same
eleven columns, held in agreement by a test rather than by sharing code.

**Noted, not solved.** `reportlab`'s `Table` flowable builds its whole row list in memory before
`SimpleDocTemplate.build` lays it out — there is no streaming or paginated construction path, unlike
`DiskJobStore.iter_result_page_urls`'s bounded-memory read (ADR 0023's Consequences). At ADR 0001's
500k-URL upper bound, with eleven short `Paragraph` cells per row, this has not been measured against
a crawl anywhere near that size. The `.xlsx` export carries the same shape of open question — see
build-log 0102's write-only-vs-normal-`Workbook` flag — and this one is recorded here rather than
assumed safe by analogy.
