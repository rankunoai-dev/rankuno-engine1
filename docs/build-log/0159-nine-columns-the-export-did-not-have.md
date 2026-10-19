# Cycle 0159: Nine columns the export did not have

- **Date**: 2026-10-19
- **Scope**: New feature, phase 1 of the approved downloadable-report field plan (the field list from the user's screenshot). Nine columns are appended after the last existing column of the xlsx "All URLs" sheet. Every value is derived at export time from fields the profile already stores. Nothing is persisted, requested or fetched, and no field is added to `FullPageIntelligenceProfile`.
- **Numbering**: the highest entry on disk was 0157, an untracked file from another session. This entry takes 0159, because origin/main took 0158 for the per-category download. No number is reserved.
- **Commit**: none. Nothing is committed; the working tree is dirty (§7).
- **Quality gate**: **RED.** `verify.ps1` full run ended `VERIFICATION FAILED` on Format and Lint. Both failures come from `scripts/test_gsc_credentials.py`, an untracked file owned by another session. This cycle's files pass ruff and mypy. The cycle is complete only once that file is fixed, moved or removed and the gate is re-run green. Do not read this entry as a green cycle.

## 1. Gate results

The gate figures below were reported by the implementing agent. The scribe did not re-run the full gate (it takes about 13 minutes). The scribe's own commands are the two ruff runs and `drift_check.py` quoted at the end of this section.

| Stage | Result (reported) |
| :--- | :--- |
| ruff format | **FAILED**: `1 file would be reformatted`, the file is `scripts/test_gsc_credentials.py` (untracked, another session) |
| ruff check | **FAILED**: 6 errors, all in `scripts/test_gsc_credentials.py` |
| mypy --strict | `Type check PASSED` |
| coverage | `TOTAL 17962 966 3886 277 94%`; `Required test coverage of 85.0% reached. Total coverage: 93.77%` |
| pytest | `4579 passed, 2 skipped, 2 warnings in 760.70s (0:12:40)` |
| UI tests inside the gate | `Test Files 58 passed (58)`, `Tests 787 passed (787)` |
| `npm run contract` | `UI contract is up to date.` |
| `npx tsc --noEmit` | exit 0 |
| `npx vitest run` | 58 files / 787 tests passed |
| `npm run build` | built in 16.86s (pre-existing chunk-size warning) |
| `drift_check.py` (implementer) | PASSED across 257 md files |

The scribe re-ran two checks, against the current tree:

`ruff format --check` on `scripts/test_gsc_credentials.py`, `report_columns.py`, `reports.py` and `tests/modules/seo/page_classifier/`:

```
76 +     print(f"✅  Found {len(properties)} propert{'y' if len(properties) == 1 else 'ies'}:")
77 |     for p in properties:
   |

1 file would be reformatted, 11 files already formatted
```

`ruff check` on the same tree, plus the three new test files:

```
S310 Audit URL open for permitted schemes. Allowing use of `file:` or custom schemes is often unexpected.
  --> scripts\test_gsc_credentials.py:49:14
...
Found 6 errors.
[*] 3 fixable with the `--fix` option (1 hidden fix can be enabled with the `--unsafe-fixes` option).
```

Every reported error is in the other session's file. The scribe did not run `-Fix` and did not edit that file. The implementer also did not edit or delete it. The follow-up is in §8.

## 2. What landed

### The columns

The xlsx "All URLs" sheet now has 21 columns, A to U. Columns A to L are unchanged in order and content. The nine appended columns are M to U:

| Col | Header | Rule (as implemented in `report_columns.py`) |
| :--- | :--- | :--- |
| M | Found Via | No discovery flag set: "Not recorded (older crawl)". Otherwise `dom_link` gives "Crawl link", else `cms_api` gives "CMS", else `sitemap` gives "Sitemap". |
| N | In Sitemap | `discovery_sources.sitemap`: Yes or No. Legacy label if no flags are set. |
| O | Unique Inlinks | `inbound_internal_links_count`. Already de-duplicated per linking page at discovery (`discovery.py` ~1009, `async_discovery.py` ~995). A page the crawl never fetched keeps its real count, because links to it were read from other pages. Legacy label when `fetch_outcome` is `None`. |
| P | Unique Outlinks | `outbound_internal_links_count`. Blank for not-fetched and no-response pages, because the count is unknown and not zero. A fetched page with 0 links shows 0. Legacy label when `fetch_outcome` is `None`. |
| Q | Orphan | Yes when `sitemap` AND NOT `dom_link` AND NOT `cms_api` AND `inbound_internal_links_count == 0`. Otherwise No. Legacy label if no flags. GSC is not used. |
| R | GSC CTR (decimal) | `(gsc_clicks or 0) / gsc_impressions`, stored as a float, number format `0.000` (23 / 1000 shows as 0.023). Blank when impressions is `None` (GSC not joined) or `0`. |
| S | Final URL | `final_url`. Blank when not fetched. Legacy label when `fetch_outcome` is `None`. |
| T | Indexability | The stored enum value, as-is. Legacy label when `fetch_outcome` is `None`. Not re-judged. |
| U | Indexability Reason | The stored reason, as-is. Blank when none was stored. Legacy label when `fetch_outcome` is `None`. |

The existing "GSC CTR %" (column H, percentage-style, e.g. 2.3) is unchanged. The decimal column sits beside it, not in place of it.

### Design decisions

- **Derivation, not storage.** The cells are computed at export. The profile, its schema and the crawl are untouched. The export therefore cannot disagree with the crawl by re-reading the site.
- **Found Via precedence: crawl link, then CMS, then sitemap.** A followed link is the strongest evidence that the site uses the page. A sitemap entry alone is the site asserting that the page exists. Overlaps are not hidden: the "In Sitemap" column still shows them. Tested for dom+sitemap and cms+sitemap overlaps.
- **"Not recorded" is inferred from all-false flags.** A profile with all three discovery flags false is treated as a result from before the flags were stored. The cells that depend on the flags say so and do not report "No".
- **Blank, not zero, wherever the crawl did not measure.** Unique Outlinks is blank for not-fetched and no-response pages. GSC CTR is blank at zero or absent impressions, because `0.000` would claim a measured zero click rate.
- **Orphan is not the navigation `ORPHANED` status.** These are three different things in the code, and the workbook must not present one as another:
  - Navigation `ORPHANED` (`navigation_context.py` ~65/~100) means no sitemap entry and no link. It is read from the navigation tree.
  - Navigation `SITEMAP_ONLY` (`navigation_context.py` ~64/~92) is a different navigation status.
  - `SITEMAPS_ORPHAN_URLS` (`audit_export.py` ~188) means a sitemap entry and no `dom_link`. It is an audit export bucket.
  - The new Orphan column is a plain count from the discovery graph. It is Yes when a sitemap lists the URL, no crawled link reaches it, no CMS record names it and no page links to it. It can disagree with all three of the above, and it is labelled separately.
- **GSC is not used for Orphan.** Absence of GSC data is not evidence of exclusion (`schemas.py` ~557-563). A URL with no impressions is not an orphan for that reason.
- **Indexability is shown, not judged.** The stored verdict and reason are copied as-is. `indexability_of()` is unchanged.
- **Column order is part of the contract.** `TRAILING_HEADERS` is a fixed tuple, and a test pins it.
- **The PDF is unchanged.** It keeps 12 columns and a total width of 774pt. The xlsx and PDF therefore no longer carry the same "All URLs" columns (§5).

### Modules

- **New `src/modules/seo/page_classifier/report_columns.py`** (226 lines). Holds the derivation helpers, `TRAILING_HEADERS`, `CTR_DECIMAL_HEADER`, `CTR_DECIMAL_FORMAT` and `trailing_cells()`. Reuses `fetch_status.py` labels and `http_status_label()`. Coverage: 100% line and branch.
- **`src/modules/seo/page_classifier/reports.py`** (+13 / -1). `_sheet_all_urls` appends the trailing headers and cells, and sets number format `0.000` on the CTR decimal cell. `generate_pdf`, `_pdf_row` and `_PDF_COLUMN_WIDTHS` are untouched.
- **New tests**:
  - `tests/modules/seo/page_classifier/report_profile_factory.py`: builds profiles directly. No crawl is run.
  - `tests/modules/seo/page_classifier/test_report_columns.py`: 33 test functions.
  - `tests/modules/seo/page_classifier/test_report_columns_workbook.py`: 11 test functions. Checks the workbook cells and the number format.

### Tests that pin unchanged behaviour

Existing tests still pin columns A to L, the PDF's 12 columns and widths, the "By Indexability" and "By HTTP Status" sheets, and `indexability_of()`. The implementer reports these as passing in the full pytest run (§1).

## 3. Bugs found and fixed

The implementing agent's report lists no bugs found on the way, and this entry does not claim one. The following came up while closing the cycle:

1. **Gate red from another session's file.** `scripts/test_gsc_credentials.py` is untracked and owned by another session. It fails ruff format (1 file) and ruff check (6 errors). It is not part of this cycle and was neither edited nor deleted. It blocks the gate for this cycle as well as for any other.
2. **A README paragraph became wrong.** The URL-export paragraph in `README.md` said the PDF is "the same 'All URLs' columns" as the workbook. This cycle makes that false. Fixed in the same change (§4).
3. **The user's field list has one item that does not exist in the repo.** The screenshot's "column L Page Type list" is not in the codebase. In the report, column C is Page Type and is the 14-member `PrimaryPageType` enum. Column L is Reachability Tier. No list in the repo matches the screenshot's description of column L. Recorded as a spec mismatch, not a code defect. The implementer did not build a list for it.

## 4. Documentation changes in this cycle

- `docs/build-log/README.md`: index row for 0159 added.
- `README.md`: the paragraph describing the xlsx and PDF URL exports now says the xlsx "All URLs" sheet carries nine trailing columns after the twelve shared ones, and the PDF does not.
- `docs/ARCHITECTURE.md`: the `reports.py` entry now names `report_columns.py` as the derivation module for the trailing columns.

No ADR was added and no ruling in CLAUDE.md §6 changed. No known gap in CLAUDE.md §8 was closed by this cycle.

## 5. Corrections

- **Build-log 0124 described the PDF and the workbook as having the same "All URLs" columns.** That was true when 0124 was written, because the workbook had the same 12 columns. It is now superseded for the xlsx, not wrong about 0124's day. 0124 is not edited. The current-state wording is corrected in `README.md` (§4).
- **Build-log 0156 §6 wording is unaffected.** Its "Not recorded (older crawl)" label is reused here as the legacy label for the new columns. No statement in 0156 is changed by this cycle.

## 6. Explicitly not done

Each item is a declared gap, not an implemented contract. The reason is given for each.

- **Canonical Status (Self / Elsewhere / Missing) and Canonical URL.** Not built. The pipeline stores `""` when no canonical is declared (`discovery.py` ~898). But `cascading_pipeline.py` ~316 writes `canonical_url = evidence.canonical_url or evidence.url`. So an undeclared page is stored the same way as a self-canonical, and the export cannot tell them apart from stored data. The fix needs a new stored `canonical_declared` field and a change to the ADR 0002 contract. That change is to be approved separately.
- **Canonical Multiple.** Not built. Only one canonical is captured per page.
- **Top Query.** Not built. Query-level GSC data is not on the profile. It needs a new fetch.
- **Breadcrumb Parent URL.** Not built.
- **Unique Content Inlinks.** Not built. There is no content-region link classification, so the count cannot be split from the total.
- **Every brand, hub and service field.** Not built.
- **Every GA4 field.** Not built.
- **The GSC 10,000-row truncation.** Not fixed. It is on the fetch path, which is outside this cycle's bounds.
- **A visual check in Excel.** Not done. The `0.000` format was confirmed with openpyxl's `number_format`, not by viewing the sheet.
- **A PDF change.** None. The PDF keeps its 12 columns.
- **Any change to "By Indexability", "By HTTP Status" or `indexability_of()`.** None.
- **Any stored field or contract change.** None. `FullPageIntelligenceProfile` and ADR 0002 are untouched.

## 7. Files changed

- New: `src/modules/seo/page_classifier/report_columns.py`
- Modified: `src/modules/seo/page_classifier/reports.py`
- New: `tests/modules/seo/page_classifier/report_profile_factory.py`
- New: `tests/modules/seo/page_classifier/test_report_columns.py`
- New: `tests/modules/seo/page_classifier/test_report_columns_workbook.py`
- Docs: this entry; `docs/build-log/README.md` (index row); `README.md` (URL-export paragraph); `docs/ARCHITECTURE.md` (`reports.py` entry).

The working tree also holds changes from other sessions that are not part of this cycle: `docs/build-log/0157-leaf-clicks-off-the-right-edge.md`, `scripts/test_gsc_credentials.py`, the `rankuno-ui` tree files, and the untracked `.agents/` and `.codex/` directories.

## 8. Follow-ups

- **Other session (owner of `scripts/test_gsc_credentials.py`)**: fix the six ruff errors and the one formatting issue, or move the file out of the tree. Then re-run `verify.ps1`. Until that is done, the gate is red and this cycle is not complete.
- **Lead / user**: decide whether the Canonical Status and Canonical URL columns go ahead. They need the `canonical_declared` field and an ADR 0002 contract change, which is a separate approval.
- **User**: open one exported xlsx in Excel and check the nine columns and the `0.000` CTR format by eye.
- **User**: confirm the "Not recorded (older crawl)" rule. It assumes that a profile with all three discovery flags false came from a crawl that did not record its sources. That assumption is not verified against every legacy stored result.
- **User**: confirm whether the screenshot's column L list is wanted. The repo has no such list.

## Unverified

- The tests build profiles directly. No live crawl was run, and no real downloaded workbook was opened.
- No visual check of the new columns or the `0.000` format in Excel (format confirmed via openpyxl `number_format` only).
- Whether `extract_page_links` excludes self-links. If it does not, a page could count itself as an inlink, and Orphan would be wrong for that page. Unverified.
- The exact `cap_links` limit. Not confirmed in this cycle.
- Whether `discovery_sources` was persisted in every legacy result. The "Not recorded" rule assumes that all-false flags mean the result is legacy.
- The gate figures in §1 (other than the two ruff runs and `drift_check.py`) are as reported by the implementer. The scribe did not re-run pytest, mypy, vitest or the build.
