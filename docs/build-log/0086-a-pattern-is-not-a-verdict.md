# Cycle 0086: Defaulter URL quarantine — bare-list `UNKNOWN` rows classified by shape, quarantined from the tree, revalidated against GSC

- **Date**: 2026-09-09
- **Scope**: For the Screaming Frog cross-check's bare-URL-list input (cycle
  0072), classify each `frog_only` `UNKNOWN` row by URL shape into one of
  four `DefaulterCategory` values or leave it as an unclassified "presumed
  real" residual; quarantine the classified rows out of the interactive tree
  by default behind an opt-in toggle; give each category its own workbook
  sheet; re-check quarantined URLs against Search Console traffic whenever
  GSC data is attached to the job, without silently reclassifying them.
- **Commit**: `8e62b172b31926b1343325b1180b378915aeb154` — "chore: format and
  lint fixes for Phase 2a Tasks 2-5". That message describes none of this
  feature; the commit bundles it together with an unrelated concurrent
  session's multi-org security and PostgreSQL work because both were applied
  to a shared working tree before either was committed. Recorded here so a
  `git blame` on `screaming_frog_reconciler.py` is not mistaken for a
  formatting pass. See §7 for the file list scoped to this cycle only.
- **Quality gate**: whole-repo `verify.ps1` is **RED**, but on work this
  cycle did not touch — an untracked Redis config module, an untracked
  deliverables pipeline module, and a `test_idempotency.py` that imports a
  `make_app` symbol `src/api/server.py` does not export. Isolated checks on
  every file this cycle changed are green: ruff format clean, ruff check
  clean, `mypy --strict` clean, 246/246 tests passed, 96% coverage on
  `screaming_frog_reconciler.py`. Full output in §1.

## 1. Gate results

### 1.1 Whole-repo `verify.ps1` (real run, this session)

```
=== Format ===
unformatted: File would be reformatted
  --> src\core\redis_config.py:77:16
unformatted: File would be reformatted
  --> tests\modules\seo\deliverables\test_pipeline.py:59:18
2 files would be reformatted, 328 files already formatted
FAILED: Format

=== Lint ===
I001 Import block is un-sorted or un-formatted --> alembic\versions\0001_initial_schema.py:15:1
I001 Import block is un-sorted or un-formatted --> tests\core\test_redis_config.py:3:1
S106 Possible hardcoded password assigned to argument: "redis_password" --> tests\core\test_redis_config.py:54:34
S105 Possible hardcoded password assigned to: "password" --> tests\core\test_redis_config.py:108:54
E501 Line too long (101 > 100) --> tests\modules\seo\deliverables\test_pipeline.py:59:101
Found 5 errors.
FAILED: Lint

=== Type check ===
src\core\postgres_store.py:22: error: Cannot find implementation or library stub for module named "psycopg"  [import-not-found]
src\core\redis_config.py:63: error: Unused "type: ignore" comment  [unused-ignore]
Found 2 errors in 2 files (checked 82 source files)
FAILED: Type check

=== Tests ===
ERROR collecting tests/api/test_idempotency.py
ImportError: cannot import name 'make_app' from 'src.api.server'
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 warning, 1 error in 3.14s
FAILED: Tests

=== UI Component Tests ===
 Test Files  22 passed (22)
      Tests  248 passed (248)
   Duration  10.31s
PASSED: UI Component Tests

VERIFICATION FAILED: Format, Lint, Type check, Tests
```

None of the five failing findings touch a file this cycle changed:
`src/core/redis_config.py`, `tests/core/test_redis_config.py`,
`tests/modules/seo/deliverables/test_pipeline.py`,
`alembic/versions/0001_initial_schema.py`, `src/core/postgres_store.py`, and
`tests/api/test_idempotency.py` all belong to a concurrent session's
Phase 2a Redis/Postgres/idempotency work, present in the working tree as
untracked files or open collection errors at the time this gate ran. This
matches the pattern already on record in cycles 0083–0085: a shared working
tree makes the whole-repo gate unreadable for any one cycle's own claim.

### 1.2 Isolated checks, this cycle's files only

