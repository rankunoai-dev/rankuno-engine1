# Cycle 0142: A page body released once read

- **Date**: 2026-10-07
- **Scope**: Crawl memory, step 2. Everything a crawl reads from a page body is now read when the
  page lands, and every body except the homepage's is released at that moment. The ADR 0031 budget
  charges a body as it lands and credits it back on release, charges a flat 32 KiB plus the page's
  measured retained bytes, and charges a page's links until its BFS level is recorded. Measured on
  2,001 ~1 MB pages: 1.4504 MiB/page before, 0.0247 after
  ([ADR 0035](../adr/0035-a-crawl-releases-each-page-body-once-read.md), amending
  [ADR 0031](../adr/0031-a-crawl-stops-at-a-shared-memory-budget-fair-share-first.md)).
- **Commit**: branch `html-extract-at-fetch` on `origin/main` `1eff2d0`: `e81e4a1` (P0), `f00b181`
  (P1), `6484334` (P2), `093083f` (P3), `ad92e92` (P4a), `d74cf55` (P4b), `5258968` (P4c), `08bf84b`
  (P4d, docs), `f5fd1e8` (R1/R2), `db5ec3d` (CLAUDE.md §8, by the lead). This entry and the scribe's
  doc fixes (§7) are uncommitted at time of writing.
- **Quality gate**: refactorer's run on `f5fd1e8`: 4367 passed, 2 skipped, 93.65%. LEAD GATE:
  GREEN, 4367 passed, 2 skipped, 93.14% (§1).

**Numbering note**: the highest committed entry is `0140` on `origin/main` (fetched 2026-10-07), on
every local branch and in every worktree. `0141` was skipped: the main checkout holds an
uncommitted draft `0141-a-fetched-flag-that-outlives-the-body.md` written by another session of the
user's, covering P1-shaped edits the user has decided to discard in favour of this branch. Reusing
the number would have created a collision if that draft were ever committed. `0142` was free in
this worktree, on `origin/main`, on every local and remote-tracking ref, in the other 25 worktrees, and
in the main checkout.

## 0. Background

Railway crawls of sites with ~1 MB HTML pages (mrrooter.com, 36k URLs; groundsguys.com, 8k) were
OOM-killed (inferred, [build-log 0136](0136-a-crawl-that-stops-before-the-container-does.md) §0).
The ADR 0031 budget was step 1, a safety net: it stops the largest over-share crawl cleanly, which
for a lone crawl of such a site was at about 1,400 pages. This cycle is step 2: stop retaining the
bodies.

The user pasted another assistant's "Stream-and-Release" analysis and asked for a read-only
investigation of it before any code. Findings:

| Claim in the pasted analysis | Finding |
| :--- | :--- |
| Moving breadcrumb and JSON-LD extraction to fetch time frees the bodies | Not on its own. The async crawl extracted links **after the whole BFS level**, so the level's results list held every body until the boundary. A prototype measured 770 MiB both ways |
| Lean per-page state is ~1 KB | **Refuted.** Measured 20–36 KiB per page |
| ~80 MB at 36k pages | **Refuted.** Extrapolated 0.7–1.3 GiB |
| "Signal 3, schema.org" | It is Signal 4, `parse_jsonld_signal` |
| Some post-crawl step needs HTML from many pages | No. The header menu reads the homepage only; every other reading is of a page's own body |

A scratch prototype held the golden output identical with bodies released.

Side discoveries, not fixed here (handed off, §8):

- Signal 2 (ARIA nav) never fires in production: `to_page_evidence` never sets `nav_links`.
- `LoopWatcher` memory grows with link occurrences, not URLs (~19 KB per node with 3-segment URLs).
- A resumed crawl loses the menu tree and the homepage sidecar.
- The nav parser resolves menu links against `base_url`, ignoring the landed URL and `<base href>`.

User decisions, in order:

| Question | Decision |
| :--- | :--- |
| Approach | Option A, "extract at fetch, phased" |
| Uncommitted P1-shaped edits from another session in the main checkout | Leave them; build separately in this worktree |
| P0–P2 plan | Approved |
| P3–P4 | Approved to continue |
| URL ceiling | 8,192 characters |
| Links per page | 5,000 cap accepted |
| CLAUDE.md §8 update | Approved (applied by the lead in `db5ec3d`) |
| Which Phase 1 wins | This branch's, over the other session's |
| A "fix" for redirected-page link resolution (Step 3) | Approved, then withdrawn once the premise was shown false (§5.1); re-confirmed: keep today's behaviour |

