# Cycle 0079: Sixteen measured, ninety-four not

- **Date**: 2026-09-08
- **Scope**: Plan work items P0-4 (engine adapter, `src/modules/seo/page_classifier/audit_export.py`) and P0-6 (import-boundary test, `tests/modules/seo/test_import_boundary.py`) of `docs/DELIVERABLES_IMPLEMENTATION_PLAN.md` §4 under ADR 0011. `to_audit_dataset(profiles, *, produced_at=None) -> AuditDataset` reads `FullPageIntelligenceProfile` and writes the shared contract with `source=ENGINE`, 16 issues `MEASURED`, 94 `NOT_MEASURED`, `links=()`. The one-direction ast test from cycle 0077 was folded into the new boundary test. 45 new tests.
- **Commit**: the code landed in `b3d7105` ("feat(seo,core,api): GSC account profiles and deliverables boundary", 86 files, 2026-09-08 18:20 +0530) — an unrelated session's sweep commit made *after* the feature-builder reported "nothing committed". This entry and the README / ARCHITECTURE / plan edits are uncommitted at time of writing.
- **Quality gate**: **RED** — `1 failed, 2012 passed, 1 skipped` Python / `232 passed` UI / `Total coverage: 93.91%`. The one failure is `tests/api/test_server.py::TestCancel::test_the_reason_says_the_thread_may_survive`, one of the three named in [build-log 0078 §1.2](0078-the-fields-that-never-left-the-call-site.md) as nondeterministic and belonging to `src/api/server.py`, which this cycle did not touch. Per CLAUDE.md §1.6 this task is **not complete** while the gate is red; attribution is unchanged from 0078.

**Origin.** Plan §4 rows P0-4 and P0-6; [0073 §8.3](0073-not-measured-is-a-value.md) and [0074 §6](0074-absent-is-not-empty.md) both flagged P0-6 as the missing enforcement behind ADR 0011 decision 1 ("a test enforces it"). Step 3 was held with the operator on 2026-09-08 and produced two rulings, D-A and D-B (§3.1, §3.2). No new ADR: both are applications of ADR 0011 decision 5, "not measured is a value".

---

## 1. Gate results

### 1.1 Feature-builder's run (verbatim, before `b3d7105`)

`verify.ps1 -Fix` tail. The `-Fix` reformatted only `audit_export.py` (one lambda joined onto one line); ruff format, ruff check and `mypy --strict src` passed:

```
 Test Files  21 passed (21)
      Tests  232 passed (232)
PASSED: UI Component Tests

VERIFICATION FAILED: Tests
Do not report this task as complete.
```

Python stage of the same gate (`pytest --cov=src --cov-report=term-missing`, rerun to expose the summary):

```
TOTAL                                                           7779    381   1948    139    94%
Required test coverage of 85.0% reached. Total coverage: 93.91%
FAILED tests/api/test_server.py::TestCancel::test_the_reason_says_the_thread_may_survive
1 failed, 2012 passed, 1 skipped, 1 warning in 159.22s (0:02:39)
```

`tests/api/test_server.py` alone, feature-builder's run: `114 passed, 0 failed`.

The four files this cycle owns or touched, feature-builder's run:

```
.venv/Scripts/python.exe -m pytest tests/modules/seo/test_audit_export.py tests/modules/seo/test_import_boundary.py tests/modules/seo/test_audit_contract.py tests/modules/seo/test_screaming_frog_adapter.py -q
93 passed in 18.23s
```

### 1.2 Docs-scribe's runs (after `b3d7105`)

Same four files, `-q -p no:cacheprovider`: `93 passed`. Collection, per file:

```
tests/modules/seo/test_audit_export.py: 36
tests/modules/seo/test_import_boundary.py: 9
```

45 new tests in total, as reported; the per-file split in the feature-builder's report (37 + 8) was wrong by one in each direction (§5.6).

Full gate, docs-scribe's run on the `b3d7105` tree (`verify.ps1`, no `-Fix`; exit 1). Verbatim, ANSI stripped:

