# Cycle 0163: Link and breadcrumb facts recorded at fetch (Phase 1b)

- **Date**: 2026-10-19
- **Scope**: Record canonical declarations, body-region content link counts, and breadcrumb parent URLs at fetch time (Phase 1b, ADR 0039 amending ADR 0002), and expose 5 trailing columns in the xlsx All URLs sheet.
- **Commit**: uncommitted at time of writing
- **Quality gate**: Ruff clean, mypy 190 files clean, drift check clean, vitest 824 passed (61 files), targeted pytest suites green.

---

## 1. Gate results

- **Format**: `ruff format --check .` — 725 files already formatted.
- **Lint**: `ruff check .` — All checks passed.
- **Type check**: `mypy src` — Success: no issues found in 190 source files.
- **UI contract & tests**: `scripts/export_ui_contract.py --check` clean; `vitest run` 824 passed across 61 test files; `tsc -b && vite build` clean.
- **Drift check**: `scripts/drift_check.py` PASSED across 266 markdown files.

---

## 2. What landed

### 2.1 Stored link and breadcrumb facts (ADR 0039)
Five optional fields were added across the pipeline contract (`DiscoveredNode`, `PageEvidence`, and `FullPageIntelligenceProfile`), defaulting to `None` so existing stored crawls render as "Not recorded (older crawl)" rather than a misleading zero:
1. `canonical_declared: bool | None`: `True` if at least one usable canonical tag was declared; `False` if HTML was fetched but declared none (or only unusable tags); `None` if unfetched/non-HTML.
2. `canonical_link_count: int | None`: Total non-empty canonical tags found in `<head>` (detects the duplicate canonical defect).
3. `body_link_count: int | None`: Count of outbound links inside the body region (`<main>` or `<article>`, falling back to whole document if neither is present).
4. `breadcrumb_parent_url: str | None`: URL of the breadcrumb step immediately preceding the page (`""` if HTML was read but no parent exists; `None` if unread).
5. `unique_content_inlinks: int | None`: Distinct source pages whose content/body region links to this page (excluding sitewide headers/footers/navigation).

### 2.2 Report columns export
`src/modules/seo/page_classifier/report_columns.py` appends 5 trailing columns to the xlsx "All URLs" sheet:
- `Canonical Status`: `Self`, `Elsewhere`, `Multiple`, or `Missing` (or blank if unread).
- `Canonical URL`: Target URL verbatim from the first valid canonical tag.
- `Canonical Links`: Integer count of canonical link tags.
- `Unique Content Inlinks`: Inlinks originating strictly within content regions.
- `Breadcrumb Parent URL`: Preceding breadcrumb URL step.

All existing columns (A–L byte-stable core columns and the 9 Phase 1 derived columns) remain undisturbed.

---

## 3. Design decisions

1. **Renumbering to ADR 0039**: ADR 0038 was claimed concurrently by the GA4 multi-tenant credential feature (`0038-ga4-access-is-a-separate-read-only-credential-per-org.md`). The link and breadcrumb facts ADR was cleanly renumbered to ADR 0039.
2. **Golden snapshot projection exclusion**: Added `LINK_FIELDS` to snapshot projection exclusion in `tests/modules/seo/test_golden_extract_at_fetch.py` so existing golden hash assertions remain byte-identical without test churn.

---

## 4. Bugs found and fixed

- **Empty canonical href edge case**: A tag like `<link rel="canonical" href="">` counts in `canonical_link_count` (1 defect), but sets `canonical_declared = False` to prevent it from defaulting to `Self`.
- **D205 docstring lints**: Fixed docstring formatting in unit test files to adhere to strict ruff checks.

---

## 5. Explicitly not done

- **PDF report modification**: The 12-column PDF report layout is strictly preserved.
- **Phase 2 fields**: Brand code, service segment, and hub slug mapping deferred to Phase 2.