Security review of the P4 design: **PASS WITH CONDITIONS**, C1–C10 plus 14 required tests. Findings:

| # | Severity | Finding | Where it is met |
| :--- | :--- | :--- | :--- |
| F1 | HIGH | Derived data outlives the body and is uncharged: a page could evade the budget by putting its weight in breadcrumbs, types, canonical or redirect hops | Caps (P4a) and measured `retained_page_bytes` charged on land (P4c) |
| F2 | — | Links uncounted | Cap of 5,000 (P4a); link bytes charged (R2) |
| F3 | — | An extraction error's traceback keeps the body alive | `exc.with_traceback(None)` in `_ahtml` |
| F4 | — | "Projected ≤ today's" is false | §5.2; ADR 0035 states the real bound |
| F5 | — | A silent clamp hides double-credit bugs | Over-credit logged at ERROR; conftest fixture fails the test |
| F6 | — | Mixed-mode flag | Read once per crawl, fixed on the `SiteGraph` |

Follow-up review: three deviations accepted (measured charging in place of a fixed C1 constant;
`links_capped` not in `DiscoveryReport`; caps active with the rollback flag off). It found a new
**HIGH**: a 104 KB body with a long same-site `<base href>` and 200 `href="?n"` anchors produced
20,013,290 bytes of link strings, about 193x the body. R1 and R2 were required and landed in
`f5fd1e8`.

---

## 1. Gate results

LEAD GATE (run by the lead on `db5ec3d`, main venv, `import src` resolved to the worktree):

```
ruff format --check .            -> 653 files already formatted
ruff check .                     -> All checks passed!
mypy src                         -> Success: no issues found in 175 source files
export_ui_contract.py --check    -> UI contract is up to date.
drift_check.py                   -> PASSED: no drift detected across 240 markdown files.
pytest --cov=src                 -> Required test coverage of 85.0% reached. Total coverage: 93.14%
                                    4367 passed, 2 skipped, 1 warning in 1340.93s (0:22:20)
```

The lead's run measured 93.14% coverage where the refactorer reported 93.65% for the same test count;
the difference is unexplained (both are far above the 85% floor) and is recorded rather than smoothed.
After this run the lead made two description-only fixes (the `ALLOWED_SCHEMES` docstring displaced by
`MAX_FETCH_URL_LENGTH` in `src/core/url_safety.py`, §4.5, and the `crawl_release_page_html` description
in `src/core/config.py`); ruff format/check, mypy on both files and `tests/core/test_url_safety.py`,
`tests/core/test_config.py`, `tests/modules/seo/test_long_urls.py` passed after them.

The refactorer's gates, as reported by the refactorer per phase. Not re-run by the scribe:

| Commit | Phase | Passed | Coverage |
| :--- | :--- | ---: | ---: |
| `e81e4a1` | P0 | 4259 | 93.53% |
| `f00b181` | P1 | 4272 | 93.53% |
| `6484334` | P2 | 4282 | 93.58% |
| `093083f` | P3 | 4300 | 93.59% |
| `ad92e92` | P4a | 4314 | 93.61% |
| `d74cf55` | P4b | 4325 | 93.62% |
| `5258968` / `08bf84b` | P4c / P4d | 4350 | 93.63% |
| `f5fd1e8` | R1/R2 | 4367 (2 skipped) | 93.65% |

On `f5fd1e8`, also as reported: ruff 653 files, mypy 175 files, `drift_check` PASSED (240 markdown
files).

The scribe ran the cycle's targeted tests in this worktree, main venv, `import src` resolving to
`.claude\worktrees\html-extract-at-fetch\src\__init__.py`, on `db5ec3d`:

```
python -m pytest --no-cov -p no:cacheprovider -o addopts="" \
    tests/core/test_memory_budget_credit.py tests/core/test_memory_budget.py \
    tests/modules/seo/test_async_landed_links.py tests/modules/seo/test_extraction_caps.py \
    tests/modules/seo/test_fetch_time_extraction.py tests/modules/seo/test_fetched_set.py \
    tests/modules/seo/test_golden_extract_at_fetch.py tests/modules/seo/test_link_charges.py \
    tests/modules/seo/test_long_urls.py tests/modules/seo/test_release_bodies.py \
    tests/modules/seo/test_tool_homepage_sink.py tests/modules/seo/test_async_discovery_memory_budget.py
============================ 154 passed in 58.05s =============================
```