```
=== Format ===
292 files already formatted
PASSED: Format

=== Lint ===
All checks passed!
PASSED: Lint

=== Type check ===
Success: no issues found in 68 source files
PASSED: Type check
```

```
src\modules\seo\page_classifier\audit_export.py                  103      1     28      2    98%   204->202, 207
```

```
TOTAL                                                           7779    381   1948    139    94%

32 files skipped due to complete coverage.
Required test coverage of 85.0% reached. Total coverage: 93.91%
=========================== short test summary info ===========================
FAILED tests/api/test_server.py::TestStartupRecovery::test_orphaned_jobs_are_failed_on_startup
1 failed, 2012 passed, 1 skipped, 1 warning in 133.34s (0:02:13)
FAILED: Tests
```

```
 Test Files  21 passed (21)
      Tests  232 passed (232)
PASSED: UI Component Tests

VERIFICATION FAILED: Tests
Do not report this task as complete.
```

Same totals as the feature-builder's run (2,012 passed, 1 skipped, 93.91%), but a **different** member of the 0078 §1.2 trio failed: `test_orphaned_jobs_are_failed_on_startup` here, `test_the_reason_says_the_thread_may_survive` there. `audit_export.py` is at 98%; the two uncovered branches (`204->202`, `207`) are the empty-`oversized` early return in `_over_50k` and its comprehension — reachable only when a sitemap grouping exceeds 50k, which the tests do cover in the positive direction.

`tests/api/test_server.py` alone, five docs-scribe runs on the same tree:

| Run | Result |
| :--- | :--- |
| 1 | `FAILED ...::TestStartupRecovery::test_orphaned_jobs_are_failed_on_startup` |
| 2 | exit 0 (all passed; count suppressed by a doubled `-q`) |
| 3 | exit 0 (same) |
| 4 | exit 0 (same) |
| 5 | `FAILED ...::TestCancel::test_cancelling_frees_the_slot` — `1 failed, 113 passed, 1 warning in 68.64s` |

The feature-builder's "114 passed, 0 failed" for the file alone is therefore reproducible but not reliable; every failure seen belongs to the three-test set in 0078 §1.2, and none names a file this cycle changed.

### 1.3 The red test is not this cycle's

`test_the_reason_says_the_thread_may_survive` is the third of the three tests [0078 §1.2](0078-the-fields-that-never-left-the-call-site.md) traced to the daemon-thread orphan recovery in `src/api/server.py`'s `lifespan`. This cycle touched no file under `src/api/` or `tests/api/`; `audit_export.py` is imported by nothing outside its own tests (`page_classifier/__init__.py` was not changed). What has changed since 0078: those `server.py` / `test_server.py` edits are no longer "another session's uncommitted edits" — `b3d7105` committed them along with this cycle's files. The failure is now in `HEAD`, and the handoff in 0078 §8.1 stands with that amendment.

### 1.4 Drift check

Feature-builder's run, before this entry and the doc edits existed:

```
--- Drift Audit Results ---
PASSED: no drift detected across 140 markdown files.
  - all relative links resolve
  - all domain modules documented
  - all skill directories populated
```

Docs-scribe's run after this entry and the README / ARCHITECTURE / plan / index edits (`.\.venv\Scripts\python.exe scripts\drift_check.py`, exit 0):

```
Running Architecture & Documentation Drift Audit...

--- Drift Audit Results ---
PASSED: no drift detected across 150 markdown files.
  - all relative links resolve
  - all domain modules documented
  - all skill directories populated
```

The count moved from 140 to 150 because `b3d7105` tracked entries 0072–0078 and the plan, not because of this entry. The note from 0078 §1.3 still applies: `drift_check.py` walks `git ls-files "*.md"`, so this untracked entry is outside its link check until committed. The four relative links this entry adds (0073, 0074, 0077, 0078), the index link in `docs/build-log/README.md`, and the two `docs/build-log/0079-...` links from `README.md` and `docs/ARCHITECTURE.md` were checked by hand with `test -f` and resolve.

---

## 2. What landed

### 2.1 `src/modules/seo/page_classifier/audit_export.py` — 292 lines

