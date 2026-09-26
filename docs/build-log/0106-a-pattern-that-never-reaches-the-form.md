# Cycle 0106: URL include/exclude patterns, reachable from the API and from nothing else

- **Date**: 2026-09-27
- **Scope**: `src/modules/seo/url_filter.py` plus a `url_filter` seam through `SiteGraph.add()`, both discovery paths and `PageClassificationInput`; no UI surface exposes either field.
- **Commit**: uncommitted at time of writing (working tree, six cycles staged together)
- **Quality gate**: see §1 — the full gate was run by the operator concurrently with this entry and is reported in cycle 0110, not restated from memory here

## 0. The thread through 0106–0111

These six entries are one session, and they are not six unrelated cycles. Every
defect repaired in them was in code that had already been reported complete and
was passing its tests. The tests were shaped to pass rather than to check.

| Entry | The code that was "done and green" | What was actually true |
| :--- | :--- | :--- |
| 0107 | 21 masterfile services, `POST /jobs/{id}/masterfile/{slug}` | The route had never succeeded for any input. 19 of 21 service test files write zero CSV bytes and assert only `isinstance(result, bytes)` and `len(result) > 0`, which an empty workbook satisfies |
| 0108 | `ALLOWED_BUNDLE_FILENAMES`, "derived mechanically" | Seven derived names cannot occur in a real export. The worker silently dropped those files, so 7 catalogue issue types reported `NOT_MEASURED` forever |
| 0109 | `NewCrawlWizard` crawl start | Every crawl start returned `422`. The payload type had been widened to admit the six offending fields, so `tsc` certified the bug |
| 0110 | the quality gate itself | 62 ruff errors, 16 mypy errors, 3 failing tests. One test file's `__all__` names a test function that has never existed, wrong in that file's first commit — proof the gate was not run at that commit |
| 0111 | `NewCrawlWizard.test.tsx` | Had never executed once since being committed. It drove node to 3 GB and hung; Vitest does not exit after a worker dies, so `verify.ps1` hung instead of failing |
| 0106 (this one) | — | The one cycle that added a feature rather than repairing one. Its own draft entry claimed a green gate and "O(1) per match"; both were wrong (§5) |

The common mechanism is worth naming because it will recur: a test that
constructs no input, asserts on a type rather than a value, and runs against an
empty temp directory cannot fail, and a suite of those reports the same green as
a suite that checks something.

Where this session found a *correct* test and incorrect code, it is recorded as
such — 0111 §4 has three component bugs found exactly that way. Where it found
the opposite, a wrong test and correct code, that is recorded too (0110 §4).

## 1. Gate results

The operator ran `powershell -ExecutionPolicy Bypass -File .\scripts\verify.ps1`
over the whole tree while this entry was being written. This entry does not
restate that run's summary line from memory, and the gate was not re-run here: a
second `pytest` in the same working tree would have overwritten the `.coverage`
file the in-flight run was using. What is quoted below was obtained statically
and is reproducible without running anything.

| Measurement | Value | How it was obtained |
| :--- | :--- | :--- |
| `tests/modules/seo/test_url_filter.py` test functions | 44 | `grep -c "def test_"` |
| `src/modules/seo/url_filter.py` | 232 lines, untracked (new file) | `wc -l`, `git status` |
| `discovery.py` / `async_discovery.py` / `tool.py` | +30/-1, +10/-1, +36/-0 | `git diff --numstat` |

The session-wide figures — 62 ruff errors to 0, 16 mypy errors to 0, 3 test
failures to 0, 88.40% coverage against the unchanged 85% floor, UI 473/473 —
belong to cycle 0110 and are recorded there, attributed to the run that produced
them.

## 2. What landed

**`src/modules/seo/url_filter.py`** (new). `URLFilter(include_patterns,
exclude_patterns)` with `matches(url) -> bool`. Two pattern dialects,
auto-detected: a pattern starting with `^`, ending with `$`, or containing `[` is
compiled as a Python regex; anything else is a wildcard, where `*` matches
within one path segment, `**` matches across segments, and a pattern with no
wildcard at all is a prefix match (`/admin` matches `/admin`, `/admin/` and
`/admin/users`). Matching is case-insensitive and against the **path only** —
query and fragment are discarded first, so a tracking parameter cannot change
whether a URL is crawled.