The golden snapshot was not touched after it was written: `git diff --stat e81e4a1..HEAD --
tests/fixtures/golden` is empty (scribe, on `db5ec3d`).

### Memory

Method (refactorer): 2,001 pages of ~1 MB HTML served in-process to `PageClassificationTool`
through a fake fetcher, a fresh process per run, Windows peak working set, median of 3.

| Tree | Release | MiB / page | Peak (MiB) |
| :--- | :--- | ---: | ---: |
| `1eff2d0` (before) | — | 1.4504 | 2961.4 |
| P1 / P2 | — | 1.4504 | — |
| P3 | — | 1.4523 | — |
| P4 | off | 1.4525 | — |
| P4 | on | 0.0245 | 109.3 |
| `f5fd1e8` (R1/R2) | on | 0.0247 | 109.5 |

The lead's independent run on the P4 tree: release on 0.02478 MiB/page (peak 109.8 MiB, 12.8 s);
release off 1.4525 (peak 2966.6 MiB, 13.8 s).

Extrapolated, not measured: about 0.9 GiB at 36k such pages with release on, against about 51 GiB
with it off.

---

## 2. What landed

Each phase was its own commit, and each was required to leave the committed golden snapshot
passing unchanged on the serial path and on the async path under three completion orders.

**P0, `e81e4a1`: the golden test (tests only).** `tests/modules/seo/golden_site_factory.py` builds
a deterministic 503-node site served in-process: a redirected homepage with a header menu, a 404,
a PDF answered 200, `/moved/` → `/new/sub/` with relative links, an empty HTML body, non-ASCII
pages, a relative-href loop that evicts fetched nodes, DOM and JSON-LD breadcrumbs, JSON-LD types
(one broken block) and sitemap-only orphans. Completion order is shuffled deterministically by
per-path `asyncio.sleep(0)` yields seeded by string, and a guard test proves the seeds really
reorder. The snapshot `tests/fixtures/golden/extract_at_fetch_500.json.gz` is 50,907 bytes gzipped,
1,201,935 bytes of canonical JSON, taken from the serial path. `test_tool_homepage_sink.py` pins
that the homepage body reaches `homepage_sink` exactly once, under the requested key, not at all
when unfetched, and that a failing sink does not fail the job. The site's fetcher uses its own
quota key so the shared 600/min `BaseAPIClient` bucket does not pace the serial run.

**P1, `f00b181`: "fetched" is a set.** `SiteGraph._fetched` is written only in `store_html` and
discarded only on loop eviction. `unfetched_urls` reads it instead of "has a stored body", so the
definition that checkpoints and resume rely on does not change when bodies go. An empty HTML body
still counts as fetched. Fail-before: removing the eviction discard failed 5 tests; leaving empty
bodies unmarked failed 8.

**P2, `6484334`: the async task extracts links.** `_ahtml` returns a private `_LandedPage` (url,
links, `links_if_evicted`, error) instead of `(url, body)`, so a level's results list no longer
carries bodies. Links are still **recorded** after the level in input order, so node order, result
order and page-ceiling refusals do not depend on completion order. An extraction error is captured
and re-raised by the level loop at that page's input position. For a redirected page, links are
also extracted against the requested URL, because an earlier sibling can evict the node before the
boundary and `landed_url` then answers the requested URL (§5.1); any third answer raises
`AssertionError`. Fail-before: replacing the re-raise with `continue` failed 3 tests; dropping the
redirected fallback failed 3 async-vs-serial tests.

**P3, `093083f`: breadcrumbs and schema types at fetch.** `store_html` fills `_breadcrumbs`
(section labels, resolved against `node.url`, exactly as `to_page_evidence` did) and
`_jsonld_types` (recognised schema.org types, document order). `PageEvidence.jsonld_types` is a new
optional field, default `()`. `parse_jsonld_signal` reads the body when present (corpus, tests),
otherwise the stored types; the first recognised type wins either way.
`extract_schema_types` skips a block too deep to parse (`RecursionError`) like a broken one.