The only file in `page_classifier` that imports `contracts`. Public surface: `to_audit_dataset`, `AuditExportError`, `STATUS_RE`, `SITEMAP_LIMIT`, `NOT_MEASURED_REASONS`, and three note constants.

**What is measured.** One rule per issue over one profile; a rule is a `Callable[[FullPageIntelligenceProfile], bool]` in `_RULES`, plus one crawl-wide count for the 50k sitemap ceiling:

| Issue | Read from | Rule |
| :--- | :--- | :--- |
| `SITEMAPS_URLS_NOT_IN_SITEMAP` | `indexability`, `discovery_sources.sitemap` | indexable and not sitemap-discovered |
| `SITEMAPS_ORPHAN_URLS` | `discovery_sources` | sitemap-discovered and never DOM-linked |
| `SITEMAPS_NON_INDEXABLE_URLS_IN_SITEMAP` | `discovery_sources.sitemap`, `indexability` | sitemap-discovered and `NOINDEX` / `CANONICALISED_AWAY` / `NOT_A_PAGE` (`UNKNOWN` excluded: never fetched is not non-indexable) |
| `SITEMAPS_XML_SITEMAP_OVER_50K_URLS` | `sitemap_source` | every URL whose grouped sitemap listed `> 50_000` profiles; `== 50_000` is not over |
| `DIRECTIVES_NOINDEX` | `indexability` | `NOINDEX` |
| `CANONICALS_CANONICALISED` | `indexability` | `CANONICALISED_AWAY` |
| `RESPONSE_CODES_3XX_REDIRECTION` | `redirect_chain` | length ≥ 1 |
| `RESPONSE_CODES_INTERNAL_REDIRECT_CHAIN` | `redirect_chain` | length ≥ 2 |
| `RESPONSE_CODES_INTERNAL_CLIENT_ERROR_4XX` | `indexability_reason` via `STATUS_RE` | `NOT_A_PAGE` and reason starts `Answered 4NN.` |
| `RESPONSE_CODES_INTERNAL_SERVER_ERROR_5XX` | same | `Answered 5NN.` |
| `URL_UPPERCASE` | raw `url` | any uppercase in path or query |
| `URL_UNDERSCORES` | raw `url` | `_` in path |
| `URL_PARAMETERS` | raw `url` | non-empty query |
| `URL_MULTIPLE_SLASHES` | raw `url` | `//` in path |
| `URL_REPETITIVE_PATH` | raw `url` | a path segment repeats, case-folded |
| `URL_CONTAINS_SPACE` | raw `url` | ` ` or `%20` anywhere |

The URL rules read the **raw** `profile.url`, because `normalize_url` lowercases, collapses slashes and strips parameters — the exact defects the rules exist to find. The *key* each hit is recorded under is the normalised one, so a duplicate raw URL that carries a defect the surviving spine entry lacks still registers (`test_url_rules_read_the_raw_url_and_report_the_normalised_key`, `test_duplicates_collapse_to_one_page_and_issues_union`).

**Sitemap gate.** If no profile in the input has `discovery_sources.sitemap == True`, all four `SITEMAPS_*` ids become `NOT_MEASURED` with `SITEMAP_NOT_READ_NOTE` on the dataset. Without this, a crawl of a site with no sitemap would flag every indexable page as "not in sitemap", which is the RAE failure mode ("absent input rendered as a finding") in mirror image. With a sitemap read, `SITEMAP_TRUNCATION_NOTE` is stamped instead: the crawl page budget can truncate a sitemap below 50k, so an empty over-50k set is not proof.

**Everything else** is `NOT_MEASURED` with `frozenset()`, and `notes` carries one line per category naming why (`NOT_MEASURED_REASONS`, 14 categories including the four partly-measured ones). Per-category counts from a docs-scribe probe against the shipped module, one profile with a sitemap:

| Category | Rows | Measured | Not measured |
| :--- | ---: | ---: | ---: |
| `RESPONSE_CODES_INTERNAL` | 7 | 4 | 3 |
| `URL_ISSUES` | 6 | 6 | 0 |
| `SITEMAPS` | 4 | 4 | 0 |
| `CANONICALS` | 10 | 1 | 9 |
| `DIRECTIVES` | 2 | 1 | 1 |
| `PAGE_TITLES` | 7 | 0 | 7 |
| `META_DESCRIPTION` | 6 | 0 | 6 |
| `H1` | 4 | 0 | 4 |
| `SECURITY` | 12 | 0 | 12 |
| `PAGE_SPEED_CWV` | 5 | 0 | 5 |
| `STRUCTURED_DATA` | 6 | 0 | 6 |
| `INTERNAL_LINKS` | 9 | 0 | 9 |
| `CONTENT_ISSUES` | 9 | 0 | 9 |
| `CUSTOM_SEARCH` | 4 | 0 | 4 |
| `PAGINATION` | 6 | 0 | 6 |
| `HREFLANG_TAGS` | 13 | 0 | 13 |
| **Total** | **110** | **16** | **94** |

Same probe with no sitemap-discovered profile: 12 / 98, and the log line reads `"coverage_measured": 12, "coverage_not_measured": 98`.

**Spine and site.** Pages are keyed by `normalize_url`, first occurrence wins (`dict.fromkeys`), so the spine is a set (contract invariant 4). `site` is the majority hostname with `www.` and port stripped, the same choice the Screaming Frog adapter makes; more than one hostname adds a `site: N hostnames in spine; majority chosen` note. Empty input, or a hostname the contract refuses (`localhost`), raises `AuditExportError`, which wraps `ValidationError`.

**Logging.** One `audit_export_built` line with `pages`, `duplicates_dropped`, `coverage_measured`, `coverage_not_measured`. No URL is logged; `test_logs_carry_counts_never_urls` plants a sentinel in a URL and asserts it never reaches any record. This is the first adapter test written after 0078 fixed `get_logger`, so it asserts on the record's `extra` fields directly rather than on `message` alone.

### 2.2 `tests/modules/seo/test_audit_export.py` — 397 lines, 36 tests

| Group | Tests | What is pinned |
| :--- | ---: | :--- |
| Shape and coverage | 5 | `source=ENGINE`, `links=()`; the 16/94 split by exact set, `len(IssueId) == 110`; every `NOT_MEASURED` id present with `frozenset()`; `CANONICALS_MISSING` is `NOT_MEASURED` (D-A); every non-fully-measured category has a `not measured (...)` note |
| Sitemaps | 6 | the gate (4 ids drop, note swaps); `URLS_NOT_IN_SITEMAP` flags indexable only; orphan = sitemap and never linked; `UNKNOWN` excluded from non-indexable; over-50k counts per grouped sitemap, `SITEMAP_LIMIT + 1` hits and the small sitemap does not; exactly 50k is `MEASURED` and empty |
| Directives, canonicals, response codes | 4 + 5 parametrised | verdict-driven ids; chain length 1 vs 2; 4xx/5xx from `indexability_of`'s own reason text, with a PDF `NOT_A_PAGE` and an `UNKNOWN` landing in neither; `STATUS_RE` matches `indexability_of(status_code=s)` for 400, 404, 410, 500, 503 (D-B binding); `UNKNOWN` in no response-code set |
| URL rules | 8 parametrised + 1 | hit / miss pairs per rule; raw-URL read, normalised-key report |
| Dedupe, site, errors | 7 | union across duplicates; majority host, `www.` and `:8443` stripped; single host adds no note; `localhost` raises; empty raises; `produced_at` defaults aware-now; logs carry counts, never URLs |

### 2.3 `tests/modules/seo/test_import_boundary.py` — 93 lines, 9 tests

Walks every `*.py` under `src/modules/seo/{page_classifier,deliverables,contracts}` with `ast`, resolving relative imports against the package (`from ..deliverables import x` is caught, not just the absolute form).

| Test | Asserts |
| :--- | :--- |
| `test_every_package_has_the_modules_this_test_exists_for` | `audit_export.py`, `screaming_frog_adapter.py`, `_bundle.py`, `audit.py` are all scanned, so a green run cannot mean "nothing found" |
| `test_no_import_crosses_the_seam` ×3 | `page_classifier` never imports `deliverables`; `deliverables` never imports `page_classifier`; `contracts` imports neither |
| `test_the_seam_packages_import_contracts` | both sides really import `contracts` — joined, not merely kept apart |
| `test_detector_catches_a_violation` ×4 | `import src.modules.seo.deliverables`, `from ... import`, a submodule import, and a relative `from ..deliverables import x` are each detected |

