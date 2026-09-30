# Cycle 0129: Two pages that differed only by case

- **Date**: 2026-09-30
- **Scope**: URL path case is preserved in the page identity; Search Console and GA4 matching keep
  case-insensitivity only as an explicit, reported fallback
- **Commit**: `383d01f`, plus `5c0d149` (ADR renumbered 0026 → 0027 at integration), pushed to
  `origin/main` as `5c0d149`
- **ADR**: [0027](../adr/0027-url-path-case-is-significant.md)
- **Quality gate**: GREEN on the combined tree of cycles 0127, 0128 and 0129. `pytest --cov=src`
  exit code 0, "Required test coverage of 85.0% reached. Total coverage: 92.90%". No pass count
  printed; see §1.

## 0. Background

Found during the URL-provenance investigation ([0127](0127-a-reason-the-crawl-never-recorded.md)).
`normalize_path` (`url_rules.py`) lowercased the whole path with `s.lower()`, so `/A` and `/a`
became one `SiteGraph` node. On a case-sensitive server they are different resources. Screaming
Frog crawls them as two URLs and Google indexes them as two. The engine showed one page's HTML,
classification and discovery reason for both, and under-counted pages.

The implementing agent stopped before changing anything. Build-log 0079 §4.1 records the collapse
as intended. On inspection, that ruling was about a test fixture: two fixture rows collided because
`/Blog/` and `/blog/` shared a key, and the entry concluded "the code was right; the fixture was
wrong". The lowercasing dated from the initial commit (`ba6f1b8`) with no recorded reason, and 0079
cited no real-site evidence that merging case variants was the lesser harm. The question went to
the user, who chose to **preserve path case**.

## 1. Gate results

Shared with 0127 and 0128: one run, by the lead, on the combined tree after all three branches
merged into `provenance-integration` with no conflicts.

```
ruff format --check .                    -> 550 files already formatted
ruff check .                             -> All checks passed!
mypy src                                 -> Success: no issues found in 152 source files
scripts/export_ui_contract.py --check    -> UI contract is up to date.
scripts/drift_check.py                   -> PASSED: no drift detected across 215 markdown files.
pytest --cov=src                         -> exit code 0
                                            Required test coverage of 85.0% reached. Total coverage: 92.90%
```

The pytest pass-count summary line did not print (same buffering artifact as build-log 0098 §1 and
0100 §1). No test count is claimed.

```
tsc --noEmit                             -> exit 0
vitest                                   -> Test Files  47 passed (47)
                                            Tests  605 passed (605)
npm run build                            -> ✓ built in 8.07s
```

The regression tests were run by the lead against the pre-fix code (fail) and the fix (pass). The
scribe did not re-run them.

## 2. What landed

**`page_classifier/url_rules.py`.** `normalize_path` no longer lowercases. Scheme and host are still
lowercased, `www.` is still folded, and the query, fragment, trailing-slash and percent-decoding
rules (build-log 0037) are unchanged. Percent-escapes that survive decoding (structural escapes,
and runs that are not valid UTF-8) now have their hex digits upper-cased, per RFC 3986 §6.2.2.1.

**`performance/url_identity.py`, `performance/schemas.py`.** Google-URL-to-crawled-page resolution
keeps case-blind matching only as a fallback, reported as the new `MatchTier.CASE_FOLDED`. At each
level (absolute URL, path with query, bare path) an exact case-preserving lookup is tried first, so
an exact spelling always wins. The folded index applies the same ambiguity rule as the other tiers:
if two crawled pages differ only by case, a Google row matching neither exactly resolves to
`MatchFailure.AMBIGUOUS` and is given to neither. The fold covers the path only, never the query.

`URL_UPPERCASE` detection is unaffected; it always read the raw URL.

## 3. Design decisions

- **Why upper-case the kept escapes.** Before, the global `lower()` made `%2f` and `%2F` one key as
  a side effect. Removing it without this step would have split one address into two keys, the
  exact false-duplicate class build-log 0037 closed.
- **Why keep a case-folded tier at all.** Search Console and GA4 report URLs as Google saw them;
  links in the wild vary in case more than the crawled graph does. Dropping case-folding entirely
  would have turned a class of resolvable rows into misses. Keeping it silent would have hidden
  which rows matched only by folding. An explicit tier reports it.
- **Why `AMBIGUOUS` rather than first match.** Two crawled pages that differ only by case are now
  two pages. Giving a folded-only Google row to either one would misassign traffic.
- **Why not the query.** Query-string case is application-defined; folding it would merge distinct
  parameter values.

## 4. Bugs found and fixed