```
ruff format --check src/modules/seo/page_classifier/screaming_frog_reconciler.py \
  src/api/server.py src/modules/seo/page_classifier/bare_url_list.py \
  tests/modules/seo/test_screaming_frog_reconciler.py \
  tests/modules/seo/test_bare_url_list.py tests/api/test_server.py
  -> 6 files already formatted

ruff check <same files>
  -> All checks passed!

mypy --strict src/modules/seo/page_classifier/screaming_frog_reconciler.py \
  src/api/server.py src/modules/seo/page_classifier/bare_url_list.py
  -> Success: no issues found in 3 source files

pytest tests/api/test_server.py tests/modules/seo/test_screaming_frog_reconciler.py \
  tests/modules/seo/test_bare_url_list.py --no-cov
  -> 246 passed, 1 warning in 10.25s
     (128 in test_server.py + 106 in test_screaming_frog_reconciler.py + 12 in test_bare_url_list.py)

pytest tests/modules/seo/test_screaming_frog_reconciler.py tests/modules/seo/test_bare_url_list.py \
  --cov=src.modules.seo.page_classifier.screaming_frog_reconciler --cov-report=term-missing
Name                                                           Stmts   Miss Branch BrPart  Cover   Missing
screaming_frog_reconciler.py                                    362     13     88      5    96%   409-410, 559, 563-564, 696, 739, 1027-1030, 1091-1092
Required test coverage of 85.0% reached. Total coverage: 96.00%
```

The `test_screaming_frog_reconciler.py` count (106) matches the implementer's
figure exactly, verified by an independent re-run rather than taken on trust.

### 1.3 Full python suite, unrelated collection errors excluded

Run with `--ignore=tests/api/test_idempotency.py
--ignore=tests/core/test_redis_token_bucket.py` (the two files that abort
collection before any test runs) so the rest of the suite is actually
readable:

```
2281 tests, 0 failures, 0 errors, 2 skipped, 162.66s
Required test coverage of 85.0% reached. Total coverage: 89.55%
```

This is not a claim that the whole repo is green — §1.1 already says it is
not — only that nothing outside the two excluded files is currently broken.

### 1.4 UI

```
npx vitest run   -> Test Files 22 passed (22); Tests 248 passed (248)
npx tsc --noEmit -> exit 0, no output
```

No new UI test count is called out separately here because the whole-suite
248 already includes the 7 new `dashboardModel.test.ts` cases plus the
`treeOverlay.test.ts` (+2), `TreeControls.test.tsx` (+3) and
`VirtualizedTree.test.tsx` (+4) additions the implementer reported; this
session did not re-run the UI suite pre- and post-change to isolate the
delta, since the change is already merged into the working tree (see the
commit note above) and there is no prior state to diff against locally.

## 2. What landed

- `src/modules/seo/page_classifier/screaming_frog_reconciler.py`:
  `DefaulterCategory` (`StrEnum`: `DAM_HTML_ARCHIVE`, `DAM_FORMS_OTHER`,
  `CMS_INTERNAL_LEAK`, `CORRUPTED_URL`), `DefaulterValidation` (`checked_at`,
  `gsc_impressions`, `gsc_clicks`, `flagged_real`), and two new optional
  fields on `UrlGap`: `defaulter_category: DefaulterCategory | None = None`
  and `validation: DefaulterValidation | None = None`. Both default to
  `None`, so every previously saved reconciliation sidecar deserialises
  unchanged. Classification (`_defaulter_category`) runs only when a row is
  `BARE_URL_LIST`-sourced and its reason is `UNKNOWN`; precedence is
  corrupted-first, then DAM-archive, then DAM-forms-other, then CMS-leak,
  then no match (the residual, left `None`, "presumed real, not verified").
  `revalidate_defaulters(saved, unmatched_rows)` is a pure function with no
  network call: it re-checks each defaulter row against the GSC "not
  crawled" bucket the performance-attach endpoint already produces and
  attaches a `DefaulterValidation` with `flagged_real=True` where GSC shows
  impressions or clicks, without touching `defaulter_category` — the
  original pattern-match evidence stays visible even after GSC contradicts
  it.