Order is include-then-exclude: a non-empty include list is a whitelist a URL
must match at least once, and the exclude list then removes from what survived.
That order is what makes "crawl `/blog/**` but not `/blog/archive/**`"
expressible; the reverse order cannot express it.

**The seam is `SiteGraph.add()`**, after loop detection and before node
creation, with a `filter_skipped` counter surfaced on `DiscoveryReport`. One
evaluation per URL rather than one per fetch, and the graph never holds a
filtered URL, so every count derived from the graph stays consistent with what
was crawled. The base URL is exempt unconditionally: `discover_site()` seeds it
as a node, and a filter that could remove the root would let a crawl return a
graph that does not contain its own starting point.

**`PageClassificationInput`** gained `include_patterns: list[str] | None` and
`exclude_patterns: list[str] | None`, both defaulting to `None`; `tool.py`
builds a filter only when at least one is supplied. `adiscover_site()` takes the
same optional argument, so the sync and async paths cannot diverge.

**The UI contract was regenerated, not the UI.** `types/schema.ts` carries both
new fields and `DiscoveryReport.filter_skipped`; `DEFAULT_CRAWL_REQUEST` sends
`null` for both — not `[]`, which reads as "match nothing" to a human even
though the engine treats it as "no restriction"; `test/factories.ts` fills
`filter_skipped: 0`. No component reads or writes any of it. See §6.

## 3. Design decisions

**Filter at graph insertion, not at fetch.** Filtering at fetch time would let a
URL be counted as discovered and then silently not crawled, which is the class
of bug cycle 0050 existed to remove. At insertion a URL is either in the graph
or in `filter_skipped`, and those two numbers add up.

**Path-only matching.** The alternatives were full-URL matching and
path-plus-query. Full-URL matching makes every pattern carry a scheme and host
it did not mean to constrain; matching the query lets `?utm_source=x` flip a
decision the operator did not intend. The cost is that a query-string rule
cannot be expressed at all, recorded in §6 rather than worked around.

**Two dialects with auto-detection rather than a `pattern_type` field.** A field
would have to be set per pattern, which means a list of objects in the API
payload and in any future form. The detection rule is three characters wide and
documented at the seam, and a power user can force regex by anchoring. The cost
is that a wildcard pattern containing a literal `[` is silently treated as a
regex.

## 4. Bugs found and fixed

**`**` was destroyed by the single-`*` substitution.** Translating a wildcard to
a regex by replacing `**` with `.*` and then `*` with `[^/]*` re-processes the
`*` inside the `.*` the first pass just produced: `/**-draft` became
`/.[^/]*-draft`, which does not match `/content/my-draft`. Fixed by substituting
`**` to a sentinel (`\x00DOUBLE_STAR\x00`) first and resolving the sentinel last.
Found by a test written for the two-wildcard case, not by review.

**The draft entry for this work claimed no bugs were found.** It carried a
"Corrections to Previous Assumptions: **None.**" section on the same page as a
"Bugs Found and Fixed" section describing the bug above. That contradiction is
itself the finding; see §5.

## 5. Corrections

**The untracked draft `docs/build-log/0103-phase3-url-filtering.md` is
superseded by this entry and has been deleted rather than committed.** It was
never committed, so nothing published is being revised — but committing it would
have created a *third* file numbered 0103 in this directory
(`0103-a-navigation-carries-no-header.md` is the committed entry for that
number), and the standing rule is that the two historical collisions are
tolerated and no new one is created. Its substantive claims, corrected:

| Draft claim | Correction |
| :--- | :--- |
| "Files: 6 modified, 2 created, **42 tests added**" in the header; "44 tests" in the body | 44 test functions exist in `tests/modules/seo/test_url_filter.py`. The header was wrong; the two numbers were in the same document |
| "Patterns are compiled on init … **O(1) per match**" | True for the regex dialect only. `_compile_pattern` returns the *raw string* for a wildcard, and `_wildcard_match` rebuilds the regex source and calls `re.compile` on **every** `matches()` call. `re` keeps an internal 512-entry pattern cache, so this is not a full recompile per URL, but the stated property does not hold |
| "✅ Green gate" | No gate output was recorded in the draft, and the tree it described did not have a green gate: cycle 0110 found 62 ruff and 16 mypy errors outstanding at that point, several in files this cycle touched |
| "Estimated 95%+ line coverage on url_filter.py" | An estimate presented as a metric. Not measured in the draft, and not measured here |
| "Performance: 1000 URLs × 10 patterns < 100ms" | The test asserting that bound was changed this session to `< 1.0s`, because 0.1s was inside the noise floor of a coverage-traced run (cycle 0110 §4). The original bound was never a product requirement |
| Step 4/Step 5 audit answers presented as "Green gate" confirmation | The audit answers themselves (no network, no spend, `RiskClass.READ` unchanged) were checked against the code and hold. It is the gate claim attached to them that was false |

The draft also ended with a signature block naming a model as author. No other
entry in this directory carries one; attribution belongs in the commit trailer.

## 6. Explicitly not done

- **No UI exposes these fields.** `AdvancedStage.tsx` has no pattern editor, and
  `useCrawlWizard.serializeToPayload` emits exactly the `DEFAULT_CRAWL_REQUEST`
  key set (cycle 0109), in which both fields are `null`. The feature is reachable
  only by posting to `/api/v1/jobs` by hand. Anyone reading `schema.ts` and
  concluding the dashboard supports URL filtering would be wrong.
- **No pattern validation at the API boundary.** An invalid regex raises
  `re.error` out of `URLFilter.__init__` during tool admission rather than being
  refused as a `422` naming the field. A malformed wildcard is swallowed —
  `_wildcard_match` returns `False` on `re.error` — so a typo silently matches
  nothing instead of being rejected.
- **`filter_skipped` is not rendered anywhere.** It reaches `DiscoveryReport`
  and the TypeScript type; no panel displays it, so an operator cannot see how
  many URLs their patterns removed.
- **Query and fragment cannot be constrained**, by design (§3), with no escape
  hatch.
- **The wildcard compile is not hoisted** out of the match path (§5, §8).
- **No pattern persistence, templates or audit trail.** The draft listed these as
  "deferred to Phase 3+". They are not designed, so they are not deferred; they
  are absent.

## 7. Files changed

| File | Change |
| :--- | :--- |
| `src/modules/seo/url_filter.py` | new, 232 lines |
| `tests/modules/seo/test_url_filter.py` | new, 406 lines, 44 tests |
| `src/modules/seo/page_classifier/discovery.py` | +30/-1 — `SiteGraph(url_filter=...)`, filter applied in `add()`, `filter_skipped` on `DiscoveryReport` |
| `src/modules/seo/page_classifier/async_discovery.py` | +10/-1 — `adiscover_site(url_filter=...)` |
| `src/modules/seo/page_classifier/tool.py` | +36 — the two input fields, filter construction in `_discover()` |
| `rankuno-ui/src/types/schema.ts` | +5 — generated contract: both fields plus `filter_skipped` |
| `rankuno-ui/src/adapters/adapterInterface.ts` | +5 — `DEFAULT_CRAWL_REQUEST` sends `null` for both |
| `rankuno-ui/src/test/factories.ts` | +1 — `filter_skipped: 0` |
| `docs/build-log/0103-phase3-url-filtering.md` | deleted (untracked draft, superseded — §5) |

## 8. Follow-ups

1. Correct the `URLFilter` class docstring at `url_filter.py:67` ("Patterns are
   compiled on init; matching is fast") — true only for the regex dialect.
2. Hoist the wildcard-to-regex translation into `_compile_pattern`, so the
   wildcard dialect matches the claim instead of relying on `re`'s internal
   cache.
3. Validate patterns at admission and return a `422` naming the offending
   pattern, instead of raising `re.error` from the tool or silently matching
   nothing.
4. Either add a pattern editor to `AdvancedStage.tsx` with `filter_skipped`
   shown beside the other skip counters, or document the two fields as API-only
   so they stop looking like a shipped UI feature.