**P4a, `ad92e92`: bounds (C1, C2).** Breadcrumb label 256 characters. Schema types de-duplicated,
first 8, and a type over 256 characters is not recognised (in `_recognised`, so both Signal 4 paths
agree). Canonicals over 2,048 dropped, not truncated. `HttpFetcher` refuses an over-long requested
or redirect-hop URL as `UnsafeUrlError` (not retried, recorded `guardrail_refused`).
`MAX_LINKS_PER_PAGE = 5,000` on both paths via `SiteGraph.cap_links`, overflow counted on
`SiteGraph.links_capped` and logged `page_links_capped`.

**P4b, `d74cf55`: budget credits (C4, C9, C10).** `MemoryAccount` gains `landed_body_bytes`,
`credited_body_bytes` and overhead. `MemoryBudget.credit` raises on a negative count, clamps against
outstanding **body** bytes (never total charged, so overhead cannot be credited away), logs an
over-credit at ERROR with job id and counts, never decrements `pages`, never selects a victim. The
in-flight reserve uses the landed-body mean. An autouse fixture in `tests/conftest.py` fails any
test that logs `crawl_memory_budget_over_credit`; `allow_over_credit` opts out for clamp tests.
Mutations (clamp against total; no clamp; victim on credit; pages decremented; charged-mean
reserve) each failed at least one test.

**P4c, `5258968`: release (C3, C5, C7, C8).** `SiteGraph(release_bodies=...)`; `store_html`
returns `released` and keeps the body only when `normalize_url(url) == normalize_url(base_url)`,
under the requested key. `_ahtml` stores, charges `body + LEAN_PAGE_BYTES + retained_page_bytes`,
extracts links, then credits the body if released, with no `await` in that stretch (comment plus an
AST test). No credit on the error path, and the traceback is dropped. `Settings.crawl_release_page_html`
(`CRAWL_RELEASE_PAGE_HTML`, default true) is read once per crawl in the tool; it is not a request
field. The tool output is byte-identical with release on and off.

**P4d, `08bf84b`: docs.** ADR 0035, the ADR 0031 amendment, README, ARCHITECTURE, and docstrings in
`tool.py` and `state_store.py`.

**R1/R2, `f5fd1e8`.** `MAX_FETCH_URL_LENGTH = 8192` moved to `src/core/url_safety.py` as the single
constant for both the fetcher refusal (was 2,048 in `http_fetcher`) and `extract_page_links`, which
now drops a longer resolved link before collecting it. `charge_links` charges the `getsizeof` of a
page's link tuple and its strings (both readings when redirected) as it lands; the level loop
credits it with `credit_links` once the page is recorded. An abandoned level and the pages after an
extraction error keep their link charge (safe over-count). Link accounting applies with release on
and off.

Tests collected in the new files: `test_memory_budget_credit.py` 11, `test_async_landed_links.py`
10, `test_extraction_caps.py` 15, `test_fetch_time_extraction.py` 18, `test_fetched_set.py` 13,
`test_golden_extract_at_fetch.py` 17, `test_link_charges.py` 9, `test_long_urls.py` 7,
`test_release_bodies.py` 15, `test_tool_homepage_sink.py` 10 (125 in total).

---

## 3. Design decisions

Full reasoning is in ADR 0035. The points a later reader most needs:

**Phased, each phase golden-equivalent.** The risk was not memory but silently different output.
Every phase had to pass one committed snapshot on both paths under three completion orders before
the next began. Moving the definition of "fetched" (P1) and moving link extraction (P2) were done
while bodies were still retained, so a regression there could not be confused with one from release.

**Keep the homepage only.** The header menu is read once from the homepage after the crawl, and
`homepage_sink` persists it. No other post-crawl step needs a body. The homepage is matched by
normalised key, because a raw-string match missed a trailing slash or capitalised host (§4.2).

**Charge what a page keeps, measured.** A flat `LEAN_PAGE_BYTES` (32 KiB) covers structure (node,
loop-watcher share, evidence and profile). What the page derived from its body is measured with
`getsizeof` and charged on top, because the worst case at every cap (≤ 256 KiB, test 12) exceeds
the constant. The bound is a sanity check on the caps; the measurement is the mechanism.

