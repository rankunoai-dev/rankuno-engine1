# Cycle 0096: Twenty-nine measured, eighty-one not

- **Date**: 2026-09-15
- **Scope**: Native title/H1/meta-description extraction at crawl time
  (`src/modules/seo/page_classifier/content_signals.py`), threaded through
  `PageEvidence` -> `FullPageIntelligenceProfile` -> `audit_export.py`, moving
  13 of the 17 `PAGE_TITLES`/`META_DESCRIPTION`/`H1` catalogue issue ids from
  `NOT_MEASURED` to `MEASURED`. ADR 0014 records the decision, written by the
  implementer per its own acceptance criteria.
- **Commit**: uncommitted at time of writing
- **Quality gate**: targeted files clean — `ruff check` and `mypy --strict`
  both independently re-run on all 6 touched `src/` files, 0 issues either
  way. `tests/modules/seo/test_content_signals.py` +
  `tests/modules/seo/test_audit_export.py` together: **92 passed**,
  independently re-run (§5). The implementer's fuller combined run across 9
  files: 433 passed in 70.07s (§5, not independently re-timed but the file
  list and dot-count were independently re-run and matched exactly). Whole-repo
  `verify.ps1` not independently re-run this cycle (§6) — reported RED on
  lint/type-check/tests/UI, all in files on this cycle's do-not-touch list.

## 1. Origin

This closes the first slice of the "grow native crawl coverage" roadmap
identified earlier this session (RAE integration thread): the engine measured
only 16 of the RAE catalogue's 110 issue types natively, requiring a Screaming
Frog import for the rest ([build-log 0079](0079-sixteen-measured-ninety-four-not.md)).
Step 3 design was presented and approved by the operator earlier this session.

## 2. What shipped

- **`content_signals.py`** (new, 279 lines) — `ContentSignals(StrictModel)`
  with 8 fields (`page_title`/`page_title_count`/`page_title_outside_head`,
  `meta_description`/`meta_description_count`/`meta_description_outside_head`,
  `h1_text`/`h1_count`) and `extract_content_signals(html: str) -> ContentSignals`,
  a pure `html.parser`-based tokenizer with no new dependency and no I/O.
  First-occurrence-wins for text (matching `document.title` semantics);
  every occurrence, including malformed nesting, increments the independent
  *count*. `OUTSIDE_HEAD` is a one-way flip (`_closed_head`) set the moment a
  start tag arrives whose name is outside the small set legitimately found in
  or before `<head>` — a heuristic for malformed/no-`<head>` documents, not a
  DOM-ancestry read (`html.parser` builds no tree). `<noscript>` content is
  excluded entirely via a depth counter, so a tracking-pixel fallback
  `<title>`/`<meta name="description">` is never counted or allowed to flip
  `_closed_head`. Runaway/unterminated tags are truncated (500/500/1000 chars
  for title/meta description/H1), not dropped — `extract_content_signals`
  never raises.
- **Wiring**, one implementation for both crawl paths: `discovery.py`'s
  `SiteGraph.record_fetch()` (the single method both sync `discover_site` and
  async `adiscover_site` call — see §4 correction) now calls
  `extract_content_signals` at the same `if result.is_html and result.body`
  guard that already extracts the canonical tag, and `to_page_evidence()`
  passes the 8 fields through. `signal_parsers.py`'s `PageEvidence` gained the
  same 8 fields. `schemas.py`'s `FullPageIntelligenceProfile` gained the same
  8 fields with `""`/`0`/`False` defaults, so a profile persisted before this
  shipped still deserialises under `extra="forbid"`. `cascading_pipeline.py`'s
  profile-construction call passes all 8 `evidence.*` fields through.
