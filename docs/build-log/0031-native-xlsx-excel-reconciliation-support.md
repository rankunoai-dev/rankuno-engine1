# Cycle 0031: Native .xlsx Excel Spreadsheet Support in Reconciler & API

- **Date**: 2026-08-20
- **Scope**: Add `openpyxl` as a core dependency and enable native `.xlsx` binary spreadsheet parsing in `load_screaming_frog_export()` and `POST /api/v1/jobs/{job_id}/reconcile/screaming-frog`.
- **Commit**: `d999041` (Engine & Endpoint) & `openpyxl` dependency declared.
- **Quality gate**: `1,329 passed`, `Total coverage: 95.37%`

## 1. Gate results

```
=== Format ===
PASSED: Format

=== Lint ===
PASSED: Lint

=== Type check ===
PASSED: Type check

=== Tests ===
Required test coverage of 85.0% reached. Total coverage: 95.37%
1329 passed in 98.42s
ALL GATES PASSED.
```

UI Component Tests: `23 passed` across 4 test suites.

---

## 2. What landed

### Native `.xlsx` Excel Ingestion & Auto-Format Detection

- **Declared Dependency (`pyproject.toml`)**: Declared `"openpyxl>=3.1.0,<4.0.0"` in `dependencies` so clean checkouts natively support `.xlsx` files without `ImportError` exceptions.
- **Streaming Ingestion (`_rows_from_xlsx`)**: Uses `openpyxl.load_workbook(io.BytesIO(body), read_only=True, data_only=True)` to parse 50 MB+ Excel spreadsheets line-by-line without memory inflation.
- **Header Lookup & Auto-Detection**:
  - Automatically identifies `.xlsx` files via extension or binary Zip magic header (`PK\x03\x04`).
  - Maps spreadsheet headers (`Address`, `Status Code`, `Content Type`, `Indexability`, `Redirect URL`, `Unique Inlinks`, `Crawl Depth`) into `ScreamingFrogRow` instances.
- **API Endpoint Support**: `POST /api/v1/jobs/{job_id}/reconcile/screaming-frog` accepts both binary `.xlsx` and text `.csv` payloads natively.