**The rollback flag rolls back body release only.** Caps, the 8,192 ceiling, the 5,000-link limit
and link charging stay with it off. The reviewer ruled that caps must not be tied to the flag; the
lead accepted link charging applying in both modes for the same reason.

**8,192, not 2,048.** The user chose 8,192 for the fetch ceiling. The audit contract's 2,048 is a
separate export rule. URLs of 2,049–8,192 characters behave exactly as on `1eff2d0`, including the
export failure below.

**Fair share holds structurally.** Victim selection is unchanged and a credit only lowers a
projection. The cost: small-page crawls reach their share sooner (§5.2).

---

## 4. Bugs found and fixed

### 4.1 A reversed-types mutation passed the golden test

Each golden page declares at most one JSON-LD type, so the snapshot cannot see type order. A
mutation that reversed stored types passed it. A targeted multi-type order test in
`test_fetch_time_extraction.py` now fails that mutation. The golden test was never a proof of order.

### 4.2 A raw-string homepage match passed until a key-rule test was added

A C3 mutation that matched the homepage by raw string instead of normalised key first passed. A
unit test of the key rule (`test_3_the_homepage_is_recognised_by_normalised_key_not_spelling`,
parametrised over spellings of the root) now fails it.

### 4.3 Link strings could be ~193x the body (follow-up review HIGH)

A same-site `<base href>` near the length limit, under many short relative hrefs, made every link a
full-length string: 104 KB of body became 20,013,290 bytes of links, held until the level was
recorded and uncharged. Fixed by R1 (drop links over 8,192 at extraction) and R2 (charge link
bytes while in flight).

### 4.4 An extraction error in the task would have been silently swallowed

`asyncio.gather` returning `None` for a page whose extraction failed would leave the page fetched
but uncounted. P2 carries the error on `_LandedPage` and re-raises it at the page's input position,
which is where it was raised before. Pinned by fail-before (3 tests).

### 4.5 Found, not fixed: `ALLOWED_SCHEMES` lost its docstring

`f5fd1e8` inserted `MAX_FETCH_URL_LENGTH` and its docstring between `ALLOWED_SCHEMES` and the
attribute docstring that documents it in `src/core/url_safety.py`. The text "Only plain web schemes.
Blocks `file:`…" now sits as a stray string literal after `MAX_FETCH_URL_LENGTH`'s docstring.
Behaviour is unaffected; the documentation of the scheme allowlist is detached. Found by the scribe
while reviewing; not fixed because source files were off-limits during the lead's gate run (§8).

---

## 5. Corrections

### 5.1 Serial does not resolve an evicted redirected page's links against `final_url`

The Step 3 plan stated that the serial path resolves a redirected page's links against
`final_url` when an earlier sibling has evicted its node, and proposed aligning async with it. The
user approved that "fix". The premise was wrong: serial evicts the node **before** fetching it, so
`record_fetch` finds no node, `landed_url` answers the requested URL, and both paths resolve
against the requested URL. "Fixing" async would have broken parity. P2 keeps today's behaviour; the
user re-confirmed after the correction.

### 5.2 "Projected ≤ today's" was false

The P4 design said a crawl's projected total would be at or below what ADR 0031 charged. Security
review F4 showed otherwise: every fetched page now costs at least `LEAN_PAGE_BYTES`. At the default
614 MiB share, a crawl reaches it at about 19k pages (614 MiB / 32 KiB ≈ 19,660), where a site of
10 KB pages reached it at about 60k under ADR 0031. What holds is the cross-org invariant: a crawl
at or under its share is never stopped by another org's load. ADR 0035 states the bound as
`projected ≤ ADR 0031's + pages × LEAN_PAGE_BYTES + Σ retained` and makes no "≤ today's" claim.

### 5.3 The pasted analysis's numbers