- `src/api/server.py`: `DefaulterCategory` entries added to `GAP_MEANINGS`
  and `SHEET_TITLES` (four new sheets: "Defaulters – DAM archive",
  "Defaulters – DAM forms/other", "Defaulters – CMS leaks", "Defaulters –
  Malformed"), a `rank()` tier placing them after the file-type sheets and
  before the remaining reasons, and the download endpoint's bucket-assembly
  loop keyed by `row.get("defaulter_category") or reason` instead of `reason`
  alone — a defaulter row buckets by its category, every other row is
  unaffected. The GSC-attach endpoint (`attach_performance`) now builds
  `unmatched_rows_payload` once, reuses it for both the sidecar write and a
  new `revalidate_defaulters` call, and writes back the updated
  reconciliation only when one exists for the job.
- UI (`rankuno-ui/src`): `DashNode.kind: "page" | "group" | "defaulter"` plus
  `defaulterCategory?: string`; `buildDashModel(result, grouping,
  reconciliation, includeDefaulters)` builds zero defaulter nodes when the
  flag is off — not merely hidden, not constructed, so lane counts stay
  honest — and a "Defaulter / Quarantine" root with one group per category
  when on; new `DEFAULTER_LANE = 5` excluded from the existing L0–L3/OTHERS
  classification chips; `useCrawlStore` gained `includeDefaulters` (default
  `false`, reset on every job switch) and `toggleIncludeDefaulters()`;
  `TreeControls.tsx` gained an "Include Defaulters" toggle, disabled with a
  tooltip when no reconciliation is loaded; `VirtualizedTree.tsx` renders a
  defaulter leaf as an openable real-URL link rather than the "URL path
  segment, no page crawled" fallback every other no-profile node gets;
  `useDashboardStore.ts`'s `ALL_LANES` set was extended to include
  `DEFAULTER_LANE`, without which the lane filter would hide the quarantine
  subtree even with the toggle on.
- Test coverage: 47 new cases in `test_screaming_frog_reconciler.py` (106
  total, up from 59, independently re-counted in §1.2), including a
  regression fixture replaying real `infosys.com` URLs from the three
  confirmed bare-list sidecars to pin the measured per-category counts
  against future rule drift. UI: `dashboardModel.test.ts` (new, 7 cases),
  `treeOverlay.test.ts` (+2), `TreeControls.test.tsx` (+3),
  `VirtualizedTree.test.tsx` (+4).

## 3. Design decisions

- **Orthogonal fields on `UrlGap`, not new `FrogGapReason` members.** The
  feature-builder's Phase A measured all 13 saved reconciliation sidecars in
  the repository, not just the one example seen first: only 3 of 13 are
  bare-list format, and all three are the same site (`infosys.com`) uploaded
  on different dates. Even applying all four classification rules, roughly
  80% of every bare-list `UNKNOWN` bucket remains genuinely unclassified —
  the categories are a triage aid over a bucket that stays `UNKNOWN`, not a
  resolution of it. Adding new `FrogGapReason` members would have broken the
  module's own documented invariant that every row has exactly one reason
  assigned by the first matching rule, and would have thrown away the
  original pattern-match evidence the moment GSC contradicted it. The
  orthogonal `defaulter_category` / `validation` pair keeps `reason` at
  `UNKNOWN` (true), adds the shape guess as a separate positive claim, and
  keeps a GSC contradiction additive rather than a silent overwrite.
- **`kind: "page" | "group" | "defaulter"` on `DashNode`, not a flag on the
  existing page node.** A `frog_only` defaulter URL was never crawled, so
  unlike every existing node type it has no crawl profile behind it — "reveal
  it in the tree" means synthesizing a new node, not toggling visibility on
  one that already exists. A third `kind` value keeps that distinction
  explicit at the type level instead of overloading the existing "no profile"
  fallback path, which already means something else (a URL found in the nav
  tree but not fetched by this crawl).
- **The frog-side "sitemap orphan" idea folded into the existing "presumed
  real" residual, not a second `SITEMAP_ORPHAN` value.**
  `EngineGapReason.SITEMAP_ORPHAN` already names a URL this engine found with
  no internal link pointing at it — a different comparison direction (engine
  found it, Screaming Frog did not) from what a frog-side bare-list residual
  would mean (Screaming Frog found it, this engine did not, and it matched no
  junk pattern). Reusing the same name for the second, unrelated meaning
  would have made every future reference to "sitemap orphan" ambiguous about
  which side and which crawler. This was flagged as an assumption during
  Phase B dispatch, not confirmed back by the requester before implementation
  proceeded — see §6.
- **GSC revalidation reuses the existing `unmatched_rows` "not_crawled"
  bucket the GSC-attach endpoint already produces**, rather than issuing a
  new lookup. Zero new network calls, zero new cost, and no new Step 5 audit
  was required as a result — the data was already being fetched and stored
  for an unrelated purpose (the performance panel's unmatched-rows list).
- **`DAM_FORMS_OTHER` quarantined by default along with the other three,
  though the requester's literal wording named only three categories.** The
  implementer's stated reasoning: it is equally "structurally junk" per its
  own docstring, and the Excel report already includes it as a fifth-column
  sheet regardless. This is recorded as an open item in §6, not a resolved
  one — nobody has confirmed it back to the requester.
- **No ADR.** The orthogonal-field-vs-new-enum-member choice is a real design
  decision but is scoped to one module's internal representation, is fully
  reversible (a migration from `defaulter_category` to dedicated
  `FrogGapReason` members would touch one function and one Pydantic model,
  not a boundary contract), and does not change any cross-module interface,
  risk classification, or externally observable API shape beyond four new
  optional JSON fields and four new workbook sheets. It does not meet the bar
  CLAUDE.md §6 sets for the existing ADR table (scale, output contract,
  execution model, deployment, LLM provider boundary, signal-weight seam) —
  those are all decisions a later engineer could not safely re-derive from
  the code alone. This one can: `git blame` on `UrlGap` explains itself, and
  §3 of this entry is the record if someone later asks why.

## 4. Bugs found and fixed

1. **`prompt-generator`'s first-pass brief pointed at the wrong modules**
   (`reports.py`, `tree_visualizer.py`, `gsc_aggregator.py` — all real files,
   but belonging to an unrelated deliverable pipeline, not the reconciliation
   cross-check this feature touches). Caught by the main session before any
   agent was dispatched; no implementation work was wasted, but it is worth
   recording that the automatic routing step got this one wrong and needed a
   human correction before Step 3 (HITL) could even present the right
   architecture.
2. **The requester's own brief reused `"SITEMAP_ORPHAN"` for a second,
   conflicting meaning** across the frog-side and engine-side comparisons
   (see §3). Caught before dispatch; resolved by folding the frog-side intent
   into the existing "presumed real" residual instead of adding a colliding
   second reason with the same string value in two different enums.
3. **The main session's own hand-application of the GSC-attach-endpoint hunk
   broke the file's parse on the first attempt** — it referenced
   `unmatched_rows_payload` before the name was defined, and left a
   malformed half-function (`_unused_unmatched_rows_shape`) in the file. This
   was not caught by a later gate run; it surfaced immediately as an IDE
   diagnostic (`ast.parse` failure, ruff and mypy both cascading dozens of
   "could not find name" errors through the rest of the file) and was fixed
   by re-reading the actual surrounding code and replacing the whole broken
   block — building `unmatched_rows_payload` as its own list comprehension
   before `write_performance`, unchanged in shape after that, followed by the
   new `read_reconciliation` / `revalidate_defaulters` / `write_reconciliation`
   block, followed by `return summary`. One follow-up `ruff` E501 fix was
   needed on the `CORRUPTED_URL` meaning string afterward (wrapped in
   parens). This is recorded as a bug in this cycle's own process, not in the
   shipped code: the broken intermediate state never reached a commit or a
   gate run.

No specification or test-was-wrong bugs were found this cycle — the four
classification rules, the precedence order, and the GSC-revalidation contract
all matched what Phase A's measurement against the 13 saved sidecars
predicted, and no fixture assertion needed correcting during Phase B.

## 5. Corrections

None. This is the first build-log entry for this feature; there is no prior
published claim about it to correct.

## 6. Explicitly not done

- **The WAF-bypass automated crawl fallback** (auto-retry as Googlebot/Chrome
  UA on 403, a headless-Chrome sidecar to silently solve Cloudflare
  Turnstile/Akamai challenges, one-click UI confirmation) was requested in
  the same session and **declined**, not deferred. The main session held this
  position across two separate requests: impersonating Googlebot specifically
  to obtain preferential WAF treatment, and automating defeat of a site's
  bot-challenge system, is circumventing another site's access controls
  without authorization — which conflicts with the mandatory
  `robots.can_fetch()` policy CLAUDE.md §5 itself requires on every outbound
  fetch. The legitimate subset was offered and remains unbuilt on request:
  alternate sitemap discovery via `/sitemap_index.xml`, `<link
  rel="sitemap">`, and `Sitemap:` lines in `robots.txt`; an honest UI badge
  that names a block rather than claiming to have bypassed it.
- **Live-fetch verification of the "presumed real" residual bucket**
  (confirming a bare-list URL that matched no defaulter pattern is actually
  live and HTML) is out of scope for this cycle. It would need its own
  outbound-network capability and its own Step 5 security/cost audit before
  any code touches it.
- **The four classification rules are measured against exactly one site**
  (`infosys.com`, 3 bare-list sidecars, all uploaded on different dates for
  the same site). Do not describe them as validated across sites or across
  clients — only one site's URL-shape conventions have been observed.
- **Whether `DAM_FORMS_OTHER` should be tree-quarantined by default is an
  open question, not a resolved one.** The requester's literal wording named
  only `DAM_HTML_ARCHIVE`, `CMS_INTERNAL_LEAK`, and `CORRUPTED_URL` for tree
  quarantine; the shipped code quarantines all four. See §3 for the
  implementer's reasoning. Nobody has confirmed this back to the requester as
  of this entry.
- **`Summary` sheet's `frog_reasons` / `engine_reasons` tallies deliberately
  still count by `reason`**, which stays `UNKNOWN` for every defaulter row —
  only the per-sheet bucketing in the download endpoint uses
  `defaulter_category`. This is a stated scope boundary, not an oversight: a
  later reader should not "fix" the Summary sheet to tally by category, since
  that would double-count a row that is simultaneously `UNKNOWN` by reason
  and, say, `DAM_HTML_ARCHIVE` by shape.
- **This cycle did not disentangle the shared-commit problem** described in
  the header: `8e62b172b3` bundles this feature with an unrelated session's
  multi-org security and PostgreSQL work under a commit message that
  describes neither. No `git revert`/rebase was attempted to split it — that
  is a git-history operation with its own risk, not requested, and out of
  scope for a documentation cycle.

## 7. Files changed

Scoped to this feature only (the commit above also touches unrelated files
— see the header note and CLAUDE.md's general caution against conflating
concurrent sessions' work):

- `src/modules/seo/page_classifier/screaming_frog_reconciler.py` (+269
  lines in the shared commit; `DefaulterCategory`, `DefaulterValidation`,
  `UrlGap.defaulter_category`, `UrlGap.validation`, `_defaulter_category()`,
  `revalidate_defaulters()`)
- `src/api/server.py` (defaulter entries in `GAP_MEANINGS` / `SHEET_TITLES`,
  `rank()` tier, bucket-assembly keyed by `defaulter_category or reason`,
  `unmatched_rows_payload` extraction and `revalidate_defaulters` call in
  `attach_performance`)
- `tests/modules/seo/test_screaming_frog_reconciler.py` (106 tests, up from
  59)
- `tests/api/test_server.py` (extended for the new sheet/bucket behaviour)
- `rankuno-ui/src/lib/dashboardModel.ts` (`DashNode.kind`,
  `defaulterCategory`, `DEFAULTER_LANE`, `includeDefaulters` parameter)
- `rankuno-ui/src/lib/dashboardModel.test.ts` (new, 7 tests)
- `rankuno-ui/src/lib/treeOverlay.ts` / `treeOverlay.test.ts` (+2 tests;
  confirmed the existing missed/added overlay never sees defaulter nodes)
- `rankuno-ui/src/store/useCrawlStore.ts` (`includeDefaulters`,
  `toggleIncludeDefaulters()`)
- `rankuno-ui/src/store/useDashboardStore.ts` (`ALL_LANES` extended with
  `DEFAULTER_LANE`)
- `rankuno-ui/src/components/tree/TreeControls.tsx` /
  `TreeControls.test.tsx` (+3 tests; "Include Defaulters" toggle)
- `rankuno-ui/src/components/tree/VirtualizedTree.tsx` /
  `VirtualizedTree.test.tsx` (+4 tests; defaulter leaf rendering)

## 8. Follow-ups

- Confirm with the requester whether `DAM_FORMS_OTHER` belongs in the
  default tree quarantine (§6).
- If the legitimate sitemap-discovery subset of the declined WAF-bypass
  request is wanted, it needs its own Step 3 brief — it was offered, not
  requested outright.
- The shared-commit situation (§6, §7) is worth a process note for future
  cycles: two features landed in one commit under a message naming neither,
  because two sessions applied hunks to the same working tree before either
  committed. Not a defect in this feature, but a rough edge in how
  concurrent sessions are being coordinated.