This closes the "a test enforces it" sentence of ADR 0011 decision 1, which 0073 and 0074 both recorded as unfulfilled.

### 2.4 `tests/modules/seo/test_screaming_frog_adapter.py` — 401 → 383 lines

The P0-3 one-direction test `test_adapter_modules_never_import_page_classifier` and its banner (old lines 387–401) were removed along with the now-unused `import ast` and `_bundle` import, since the same direction is one of the three parametrised cases in §2.3. `test_page_classifier_normalize_url_satisfies_the_protocol` (line 327) stays: it is about the `UrlNormalizer` protocol, not the boundary. Docs-scribe verified: `grep -c test_adapter_modules_never_import_page_classifier` on both the working tree and `HEAD:tests/modules/seo/test_screaming_frog_adapter.py` returns 0; `wc -l` is 383. Because `b3d7105` was the file's first commit, the removal is not visible as a diff anywhere — the 401-line version only ever existed untracked.

---

## 3. Design decisions

### 3.1 D-A — `CANONICALS_MISSING` is `NOT_MEASURED` (operator ruling, Step 3, 2026-09-08)

Plan §4 P0-4 said the adapter fills "Canonicals/Canonicalised + Missing". It cannot. `cascading_pipeline.py:316`:

```python
canonical_url=evidence.canonical_url or evidence.url,
```

The profile's `canonical_url` is the page's own declaration *when it makes one* and the page URL otherwise. A profile whose `canonical_url == url` is therefore either self-canonical or has no canonical at all, and nothing on the profile says which. Measuring `CANONICALS_MISSING` from that field would flag every self-canonical page (the common, correct case) as missing — a false finding on most of a healthy site. Options considered: (a) flag `canonical_url == url` — rejected for the above; (b) add a declared-vs-fallback bit to `PageEvidence` and the profile — rejected for this cycle because it changes the canonical Phase 1 contract (ADR 0002) and plan §2 forbids touching the profile; (c) `NOT_MEASURED` with the reason in `notes` — chosen. ADR 0011 decision 5 says exactly this: not measured is a value, and it renders as "not measured by this crawl", never as zero. Handoff §8.1.

### 3.2 D-B — 4xx/5xx read from `indexability_reason` by regex, bound by a test (operator ruling, Option A)

Status codes do not survive onto the profile. The one trace is the prose `signal_parsers.indexability_of` writes at line 713:

```python
f"Answered {status_code}. A page that errors is not indexed.",
```

Option A (chosen): `STATUS_RE = ^Answered (\d{3})\.` over `indexability_reason`, only when `indexability is NOT_A_PAGE`, and a test — `test_status_regex_is_bound_to_indexability_of` — that calls `indexability_of` directly for five statuses and asserts the regex reads each one back. A rewording of the reason string fails that test, not silently empties two issue sets. Option B (a `status_code` field on the profile) is the right long-term shape and is handed off (§8.2); it was not done here for the same ADR 0002 reason as D-A. The regex is anchored so `Answered with something that is not an HTML page.` (a PDF) does not match; the test includes that case.

### 3.3 The sitemap gate is per crawl, not per page

Whether a sitemap was read is a property of the crawl, so the gate is one `any(...)` over the input, and it flips four ids at once. An alternative — measuring the three membership rules and marking only `OVER_50K` unmeasured — was rejected because "not in sitemap" is meaningless when there was no sitemap to be in, and that is the case that would have produced the largest false set.

### 3.4 Rules are a table, not a chain of `if`s

`_RULES: dict[IssueId, _Rule]` plus one special case for the crawl-wide count. Coverage is derived from membership in that table (`spec.id in _RULES or spec.id is OVER_50K`), so a rule cannot be added without becoming `MEASURED`, and a `MEASURED` id cannot exist without a rule. `test_sixteen_measured_ninety_four_not` asserts the exact set, so adding a rule moves the number and the test says so.