| Bug | Where | Effect |
| :--- | :--- | :--- |
| Whole path lowercased | `url_rules.normalize_path` | `/A` and `/a` merged into one node: wrong HTML, classification and discovery reason for one of them; page counts low |
| `%2f`/`%2F` would split once the lowercase went | `url_rules.decode_percent_escapes`, `_decode` | Caught during implementation, before shipping |

**Tests that were wrong.** Seven tests encoded the lowercasing as expected behaviour and were
changed deliberately to assert case preservation (across `test_url_rules.py`,
`test_audit_export.py` and `test_discovery.py`, per the implementer; the scribe did not recount).
They were not wrong about the code; they pinned a ruling that is now reversed.

## 5. Corrections

- **Build-log 0079 §4.1 is reversed.** It said of `/Blog/` vs `/blog/`: "The code was right; the
  fixture was wrong", and that the collapse "is a documented feature rather than a surprise". The
  ruling rationalised behaviour that already existed; it offered no real-site evidence. Case
  variants are now two pages. Duplicates that really are one page (scheme, `www.`, slashes,
  tracking parameters, percent-encoding) still collapse. 0079 is left as written.
- **Build-log 0079 §2.1 ("`normalize_url` lowercases, collapses slashes and strips parameters")** is
  no longer true of the path. `normalize_url` lowercases scheme and host only.
- **ADR 0027 carries two stale statements.** Its header note ("Number chosen as next free on branch
  `fix-path-case`; may be renumbered at merge") was overtaken by `5c0d149`, which did renumber it.
  Its Consequences say "Checkpoints hold URLs only"; since cycle 0127 they also hold per-URL source
  letters. The conclusion that nothing there has to match still holds: checkpoints are never
  resumed.
- **ADR numbering collision, caught before landing.** The provenance and path-case branches were
  built in parallel and both claimed ADR 0026. At integration provenance kept 0026 and path case
  was renumbered to 0027, with its citations in `url_rules.py`, `performance/schemas.py`,
  `performance/url_identity.py`, `test_audit_export.py` and `test_url_identity.py` updated
  (`5c0d149`). Commit `383d01f`'s message still says "ADR 0026"; that citation means ADR 0027.

## 6. Explicitly not done

- **No data migration.** Stored crawls are not re-keyed on disk. Search Console resolution and
  `dedupe_profiles` recompute the key from the raw stored URL, so old results re-key under the new
  rule when read.
- **Counts across this change are not comparable** for sites that link the same path in mixed
  case: a new crawl reports more pages and spends more of the page budget than an old crawl of the
  same site.
- **`src/integrations/gsc_property_validator.py` still lowercases the whole property URL**, path
  included (`urlparse(property_url.lower())`, L47-48). Not changed.
- **`performance/url_identity.py` is 442 lines**, over the 400-line target in CLAUDE.md §9 (388
  before this cycle). Not split.
- **No case-variant finding in the reports.** A site serving one page under several casings without
  redirecting now shows them as separate pages, which is a real duplicate-content signal, but no
  report groups or flags them.

## 7. Files changed

```
383d01f
 docs/adr/0026-url-path-case-is-significant.md  | 61 ++++++++++ (renamed to 0027 in 5c0d149)
 src/modules/seo/page_classifier/url_rules.py   | 22 ++++--
 src/modules/seo/performance/schemas.py         |  8 ++
 src/modules/seo/performance/url_identity.py    | 64 ++++++++++++++--
 tests/modules/seo/test_audit_export.py         | 28 ++++++-
 tests/modules/seo/test_discovery.py            |  7 ++
 tests/modules/seo/test_url_identity.py         | 35 +++++++++
 tests/modules/seo/test_url_rules.py            | 35 +++++++--
 8 files changed, 242 insertions(+), 18 deletions(-)

5c0d149
 docs/adr/{0026 => 0027}-url-path-case-is-significant.md | 2 +-
 src/modules/seo/page_classifier/url_rules.py            | 2 +-
 src/modules/seo/performance/schemas.py                  | 2 +-
 src/modules/seo/performance/url_identity.py             | 2 +-
 tests/modules/seo/test_audit_export.py                  | 6 +++---
 tests/modules/seo/test_url_identity.py                  | 2 +-
 6 files changed, 8 insertions(+), 8 deletions(-)
```

## 8. Follow-ups

- Decide whether `gsc_property_validator.py` should keep path case too (§6).
- Split `url_identity.py` under 400 lines.
- A case-variant duplicate finding, if wanted.

Documentation drift for this cycle is recorded in [0127 §9](0127-a-reason-the-crawl-never-recorded.md#9-documentation-drift-step-8).