"~1 KB lean state" (measured 20–36 KiB per page) and "~80 MB at 36k pages" (extrapolated 0.7–1.3
GiB; ~0.9 GiB from this cycle's measured slope, still an extrapolation) were both wrong, and "Signal 3, schema.org" is Signal 4. Moving
breadcrumb and JSON-LD extraction alone saved nothing (770 MiB both ways); link extraction had to
move too (§0).

### 5.4 Build-log 0136 and ADR 0031 per-page figures

[Build-log 0136](0136-a-crawl-that-stops-before-the-container-does.md) §3 and ADR 0031 give ~2.2
MiB retained per page on ~1 MB sites and stop points of about 280 pages (five crawls at their
share) and about 1,400 (a lone crawl). With release on, those are superseded: 0.0247 MiB/page
measured, and stop points of about 19k and about 98k pages, set by the 32 KiB floor rather than the
body. They still describe `CRAWL_RELEASE_PAGE_HTML=false`. ADR 0031 carries an amendment; 0136 is
left as written.

### 5.5 ADR 0035 and the ADR 0031 amendment overstated "exactly ADR 0031's" (scribe, this cycle)

As committed in `08bf84b` and kept in `f5fd1e8`, ADR 0035 said that with release off "the
accounting is exactly ADR 0031's" and the flag "charges exactly as ADR 0031", and the ADR 0031
amendment said "With it off, everything above stands as written". Since R2 a page's links are
charged in both modes while its level is in flight, so mid-level the total is higher, and an
abandoned level keeps its link charge. `test_1_release_off_charges_bodies_exactly_as_adr_0031`
asserts exactly that: link charges net to zero at the end, bodies match ADR 0031. The three
sentences now say the **body** accounting is ADR 0031's, plus the in-flight link charge. The
README sentence "a crawl reaches its share at about 19k pages, whatever the page size" now says
"with bodies released", because with the flag off it is false. `src/core/config.py`'s
`crawl_release_page_html` description has the same "exactly as ADR 0031 did" wording and was not
changed (source file; §8).

### 5.6 CLAUDE.md §8 crawl-memory gap

The §8 entry "A crawl holds its entire graph, including page HTML, in RAM" was false by default
after this branch. The lead rewrote it in `db5ec3d` (user-approved). Not edited by the scribe.

---

## 6. Explicitly not done

- **The crawl graph is still in RAM.** P4 removed bodies, not the graph. ADR 0001's disk spill and
  Bloom filter for 500k–100M are not started.
- **P5, not started:** serial-path parity (memory account and cancel); a resumed crawl carrying the
  homepage sidecar; `LoopWatcher` holding one entry per URL rather than per link occurrence; a text
  contract for Layer 2/3, which now receive evidence with `html=None` for every page but the
  homepage.
- **`links_capped` is not in `DiscoveryReport`.** It is on `SiteGraph` and in the log only. Adding
  it changes the persisted result contract.
- **No admission-time URL-length check.** A sitemap or CMS entry over 8,192 characters becomes a
  node and is refused only when fetched; its string is held and uncharged until then.
- **No meta-test for the over-credit fixture.** That `_fail_on_memory_over_credit` actually fails a
  test is not itself tested.
- **The budget is still not an OOM guarantee.** Uncounted: sitemap and CMS bodies, the serial
  fallback, `/result` reads, deliverables, Screaming Frog jobs, imports, and discovered-but-unfetched
  nodes.
- **Not deployed, not observed on Railway.** All measurements are Windows peak working set. The 8 GB
  Railway limit and the Linux RSS slope are unverified, and the 36k-page figure is an extrapolation.
- **Files over the 400-line target, not split:** `discovery.py` 1,819 lines, `async_discovery.py`
  1,061, `tool.py` 1,266, `signal_parsers.py` 838, `memory_budget.py` 436.
- **`pages_fetched` is 0 on an aborted DOM crawl.** Seen during this cycle, unchanged.
- **Signal 2 (ARIA nav) never fires** (§0). Unchanged.
- **Audit export of 2,049–8,192-character URLs.** `AuditPage.url` rejects URLs over 2,048, so a
  crawl with any node URL in that range fails the workbook export with `AuditExportError`.
  Pre-existing on `1eff2d0`, pinned unchanged in `test_long_urls.py`.
- **The shared 600/min `BaseAPIClient` bucket still slows serial tests.** The golden fixture works
  around it with its own quota key.
- **The menu-parse base URL issue** (§0) is unchanged.

---

## 7. Files changed

From `git diff --numstat 1eff2d0..db5ec3d`:

| File | Change |
| :--- | :--- |
| `src/core/memory_budget.py` | +203 / −38 (credit, charge_links, credit_links, LEAN_PAGE_BYTES, landed-mean reserve) |
| `src/modules/seo/page_classifier/discovery.py` | +195 / −22 (`_fetched`, side tables, `store_html -> bool`, `retained_page_bytes`, `cap_links`) |
| `src/modules/seo/page_classifier/async_discovery.py` | +138 / −18 (`_LandedPage`, charge/credit in `_ahtml`, `credit_links` in the level loop) |
| `src/modules/seo/page_classifier/signal_parsers.py` | +106 / −22 (`extract_schema_types`, type caps, canonical cap, `PageEvidence.jsonld_types`) |
| `src/integrations/http_fetcher.py` | +23 / −1 (`_refuse_overlong`) |
| `src/core/url_safety.py` | +17 (`MAX_FETCH_URL_LENGTH`) |
| `src/core/config.py` | +15 / −3 (`crawl_release_page_html`) |
| `src/modules/seo/page_classifier/tool.py` | +16 / −7 |
| `src/modules/seo/page_classifier/discovery_parsers.py` | +6 |
| `src/core/state_store.py` | +4 / −3 (docstring) |
| `.env.example` | +5 |
| `tests/conftest.py` | +31 (over-credit fixture) |
| `tests/fixtures/golden/extract_at_fetch_500.json.gz` | new, 50,907 bytes |
| `tests/modules/seo/golden_site_factory.py` | new, 289 lines |
| `tests/modules/seo/test_golden_extract_at_fetch.py` | new, 276 |
| `tests/modules/seo/test_release_bodies.py` | new, 329 |
| `tests/modules/seo/test_fetch_time_extraction.py` | new, 236 |
| `tests/modules/seo/test_link_charges.py` | new, 218 |
| `tests/modules/seo/test_async_landed_links.py` | new, 197 |
| `tests/modules/seo/test_extraction_caps.py` | new, 197 |
| `tests/core/test_memory_budget_credit.py` | new, 174 |
| `tests/modules/seo/test_fetched_set.py` | new, 148 |
| `tests/modules/seo/test_long_urls.py` | new, 94 |
| `tests/modules/seo/test_tool_homepage_sink.py` | new, 92 |
| `tests/modules/seo/test_async_discovery_memory_budget.py` | +44 / −2 |
| `tests/modules/seo/test_discovery.py` | +19 / −8 |
| `tests/modules/seo/test_async_discovery.py` | +10 / −4 |
| `docs/adr/0035-a-crawl-releases-each-page-body-once-read.md` | new |
| `docs/adr/0031-a-crawl-stops-at-a-shared-memory-budget-fair-share-first.md` | +37 (amendment) |
| `README.md` | +26 / −17 |
| `docs/ARCHITECTURE.md` | +9 / −4 |
| `CLAUDE.md` | +14 / −7 (lead, `db5ec3d`) |

Uncommitted (scribe): this entry; the `docs/build-log/README.md` index row; the §5.5 wording fixes
in ADR 0035, the ADR 0031 amendment and `README.md`.

---

## 8. Follow-ups

| Owner | Item |
| :--- | :--- |
| `refactorer` | Restore `ALLOWED_SCHEMES`' docstring to directly follow it in `src/core/url_safety.py` (§4.5); align the `crawl_release_page_html` description in `src/core/config.py` with §5.5 |
| `refactorer` / next cycle | P5: serial parity (memory account, cancel); resume carrying the homepage sidecar; `LoopWatcher` one entry per URL; Layer 2/3 text contract |
| `api-data-engineer` | `links_capped` in `DiscoveryReport` |
| `feature-builder` | Admission-time URL-length check for sitemap/CMS/seed URLs |
| `test-engineer` | Meta-test that `_fail_on_memory_over_credit` fails a test that over-credits |
| audit-contract owner | `AuditPage.url` 2,048 limit vs crawled URLs up to 8,192 (`AuditExportError`) |
| `bug-fixer` | Signal 2 never fires (`nav_links` never set); `pages_fetched=0` on an aborted DOM crawl; nav parser ignores landed URL and `<base href>` |
| `refactorer` | `discovery.py` (1,819), `async_discovery.py` (1,061), `tool.py` (1,266), `signal_parsers.py` (838), `memory_budget.py` (436) over 400 lines |
| `test-engineer` | Shared 600/min `BaseAPIClient` bucket slowing serial tests |
| lead / operator | Deploy and observe on Railway; confirm the 8 GB limit and the Linux RSS slope |