### 3.5 One boundary test, three directions, self-tested

The P0-3 test covered `deliverables -> page_classifier` only and lived in the adapter's test file. Moving it and widening it to three packages in one parametrised test means the seam has one owner. The four negative cases in `test_detector_catches_a_violation` exist because an ast walker that scans the wrong directory or misses a node type passes vacuously; a detector that has never seen a violation proves nothing. Further negative cases are the test-engineer's per plan §9 (§8.5).

### 3.6 `NOT_MEASURED_REASONS` lists the partly-measured categories too

`RESPONSE_CODES_INTERNAL`, `CANONICALS`, `DIRECTIVES` each have measured and unmeasured rows. The note for those categories is about the rows left unmeasured within them; omitting it would leave a workbook with `CANONICALS_MISSING: NOT_MEASURED` and no reason beside it. `SITEMAPS` and `URL_ISSUES` are fully measured (when a sitemap was read) and get no note; `test_notes_name_every_category_with_something_unmeasured` skips exactly those two.

---

## 4. Bugs found and fixed

### 4.1 Test data: two "miss" URLs normalised to the same key as their "hit"

In `test_url_rules`, two rows originally used a miss URL that `normalize_url` folds onto the hit's key: `/Blog/` ↔ `/blog/` (uppercase rule) and `/a//b/` ↔ `/a/b/` (multiple-slashes rule). The adapter unioned both profiles onto one key, so `normalize_url(miss) not in members` failed — correctly, because miss and hit *were* the same page. The code was right; the fixture was wrong. The rows now use distinct keys (`/news/`, `/a/c/`), and the collision behaviour itself is asserted on purpose in `test_url_rules_read_the_raw_url_and_report_the_normalised_key` and `test_duplicates_collapse_to_one_page_and_issues_union`, so the union is a documented feature rather than a surprise.

### 4.2 Specification: the plan's P0-4 row promised a measurement the profile cannot support

Plan §4 P0-4, "Canonicals/Canonicalised + Missing", was written from the catalogue, not from the profile. §3.1 is the analysis; the plan row is corrected in this cycle (§5.1). There is no code bug — the plan author assumed a field that does not exist.

### 4.3 No defect found in `contracts/`

The adapter exercised invariant 1 (every id covered), invariant 3 (`NOT_MEASURED` ⇒ empty) and invariant 4 (spine is a set) from the engine side for the first time. All held without change to `audit.py`.

---

## 5. Corrections

1. **`docs/DELIVERABLES_IMPLEMENTATION_PLAN.md` §4 row P0-4** said the engine adapter fills "Canonicals/Canonicalised + Missing". `CANONICALS_MISSING` is **not** measurable from the profile (§3.1, D-A). The row is corrected in this cycle and now cites this entry; the original wording is preserved here.
2. **The Cycle 2 brief** handed to the feature-builder listed `CANONICALS_MISSING` as `MEASURED`. Wrong for the same reason; overridden by D-A at the Step 3 stop. The brief is a chat artefact, not a file in the repository, so this is the only place the correction can live.
3. **"~14 measured"** appeared in the plan discussion and earlier session summaries as the expected count. The actual count is **16 `MEASURED` / 94 `NOT_MEASURED`** (110 total), or 12 / 98 when no sitemap was read. A `grep` of `docs/`, `CLAUDE.md` and `README.md` found no published "~14" for this adapter, so no tracked document needed editing; the number is pinned here and by `test_sixteen_measured_ninety_four_not`.
4. **[0074 §6](0074-absent-is-not-empty.md)** ("the ast test in this cycle covers one direction only ... ADR 0011 decision 1's 'a test enforces it' is still P0-6 and still unwritten") and **[0077 §6 / §8.4](0077-screaming-frog-adapter-and-zip-guards.md)** ("P0-4 ... P0-6 ... deferred to subsequent Phase 0 cycles") — superseded by this cycle. Left intact.
5. **`docs/ARCHITECTURE.md` "planned, not yet implemented" row** ("The engine adapter does not exist, so only a Screaming Frog export produces an `AuditDataset`; the boundary test covering `contracts/` and `page_classifier` directions is not written") and **`README.md` deliverables row** ("engine adapter (P0-4), import-boundary test (P0-6) ... not started") — both true until this cycle; both updated in this cycle.
6. **Feature-builder's report** gave the new-test split as `test_audit_export.py` 37, `test_import_boundary.py` 8. Collection shows **36 and 9**; the total of 45 was right.
7. **Feature-builder's report** said "Nothing committed" and this entry's brief said "not committed". True when written; **false at time of this entry**: `b3d7105` committed `audit_export.py`, both new test files and the 383-line adapter test file (§1.3). This cycle did not make that commit and did not ask for it.
8. **Feature-builder's H3** cited "redirect ceiling `http_fetcher.py:578`". The file is `src/integrations/http_fetcher.py` (not under `page_classifier`), and the `too many redirects` raises are at lines **573** (sync) and **601** (async); 578 is the `_afetch_chain` signature. The substance of H3 is unaffected (§8.3).