- **`audit_export.py` wiring** (391 lines total): a new `_UNFETCHED`
  frozenset (`{Indexability.UNKNOWN, Indexability.NOT_A_PAGE}`) gates the
  three `*_MISSING` rules so a page the crawl never actually fetched cannot
  register as "missing a title" it never had a chance to declare; a
  `_normalize_text` helper (casefold + collapse whitespace) shared by
  `PAGE_TITLES_SAME_AS_H1` and three new duplicate-detection helpers; 10 new
  direct `_RULES` entries (`PAGE_TITLES_MISSING`/`MULTIPLE`/`OUTSIDE_HEAD`/
  `SAME_AS_H1`, `META_DESCRIPTION_MISSING`/`MULTIPLE`/`OUTSIDE_HEAD`,
  `H1_MISSING`/`MULTIPLE`/`OVER_70_CHARACTERS`); `_duplicates_by` plus 3
  sibling wrappers (`_duplicate_titles`, `_duplicate_meta_descriptions`,
  `_duplicate_h1s`) generalising the previously-hardcoded `_over_50k` special
  case into a `_CROSS_PROFILE_RULES` dispatch dict (now holding 4 entries: the
  pre-existing `SITEMAPS_XML_SITEMAP_OVER_50K_URLS` plus the 3 new
  `*_DUPLICATE` ids); `NOT_MEASURED_REASONS` rewritten for `PAGE_TITLES` and
  `META_DESCRIPTION` to name only the 4 pixel ids, and the `H1` entry removed
  outright (H1 has no pixel ids, so it is now fully measured).
- **`rankuno-ui/src/types/schema.ts`** regenerated mechanically via the
  existing `scripts/export_ui_contract.py` generator (never hand-edited),
  gaining the 8 new fields on both `FullPageIntelligenceProfile` and
  `DiscoveredNode` (16 lines added, confirmed by diff: `page_title`,
  `page_title_count`, `page_title_outside_head`, `meta_description`,
  `meta_description_count`, `meta_description_outside_head`, `h1_text`,
  `h1_count`, each twice). The same regeneration also pulled in 3 unrelated
  `DiscoveryReport` fields (`sitemap_fetch_attempts`, `sitemaps_blocked`,
  `sitemap_offhost_skipped`) from another session's pre-existing uncommitted
  work in `discovery.py` — not authored or reviewed by this cycle, flagged in
  §7 rather than investigated (out of scope per this cycle's own
  instructions).

## 3. Design decision: the pixel-width fallback was taken, not shipped

The four `*_PIXELS` catalogue ids (`PAGE_TITLES_OVER_561_PIXELS`,
`PAGE_TITLES_BELOW_200_PIXELS`, `META_DESCRIPTION_OVER_985_PIXELS`,
`META_DESCRIPTION_BELOW_400_PIXELS`) stay `NOT_MEASURED`. This is the
approved design's own declared fallback contingency, not a shortfall: no
verified glyph-width table could be sourced this session — no network access,
no authoritative font-metrics source to check a reconstructed table against.
Retyping a half-remembered table from training data would be an unverifiable
guess dressed up as a measured fact in a client-facing audit, which is exactly
what the approved design forbids. A `tkinter.font` live-rendering alternative
was considered and rejected too: it is not a static lookup table as scoped,
and it would measure the same page differently on the Windows workstation
that runs this crawler than on a Linux CI runner — non-deterministic across
machines, unacceptable in a report meant to reproduce identically anywhere.
`NOT_MEASURED_REASONS` for `PAGE_TITLES`/`META_DESCRIPTION` was rewritten
(not removed) to name only these 4 ids; `H1`, which has no pixel ids, is now
fully measured and its reason entry was removed outright. Full reasoning and
the alternatives table are in
[ADR 0014](../adr/0014-native-title-h1-meta-description-extraction.md).

## 4. Bugs found and fixed (including a bug in the design's own narrative)

- **The approved design assumed two call sites that turn out to be one.** The
  brief's design narrative asked for a "mirrored" edit of
  `record_fetch()`/`to_page_evidence()` in both `discovery.py` and
  `async_discovery.py`. Investigation during implementation found both are
  the *same* implementation: `discover_site` (sync) and `adiscover_site`
  (async) both call the one `SiteGraph.record_fetch` method. Independently
  confirmed by `git diff -- src/modules/seo/page_classifier/discovery.py`,
  which shows the wiring, and by `git status`, which shows `async_discovery.py`
  untouched. This is not a missed file — it means sync/async parity for this
  feature is structural, not maintained by hand across two places that could
  drift.
