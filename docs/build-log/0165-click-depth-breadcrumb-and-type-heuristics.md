# 0165 — Click depth, a breadcrumb that named no page, and two page-type heuristics

- **Date**: 2026-10-21
- **Branch**: `main`
- **Scope**: `src/modules/seo/page_classifier/` (depth export, breadcrumb parent, JSON-LD and
  nav-tree heuristics) and their tests. Golden snapshot regenerated for the depth and type
  changes it pins.

---

## 1. Gate results

Full gate, `powershell -ExecutionPolicy Bypass -File scripts/verify.ps1` (no `-Fix`), run on
the tree that this commit records. Excerpts are verbatim from the run:

```
=== Format ===
752 files already formatted
PASSED: Format

=== Lint ===
All checks passed!
PASSED: Lint

=== Type check ===
Success: no issues found in 198 source files
PASSED: Type check

Required test coverage of 85.0% reached. Total coverage: 94.10%
5033 passed, 2 skipped, 3 warnings in 863.52s (0:14:23)
PASSED: Tests

 Test Files  62 passed (62)
      Tests  858 passed (858)
PASSED: UI Component Tests

ALL GATES PASSED.
```

Drift check, `.\.venv\Scripts\python.exe scripts\drift_check.py`:

```
PASSED: no drift detected across 267 markdown files.
  - all relative links resolve
  - all domain modules documented
  - all skill directories populated
```

Targeted run on the three files that carry the new tests, before and after:

| Tree | Command | Result |
| :--- | :--- | :--- |
| `HEAD` (`git archive`, new test files overlaid) | `pytest test_depth_export.py test_breadcrumb_parent.py test_signal_parsers.py` | **12 failed, 78 passed** |
| working tree | same command | **90 passed in 0.68s** |

The 12 failures on `HEAD` are listed in §4.

---

## 2. What landed

### 2.1 `depth_from_l0` is click distance, not path depth

`depth_from_l0` was exported as `depth_of(evidence.normalized_path)`. `normalized_path` holds a
whole URL, so `https:` and the host counted as two path segments: the homepage exported `2` and
every page exported its click distance plus two. The link crawl had already recorded the true
distance on each graph node (`SiteGraph`, the breadth-first level `record_links` keeps) and dropped
it at the join into classification.

The fix carries that value through the join (Option A in the plan: use the recorded distance):

- `discovery.py` passes `depth=node.depth` into `PageEvidence` for every node.
- `signal_parsers.py` adds `PageEvidence.depth: int | None`, documented as never derived from URL text.
- `cascading_pipeline.py` exports `None if evidence.depth is None else min(evidence.depth, MAX_CRAWL_DEPTH)`.
  The cap matters because link chains are not path-limited and can exceed the schema ceiling.
- `schemas.py` makes `FullPageIntelligenceProfile.depth_from_l0` `int | None`. `None` means no crawled
  page linked here, so the distance is unknown rather than zero.
- `navigation_context.py` guards the `>= 3` comparisons against `None`, falling through to the
  existing "no path, in sitemap" branch.
- `reports.py` and `report_pdf.py` show `None` as `—`, not the text `None`.

Sitemap or CMS entries the crawl never reached export `None`. Evidence without a recorded level
(Screaming Frog imports and similar) exports `None`.

### 2.2 Breadcrumb parent with an empty path segment

`breadcrumb_parent_url` (`breadcrumb_parser.py:523`) accepted `https://host//` as a parent. The
`//` is markup that names no page. The fix refuses any candidate whose path contains `//`. It
drops the value rather than collapsing the empty segment, because collapsing would invent a URL the
markup never gave.

### 2.3 Two page-type heuristics that mislabelled pages

- **`FAQPage` removed from `_SCHEMA_TYPE_MAP`** (`signal_parsers.py`). `FAQPage` marks a
  question-and-answer block, which sits on product, service and article pages alike. Mapping it to
  `BLOG_ARTICLE` made a FAQ-only page an article.
- **Top-level nav items named for corporate pages abstain** (`parse_aria_nav_signal`). A top-level
  item was read as a service hub wherever it sat. `About`, `Careers` and similar sit in the same menu
  row and say nothing about services. `_CORPORATE_SEGMENTS` exempts them from that one rule. A
  top-level service item still returns a primary hub (a test pins this).

---

## 3. Design decisions

- **Click distance is the recorded BFS level, not a re-derived value.** Re-deriving it from the
  graph at export time would duplicate the walk. The crawl already owns that number.
- **`None` over `0` for unknown distance.** An unreached page at `0` would read as the homepage.
- **Breadcrumb: drop, do not repair.** A repaired URL is a URL the site never published.
- **The corporate list is a judgement list, not a measurement.** It is documented as such in
  `signal_parsers.py`. It exempts those segments from the top-level rule and nothing else.