---

## 6. Explicitly not done

- **94 issues are `NOT_MEASURED`** (table in §2.1). By category: `RESPONSE_CODES_INTERNAL` no-response / redirect-loop / blocked-by-robots (3); `CANONICALS` everything but `CANONICALISED` (9, including `MISSING` per D-A); `DIRECTIVES_NOFOLLOW` (1); `PAGE_TITLES` (7); `META_DESCRIPTION` (6); `H1` (4); `SECURITY` (12); `PAGE_SPEED_CWV` (5); `STRUCTURED_DATA` (6); `INTERNAL_LINKS` (9, D4); `CONTENT_ISSUES` (9); `CUSTOM_SEARCH` (4); `PAGINATION` (6); `HREFLANG_TAGS` (13). Each is a fact about what `FullPageIntelligenceProfile` carries, not a shortcut; the reason is on the dataset in `notes`.
- **Three of the `RESPONSE_CODES_INTERNAL` rows are unmeasurable, not merely unmeasured.** A fetch that raises — transport error, the redirect ceiling (`http_fetcher.py:573` / `:601`), a robots refusal — is caught in `discovery.py`'s `_safe_fetch_html` `except` block (lines 1102–1107 region) and returns before `graph.record_fetch` (line 1127), so the profile reads `UNKNOWN`, indistinguishable from a page never requested. Handoff §8.3.
- **No call-site wiring.** Nothing calls `to_audit_dataset`. `PageClassificationOutput.pages` is the intended input (the docstring says so) but `tool.py`, `server.py` and the UI do not produce an `AuditDataset`. Plan §2: the endpoint arrives with the first workbook in Phase 2.
- **No HTTP endpoint, workbook, or UI surface.** Phase 2, separate plan and Step 3 stop.
- **`links` is never filled** (D4). `LINKS_NOT_RETAINED_NOTE` is on every dataset this adapter produces, and `INTERNAL_LINKS` (9 rows) is `NOT_MEASURED`.
- **No change to `FullPageIntelligenceProfile`, `PageEvidence`, `cascading_pipeline.py`, `signal_parsers.py`, or `page_classifier/__init__.py`.** D-A and D-B are both consequences of that constraint; the profile-side fixes are handoffs (§8.1, §8.2). The `__init__.py` docstring is now stale in a second way (§8.4).
- **P0-7 (`scripts/diff_against_rae.py`)** not started.
- **Plan §4 rows P0-3 / P0-5** are not annotated as done in the plan; only P0-4 / P0-6 were in this brief. 0077 is their entry. §8.7.
- **The red `test_server.py` test was not fixed** and must not be from this cycle (§1.3; 0078 §8.1).
- **Not committed by this cycle.** The code is in `b3d7105` by another session's sweep (§5.7); the documentation in this cycle is uncommitted. Two stray files, `api.err` and `api.out` (a server run's stdout/stderr from 2026-09-08 17:21, 298 and 0 bytes), sit untracked at the repository root and are not in `.gitignore`; a future `git add -A` would pick them up (§8.8).

