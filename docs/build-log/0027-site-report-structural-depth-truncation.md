# Cycle 0027: Site report structural container filtering & print spooler fix

- **Date**: 2026-08-19
- **Scope**: Filter printable HTML site reports (`CrawlReport.tsx`) to structural container nodes (roots and nodes with children) rather than arbitrary raw row caps, fixing Windows Print Spooler crashes and shrinking PDFs from ~70 pages to ~14 pages.
- **Commit**: `aa95cb4`
- **Quality gate**: `1,236 passed`, `Total coverage: 95.19%`

## 1. Gate results

```
=== Format ===
PASSED: Format

=== Lint ===
PASSED: Lint

=== Type check ===
PASSED: Type check

=== Tests ===
Required test coverage of 85.0% reached. Total coverage: 95.19%
1236 passed, 1 warning in 100.12s
ALL GATES PASSED.
```

UI, separately: `tsc --noEmit` clean. Contract re-exported.

---

## 2. What landed

### `CrawlReport.tsx` — Structural Container Node Filtering

- **Problem**: Previously, `REPORT_ROW_LIMIT = 3_000` rendered the first 3,000 nodes in tree order into the printable `@media print` report. On large sites like `kinsta.com` (29,248 nodes), this produced a ~70 A4 page document that caused `Microsoft Print to PDF` (Windows Print Spooler) to abort with *"Printing failed. Please check your printer"*.
- **Discovery**: Naive depth filtering (`depth <= 2`) still produced 6,026 rows (~134 pages) because 3,456 leaf pages sit at depth 1 or 2 (e.g. `/blog/post-1`).
- **Fix**: Filter printable rows to **structural container nodes** (`node.kids.length > 0` OR `depth === 0` root tabs).
- **Result**:
  - `kinsta.com`: 29,248 total nodes $\rightarrow$ **611 structural section rows (~14 pages)**.
  - `highradius.com`: 15,418 total nodes $\rightarrow$ **1,700 structural section rows (~38 pages)**.
  - `rankuno.com`: 89 total nodes $\rightarrow$ **13 structural section rows (~1 page)**.
  - Both `Microsoft Print to PDF` and `Save as PDF` print cleanly without memory or spooler crashes.