- **No new ADR.** The depth change implements the meaning ADR 0002 already gives the field
  ("click depth, required to distinguish click depth from hierarchy level"). The heuristic changes
  are fixes within existing signals.

---

## 4. Bugs found and fixed

Each was reproduced first on the committed code (`HEAD`, via `git archive` plus the new test files):

| Test | Failure on `HEAD` |
| :--- | :--- |
| `test_depth_export.py::test_the_homepage_exports_zero_and_each_click_exports_its_distance` | `AssertionError` at `test_depth_export.py:80` (exported value not `0`) |
| `test_depth_export.py::test_the_async_crawl_exports_the_same_distances` | `AssertionError` at `:97` |
| `test_depth_export.py::test_a_page_no_link_reaches_exports_no_distance_rather_than_its_path_depth` | `AssertionError` at `:109` (unreached page did not export `None`) |
| `test_depth_export.py::test_a_click_distance_beyond_the_schema_ceiling_saturates_at_it` | `ValidationError`: `PageEvidence` had no `depth` field, so the classifier was never reached |
| `test_depth_export.py::test_evidence_without_a_recorded_level_exports_none` | `assert 3 is None` at `:127` (evidence with no level exported its path depth) |
| `test_depth_export.py::test_an_unknown_distance_does_not_break_navigation_enrichment` | `ValidationError`: profile rejected `depth_from_l0=None` |
| `test_depth_export.py::test_an_unknown_distance_is_shown_as_a_dash_in_the_pdf` | `ValidationError`: profile rejected `depth_from_l0=None` |
| `test_breadcrumb_parent.py::test_a_parent_with_an_empty_path_segment_is_dropped` | `https://e.com//` returned as parent |
| `test_breadcrumb_parent.py::test_an_empty_segment_mid_path_is_dropped_not_repaired` | `/a//b/` returned as parent |
| `test_signal_parsers.py::test_an_faq_page_with_no_article_signal_gives_no_article_opinion` | FAQPage alone returned an article signal |
| `test_signal_parsers.py::test_a_top_level_about_item_does_not_force_a_service_hub` | `/about-us/` at nav depth 0 returned a service hub |
| `test_signal_parsers.py::test_a_top_level_careers_item_does_not_force_a_service_hub` | `/careers/` at nav depth 0 returned a service hub |

### 4.1 Two fixtures were edited because the heuristic change made them stale

`tests/modules/seo/test_extraction_caps.py` and `tests/modules/seo/test_fetch_time_extraction.py`
used `FAQPage` as their example of a recognised schema type. `extract_schema_types` keeps only the
types `_SCHEMA_TYPE_MAP` recognises, so `FAQPage` is no longer kept. Both fixtures now use
`BlogPosting`, which is recognised. The assertion shape (first type wins; eight distinct types kept)
is unchanged. **Those tests were correct for the old mapping; the mapping was the defect.**

### 4.2 Golden snapshot regenerated, and the diff was checked field by field

`tests/fixtures/golden/extract_at_fetch_500.json.gz` was regenerated from the serial path. A
comparison of the old and new snapshots found these changes and no others:

- `depth_from_l0`: 485 values changed and 7 became `None`. The `depth` key was added to the
  `PageEvidence` projection.
- `navigation_reachability_tier` (74) and `navigation_source_authority` (20), both derived from depth.
- `primary_page_type`, `suggested_page_type`, `conversion_role`, `final_confidence_score`, `confidence`,
  `source`, `notes` (30 each): 30 pages moved from `BLOG_ARTICLE` to `UNKNOWN`. The golden site
  puts `FAQPage` on every seventh page, so these are the FAQ-only pages.
- `unknown_pages` in the summary: 214 became 244, the same 30 pages.

---

## 5. Explicitly not done

- **The "30 stored pages, most of them products" claim** is in the `FAQPage` comment in
  `signal_parsers.py`. It was **not re-verified in this cycle**: the stored crawls were not read. The
  golden snapshot shows 30 changes, but the golden site is synthetic.
- **Stored jobs keep their old values.** Nothing re-derives `depth_from_l0` or
  `primary_page_type` on existing stored results. A job classified before this commit still carries
  path-depth values until it is re-run or re-parsed.
- **`FAQPage` is no longer kept in the fetch-time schema-type facts.** This follows from §2.3 and
  is intended, but a reader comparing schema types across old and new jobs will see the difference.
- **No value for `depth_from_l0` on Screaming Frog imports.** They export `None`, so their depth
  column is blank by design, not an error.
- **The corporate segment list is not validated against a corpus.** It is a judgement list (§3).

---

## 6. Corrections to earlier entries

- **Build-log 0041** records `depth_from_l0` as "not fixed" and as a defect to fix. That status is
  now resolved by §2.1. 0041 is not edited; this entry is the correction.