- **The brief's own field count disagreed with its own field list.** The
  design brief named 8 `ContentSignals` attributes explicitly but later prose
  referred to "the 7 new fields." H1 has no `*_OUTSIDE_HEAD` catalogue issue
  (only `PAGE_TITLES` and `META_DESCRIPTION` do), so all 8 named fields are
  load-bearing for the 17-id target. Implemented as 8, documented in ADR 0014
  as a corrected miscount in the brief, not a scope change by the
  implementer.

## 5. Tests — independently re-run

Targeted pair, run directly by docs-scribe (not copied from the implementer's
report):

```
$ .venv/Scripts/python.exe -m pytest tests/modules/seo/test_content_signals.py tests/modules/seo/test_audit_export.py -q
........................................................................ [ 78%]
....................                                                     [100%]
```

92 dots, exit 0, matching the implementer's stated "92 passed" exactly. (This
environment's pytest configuration does not print the usual `N passed in Xs`
summary line under `-q` here — confirmed by capturing output to a file and
inspecting it directly, not a truncation artifact — so the count above was
obtained by counting dots in the captured output, not read off a printed
total.)

The implementer's fuller combined run, independently re-run by docs-scribe
with the same file list:

```
$ .venv/Scripts/python.exe -m pytest tests/modules/seo/test_content_signals.py tests/modules/seo/test_discovery.py tests/modules/seo/test_async_discovery.py tests/modules/seo/test_audit_export.py tests/modules/seo/test_canonical_capture.py tests/modules/seo/test_cascading_pipeline.py tests/modules/seo/test_page_classifier_schemas.py tests/modules/seo/test_signal_parsers.py tests/test_ui_contract.py -q
........................................................................ [ 16%]
........................................................................ [ 33%]
........................................................................ [ 49%]
........................................................................ [ 66%]
........................................................................ [ 83%]
........................................................................ [ 99%]
.                                                                        [100%]
```