---

## 7. Files changed

```
src/modules/seo/page_classifier/audit_export.py       new   292 lines   to_audit_dataset, 16 rules, sitemap gate, notes
tests/modules/seo/test_audit_export.py                new   397 lines   36 tests
tests/modules/seo/test_import_boundary.py             new    93 lines   9 tests; absorbs the 0077 one-direction test
tests/modules/seo/test_screaming_frog_adapter.py      401 -> 383 lines  P0-3 boundary test, banner, `import ast`, `_bundle` import removed
docs/DELIVERABLES_IMPLEMENTATION_PLAN.md              §4 P0-4 / P0-6 marked done -> 0079; P0-4 "+ Missing" corrected
README.md                                             +1 row audit_export.py; contracts and deliverables rows updated
docs/ARCHITECTURE.md                                  audit_export.py in the tree; boundary test named on contracts/ and
                                                      deliverables/; planned-table row reduced to P0-7 and rulebook
docs/build-log/README.md                              +1 row index
docs/build-log/0079-sixteen-measured-ninety-four-not.md   this entry
```

Not touched, as instructed: `src/api/server.py`, `tests/api/test_server.py`, `rankuno-ui/*`, `gsc_*`, `screaming_frog_merge.py` / `screaming_frog_reconciler.py` and their tests, `CLAUDE.md`, `page_classifier/__init__.py`. No ADR: D-A and D-B are rulings inside ADR 0011 decision 5.

---

## 8. Follow-ups

1. **H1 — `CANONICALS_MISSING` (to `page_classifier`, profile change under ADR 0002).** `cascading_pipeline.py:316` folds "no canonical declared" into `canonical_url = url`. A declared-vs-fallback bit on `PageEvidence` and the profile (or `canonical_url: str | None` with the fallback moved to the reader) would make `CANONICALS_MISSING` measurable. Until then D-A holds.
2. **H2 — status code on the profile (to `page_classifier`).** 4xx/5xx are read from prose (`signal_parsers.py:713`). A `status_code: int | None` on the profile removes `STATUS_RE` and the test that binds it. Until then `test_status_regex_is_bound_to_indexability_of` is the guard; anyone rewording `indexability_of` will meet it.
3. **H3 — fetch failures never reach the profile (to `page_classifier` / `discovery.py`).** Transport errors, the redirect ceiling (`src/integrations/http_fetcher.py:573`, `:601`) and robots refusals raise before `record_fetch` (`discovery.py:1127`), so `RESPONSE_CODES_INTERNAL_NO_RESPONSE`, `_REDIRECT_LOOP` and `_BLOCKED_BY_ROBOTS_TXT` cannot be measured. The fetch ledger from cycle 0050 records the *outcome* per URL on the graph; surfacing that outcome onto the profile (or onto `PageClassificationOutput` beside the pages) is the fix.
4. **H4 — `src/modules/seo/page_classifier/__init__.py` docstring** (lines 15–19) still lists `tool.py` and `tree_visualizer.py` under "Planned, not yet written" — both shipped long ago (CLAUDE.md §8 "Closed since the audit") — and does not mention `audit_export.py`. One-line docs fix; not done here because the brief excluded `__init__.py`.
5. **Test-engineer — boundary-test negative cases** beyond the four in `test_detector_catches_a_violation` (plan §9): `import ... as`, `importlib.import_module`, a `TYPE_CHECKING`-guarded import, and a module-level `__import__`.
6. **Owner of `src/api/server.py`** — 0078 §8.1 stands; the edits are now committed in `b3d7105` and `test_the_reason_says_the_thread_may_survive` failed again under the full gate on that tree (§1).
7. **Plan hygiene.** Annotate P0-3 / P0-5 as done (0077) and P0-1 / P0-2 (0073) in plan §4 so the table reads as a status board, as P0-8 already does.
8. **`api.err` / `api.out`** at the repository root: delete or add to `.gitignore` before the next commit.
9. **P0-7** `scripts/diff_against_rae.py`, opt-in, `Settings.rae_archive_dir` — next Phase 0 item; test-engineer per plan §9.