433 dots, exit 0 — matches the implementer's reported "433 passed in 70.07s"
exactly (docs-scribe's own re-run did not separately capture the timing).

New test surface, confirmed by `git diff --stat` / `git diff` inspection
rather than taken from the report: `test_content_signals.py` is new, 230
lines, 34 test functions (`--collect-only` count). `test_audit_export.py`
gained 222 insertions holding 4 new test classes
(`TestMissingIsGatedOnFetchedStatus`, `TestMultipleAndOutsideHead`,
`TestSameAsH1AndOver70Characters`, `TestDuplicateContentSignals`) plus 2
standalone tests (`test_twenty_nine_measured_eighty_one_not`,
`test_pixel_ids_are_not_measured_with_a_rewritten_reason`) — 23 new `def
test_` lines by direct count, close enough to the implementer's "22 across 4
new test classes + 1 pixel-note test" framing that the discrepancy is not
treated as a correction, just a different way of counting the same diff.
`test_canonical_capture.py` (+69 lines), `test_cascading_pipeline.py` (+33
lines) and `test_page_classifier_schemas.py` (+17 lines) also grew; not
individually re-verified line-by-line beyond the diff stat, since the
combined 433-pass run above already exercises them.

`EXPECTED_MEASURED` in `test_audit_export.py`, read directly: 29 members,
`assert len(measured) == 29` (was `16` before this diff — confirmed via
`git diff`, not inferred). `audit_export.py`'s own module docstring now
states "Twenty-nine issues are measured from those facts; the other
eighty-one are declared `NOT_MEASURED`" (29 + 81 = 110). Cross-checked
against `catalogue.py` directly: `PAGE_TITLES` has 7 ids (`MISSING`,
`DUPLICATE`, `OVER_561_PIXELS`, `BELOW_200_PIXELS`, `SAME_AS_H1`, `MULTIPLE`,
`OUTSIDE_HEAD`), `META_DESCRIPTION` has 6 (`MISSING`, `DUPLICATE`,
`OVER_985_PIXELS`, `BELOW_400_PIXELS`, `MULTIPLE`, `OUTSIDE_HEAD`), `H1` has 4
(`MISSING`, `DUPLICATE`, `OVER_70_CHARACTERS`, `MULTIPLE`) — 17 total, of
which the 4 pixel ids stay `NOT_MEASURED` and the other 13 are now `MEASURED`
(10 direct `_RULES` entries + 3 `_CROSS_PROFILE_RULES` duplicate entries,
counted directly from the diff in §2). **13/17 and 16/110 -> 29/110 are both
independently confirmed, not taken on the implementer's word.**

Ruff and mypy, independently re-run on all 6 touched `src/` files:

```
$ .venv/Scripts/python.exe -m ruff check src/modules/seo/page_classifier/content_signals.py src/modules/seo/page_classifier/discovery.py src/modules/seo/page_classifier/signal_parsers.py src/modules/seo/page_classifier/schemas.py src/modules/seo/page_classifier/cascading_pipeline.py src/modules/seo/page_classifier/audit_export.py tests/modules/seo/test_content_signals.py
All checks passed!

$ .venv/Scripts/python.exe -m mypy --strict src/modules/seo/page_classifier/content_signals.py src/modules/seo/page_classifier/discovery.py src/modules/seo/page_classifier/signal_parsers.py src/modules/seo/page_classifier/schemas.py src/modules/seo/page_classifier/cascading_pipeline.py src/modules/seo/page_classifier/audit_export.py
Success: no issues found in 6 source files
```

## 6. Gate (whole-repo, as reported by the implementer — not independently re-run)

The whole-repo `verify.ps1` gate was not independently re-run this cycle:
the targeted 433-test subset alone took real, measurable time, and a full
run is several times that (see cycles 0088–0095 for comparable full-run
durations, all several minutes). The implementer's reported tail is pasted
here per the "paste real gate output" rule, with the caveat that it is
reported, not independently reproduced end-to-end:

```
Format: PASSED
Lint: FAILED (33 pre-existing errors, 0 in touched files)
Type check: FAILED (14 pre-existing errors in 6 files, 0 in touched files)
Tests: FAILED (7 pre-existing failures, 2518 passed, 2 skipped; coverage 92.86%)
UI Component Tests: FAILED (2 pre-existing failing test files, unrelated frontend components)
```

The implementer attributes every failure to files on this cycle's explicit
do-not-touch list. Independently checked via `git status` rather than taken
on the implementer's word: `src/api/server.py`, `tests/api/test_idempotency.py`,
`tests/integrations/test_gsc_token_manager.py` and `src/core/state_store.py`
are all either already-modified-but-uncommitted by a concurrent multi-org/GSC
session, or untouched by this cycle's diff — consistent with the do-not-touch
list this cycle was given. One concrete example worth naming, cross-checked
against the do-not-touch list rather than re-diagnosed: the
`TestFacetRouterCapWiring` failures the implementer describes as
`ApiState.__init__() missing 1 required positional argument:
'org_config_store'` are the same concurrent multi-org `ApiState` signature
change already narrated in
[build-log 0095 §1](0095-a-crash-the-kernel-cleans-up.md), not a new defect
and not this cycle's to fix. `drift_check.py`'s own independent re-run is in
§9 of this entry, since it is the one gate command this cycle's own
instructions required docs-scribe to run directly.

## 7. Handoffs

- The `schema.ts` regeneration mechanically pulled in 3 unrelated
  `DiscoveryReport` fields (`sitemap_fetch_attempts`/`sitemaps_blocked`/
  `sitemap_offhost_skipped`) from another session's pre-existing uncommitted
  work in `discovery.py` — not authored or reviewed by this cycle. Flagged
  for whoever owns that other work to confirm it is intentional; not
  re-investigated here per this cycle's own scope boundary.
- The gate-blocking concurrent-session issues (GSC org-account/`ApiState`
  wiring, Redis/Celery/Postgres typing, `chaos_test.py` lint) are not this
  cycle's to fix.
- A future cycle can source and verify a real glyph-width table and wire the
  4 `*_PIXELS` ids into the existing `_RULES` gap without touching anything
  else — `content_signals.py` and `audit_export.py`'s `_RULES` table were
  both shaped so this drops in cleanly (ADR 0014's own follow-up note).

## 8. Explicitly not done

- `pixel_width.py` / `test_pixel_width.py` were not created — see §3. The 4
  `*_PIXELS` ids remain `NOT_MEASURED`.
- `async_discovery.py` was not modified — not needed, see §4's correction; it
  shares `discovery.py`'s `SiteGraph.record_fetch` implementation already.
- `discovery.py`'s `sitemap_fetch_attempts`/`sitemaps_blocked`/
  `sitemap_offhost_skipped` fields, and the sitemap-related lines they touch
  in the same file's diff, were not re-described or re-investigated — flagged
  as pre-existing uncommitted work from another session that happened to land
  in a file this cycle also touched (§7).
- Duplicate detection (`*_DUPLICATE`) is not gated on indexability, matching
  the pre-existing `_over_50k` precedent — a shared title between an
  indexable page and a 404 page with the same generic title would still
  register. Recorded as a deliberate consistency choice in ADR 0014, not
  fixed here.
- No new ADR from docs-scribe this cycle: ADR 0014 already exists on disk,
  written by the implementing agent per its own acceptance criteria; this
  entry only cites it.

## 9. Drift check — independently re-run

```
$ .venv/Scripts/python.exe scripts/drift_check.py
Running Architecture & Documentation Drift Audit...

--- Drift Audit Results ---
PASSED: no drift detected across 167 markdown files.
  - all relative links resolve
  - all domain modules documented
  - all skill directories populated
```

Run after the README.md / docs/ARCHITECTURE.md updates in §10 were made, so the
167-file count and clean result reflect this cycle's own drift edits, not a
stale prior run.

## 10. Files changed

- `src/modules/seo/page_classifier/content_signals.py` — new, 279 lines.
- `tests/modules/seo/test_content_signals.py` — new, 230 lines, 34 tests.
- `src/modules/seo/page_classifier/discovery.py` — `extract_content_signals`
  import, `DiscoveredNode` +8 fields, `record_fetch()` hook,
  `to_page_evidence()` passthrough. This file also carries substantial
  pre-existing uncommitted sitemap-related changes from another session,
  unrelated to this cycle (§8).
- `src/modules/seo/page_classifier/signal_parsers.py` — `PageEvidence` +8
  fields.
- `src/modules/seo/page_classifier/schemas.py` — `FullPageIntelligenceProfile`
  +8 fields, `""`/`0`/`False` defaults.
- `src/modules/seo/page_classifier/cascading_pipeline.py` — passes 8
  `evidence.*` fields through to the profile constructor.
- `src/modules/seo/page_classifier/audit_export.py` — `_UNFETCHED` frozenset,
  `_normalize_text`, 10 new `_RULES` entries, `_duplicates_by` + 3 sibling
  helpers, `_CROSS_PROFILE_RULES` dispatch dict, rewritten
  `NOT_MEASURED_REASONS`. 391 lines total.
- `tests/modules/seo/test_audit_export.py`,
  `tests/modules/seo/test_canonical_capture.py`,
  `tests/modules/seo/test_cascading_pipeline.py`,
  `tests/modules/seo/test_page_classifier_schemas.py` — extended, see §5.
- `rankuno-ui/src/types/schema.ts` — regenerated via
  `scripts/export_ui_contract.py`; also picked up 3 unrelated
  `DiscoveryReport` fields from another session's in-flight work (§7).
- `docs/adr/0014-native-title-h1-meta-description-extraction.md` — new,
  written by the implementer.
- This entry: `docs/build-log/0096-twenty-nine-measured-eighty-one-not.md`.
- `docs/build-log/README.md` — index row added.
- `README.md`, `docs/ARCHITECTURE.md` — drift updates for the new module and
  the coverage change (§9 of this cycle's own procedure).

## 11. Follow-ups

- Source and verify a real per-character glyph-width table (with provenance
  recorded) so the 4 `*_PIXELS` ids can move to `MEASURED` (ADR 0014's own
  follow-up).
- Confirm with the owner of the concurrent sitemap-fields work
  (`sitemap_fetch_attempts`/`sitemaps_blocked`/`sitemap_offhost_skipped`)
  whether their mechanical appearance in this cycle's `schema.ts` regeneration
  is intentional.
- Resolve the gate-blocking concurrent-session issues (GSC org-account/
  `ApiState` wiring, Redis/Celery/Postgres typing) so `verify.ps1` can be
  independently re-run green end-to-end again.
