# Cycle 0112: The 4-stage wizard was wired to the wrong crawler, and was not relocatable

- **Date**: 2026-09-27
- **Scope**: The 4-stage new-crawl wizard removed and `LiveCrawlModal` restored on `DashboardShell`; `validateDomain` fixed, which had rejected the example its own help text gives.
- **Commit**: `bfb8518` — already on `origin/main` when this entry was written, which is a process anomaly in its own right (§8)
- **Quality gate**: **ALL GATES PASSED** — 3178 passed, 2 skipped, 88.40% against an 85% floor; UI 39 files / 455 tests
- **Session thread**: follows 0106–0111, all six of which describe code that was reported complete and was not. This cycle deletes a large part of what those six repaired.

## 1. Gate results

The pass/fail figures below are the run made during the implementing cycle,
recorded as reported. They were not re-executed here. What *was* verified in this
session is that they still apply: `bfb8518` changed **13 files, all under
`rankuno-ui/`, +207/−1972** (`git show --stat`), and **zero files under `src/`**,
so nothing in the commit can move a Python number.

```
Format:      499 files already formatted                        — PASSED
Lint:        All checks passed!                                 — PASSED
Type check:  Success: no issues found in 144 source files       — PASSED
Tests:       3178 passed, 2 skipped, coverage 88.40% (floor 85%) — PASSED
UI:          39 files, 455 tests                                — PASSED
ALL GATES PASSED.
```

Independently checked here, statically:

| Measurement | Value | How |
| :--- | :--- | :--- |
| Files changed | 13 (+207/−1972) | `git show --stat bfb8518` |
| Files under `src/` changed | **0** | same |
| UI test files | 41 → **39** | `git ls-tree -r cae8b17` vs `find rankuno-ui/src` |
| `NewCrawlWizard.test.tsx` blocks deleted | **15** | counted at `cae8b17` |
| `useCrawlWizard.test.ts` blocks deleted | **11** | counted at `cae8b17` |
| `validation.test.ts` blocks | 29 → **37** (+8) | counted at `cae8b17` and at `HEAD` |
| Arithmetic | 473 − 15 − 11 + 8 = **455** | matches the reported UI total exactly |
| Blocks skipped or weakened | **0** | no `it.skip` / `it.todo` in `validation.test.ts` |

A static `it(` / `test(` count across the UI tree gives **414**, not 455. The
difference is `it.each` / `describe.each` in `lib/navTree.test.ts` and
`styles/tokens.test.ts` (6 call sites), which expand at run time. The runner
figure is the real one; the static count is recorded here only so a later reader
who repeats the `grep` does not conclude a number was invented.

## 2. What landed

**`DashboardShell.tsx` renders `LiveCrawlModal` again.** A two-line diff — one
import, one JSX element — reversing exactly what `8d606db` had swapped out:

```diff
-import { NewCrawlWizard } from "../crawl/NewCrawlWizard";
+import { LiveCrawlModal } from "./LiveCrawlModal";
-        <NewCrawlWizard open={crawlOpen} onClose={() => setCrawlOpen(false)} />
+        <LiveCrawlModal open={crawlOpen} onClose={() => setCrawlOpen(false)} />
```

**Deleted.** `components/crawl/NewCrawlWizard.tsx` and its test,
`SourceStage.tsx`, `DomainStage.tsx`, `ConfigStage.tsx`, `AdvancedStage.tsx`,
`hooks/useCrawlWizard.ts` and its test, `types/crawlWizard.ts`. Each was
confirmed unreferenced by `grep` across `rankuno-ui/src` before deletion. The
wizard had no CSS file and no path alias, so nothing else needed unwinding.
`src/components/crawl/` and `src/hooks/` became empty and are gone —
`rankuno-ui/src/hooks` no longer exists as a directory.

**One type moved instead of dying.** `lib/urlParser.ts` imported `DomainOption`
from the deleted `types/crawlWizard.ts`. The 4-line interface now lives in
`urlParser.ts`, beside `extractDomainsWithCounts()`, the function that produces
it. It had been in a wizard-only type module for no reason other than that the
wizard was written first.

**`lib/validation.ts` reshaped around one parse.** A new internal
`parseDomain()` returns `{ host, error }` — exactly one of the two set — and both
`validateDomain()` and the new exported `normalizeDomain()` delegate to it. The
hostname regex is unchanged from the one cycle 0110 tightened; it is now applied
to the extracted hostname instead of to the raw input. See §4.

## 3. Design decisions

### 3.1 Removal rather than relocation, because the wizard is not relocatable

There are two crawl paths in this product and the wizard was attached to the
wrong one:

| | Path | Module |
| :--- | :--- | :--- |
| A | The engine's own native Python crawler | `src/modules/seo/page_classifier/` |
| B | Screaming Frog dispatched to a registered Windows worker | `src/modules/seo/screaming_frog_control/` |

The wizard existed to bring an older Screaming Frog-based tool's ("RAE",
reference copy at the repo root) configuration surface into this product. RAE is
a Screaming Frog tool, so those settings belong on path B. The wizard configured
path A.

The obvious repair — move the wizard to path B — is impossible, and the reason is
already recorded in the code, which is why this became a deletion rather than a
migration. The dispatch envelope carries nothing a config stage could fill:

* `ScreamingFrogJobInput` (`src/modules/seo/screaming_frog_control/schemas.py:164`)
  has **two fields**: `seed_url` and `template_name`.
* `WorkerJobEnvelope` (`src/core/worker_dispatch_schemas.py:109`) adds only
  transport metadata — `job_id` and `correlation_id` — and its docstring says
  "Deliberately carries nothing else: no crawl options, no path override, no raw
  command", enforced by `StrictModel`'s `extra="forbid"` (ADR 0015 condition 8).
* `template_registry.py:1` records the underlying finding, verified when ADR 0013
  was written: "none of max_pages, max_depth, respect_robots, user_agent, JS
  rendering, speed or exclude has a CLI counterpart". Those settings exist only
  inside a `.seospiderconfig`, which the same docstring documents as a Java
  `ObjectInputStream`-serialised file this codebase cannot author, validate, or
  fabricate a placeholder for.

So of the wizard's four stages, Source and Domain have somewhere to land on path
B (a URL-list upload and `seed_url`), and **Config and Advanced have nowhere at
all**. A security audit run during the implementing session returned DO NOT SHIP
on the remaining option — letting an operator upload an opaque
`.seospiderconfig` — which closes the last route. That verdict is recorded here
as reported by the implementing agent; it does not exist as a document in the
tree, so a later reader should treat the two code citations above, not the audit,
as the load-bearing evidence.

With two of four stages unplaceable and the user asking for the native crawler's
simple form back, removal was the outcome. This reverses `8d606db`; it does not
decide anything new, which is why no ADR accompanies it (§6.7).

### 3.2 A path, query, port or fragment is rejected, not normalised

`parseDomain()` strips a scheme and a single trailing slash. It **refuses**
anything else after the hostname, with a message naming the offending part.

The asymmetry is deliberate. A scheme and a bare `/` cannot change which site
gets crawled. A path can: someone who pastes `https://example.com/blog/` is
asking for a section, and someone who types `example.com:8080` is naming a
different origin. Normalising either to the whole of `example.com` would start a
crawl the operator did not ask for — an expensive failure that is hard to notice
afterwards — against the cheap failure of asking them to delete three characters.

### 3.3 `normalizeDomain` exists so the validator and its caller cannot drift

The exported `normalizeDomain()` has no caller today. It was added because the
bug in §4 was a *duplication* bug: `useCrawlWizard.serializeToPayload`
independently prepended `https://`, so the field's validator and the field's
consumer each held their own idea of what the box contained. Shipping the
normaliser next to the validator, sharing one parse, is what stops that
recurring on the path-B form.

## 4. Bugs found and fixed

### 4.1 `validateDomain` rejected the example printed directly beneath the field

`rankuno-ui/src/lib/validation.ts`. The function tested the **raw** trimmed input
against a bare-hostname regex and never stripped a scheme. So
`https://rankuno.com/` produced:

> Invalid domain format (e.g., www.example.com)

while the help text under the same input said the field accepts a domain "with or
without https://" and offered `https://example.co.uk` as a valid example.
Confirmed from a live screenshot of the running UI, not from reading the code.

**Pre-existing.** The regex tightening in
[build-log 0110](0110-what-the-gate-had-not-been-run-on.md) did not cause it: the
older `([a-z0-9-]*\.)*` pattern rejected a scheme for the same reason. 0110
changed which *malformed hostnames* were refused, not whether a scheme was
stripped.

**Why it survived, which is the part worth recording.** The existing test
asserted exactly one invalid input, `example..com`. The scheme case was never
exercised, so there was nothing for the suite to catch. That is the identical
failure shape that
[0106 §0](0106-a-pattern-that-never-reaches-the-form.md) names as this session's
thread: the tests were written against the code's behaviour, so they certified
it.

**Fix.** `parseDomain()` strips the scheme (rejecting a non-`http(s)` one by
name) and a single trailing slash, then applies the **unchanged** hostname regex
to the hostname alone. Interior whitespace is checked before any stripping — a
space means two things were pasted into one field, and no normalisation fixes
that. `validation.test.ts` went 29 → 37 blocks; no test was skipped or weakened.

## 5. Corrections

Per CLAUDE.md §2, corrected here and not by editing the entries concerned.

1. **Build-logs [0102](0102-phase2-new-crawl-wizard.md),
   [0106](0106-a-pattern-that-never-reaches-the-form.md),
   [0109](0109-a-type-that-certified-the-bug.md) and
   [0111](0111-a-test-that-had-never-run.md) all describe the 4-stage wizard as
   live.** It does not exist. Every `NewCrawlWizard`, `SourceStage`,
   `DomainStage`, `ConfigStage`, `AdvancedStage`, `useCrawlWizard` and
   `types/crawlWizard` reference in those entries is now historical.

2. **`8d606db`'s rewiring of `DashboardShell` is undone.** The mount point is
   `LiveCrawlModal` again, as it was before `8d606db`.

3. **Two cycles of real bug-fixing were deleted along with the component they
   fixed.** [0109](0109-a-type-that-certified-the-bug.md) fixed the wizard's
   `422` payload defect (`serializeToPayload` emitting six keys that
   `PageClassificationInput` forbids, with a widened TypeScript type certifying
   the bad body). [0111](0111-a-test-that-had-never-run.md) fixed three component
   defects — Cancel skipping `reset()`, `setSubmitting(false)` only on failure,
   and the payload being serialized after `onClose()`. All of that code is gone.
   Recording it plainly because it is a real cost of having built on the wrong
   path, and because a later reader who finds those entries will otherwise spend
   time looking for fixes that are no longer in the tree.

4. **`docs/ARCHITECTURE.md`'s "Backend support for the crawl wizard's advanced
   stage" row** described `AdvancedStage.tsx` as collecting proxy, auth, headers,
   an SSL opt-out and a GA4 property id. That file no longer exists; the row was
   rewritten in this cycle rather than deleted, because the underlying gap —
   nothing on either crawl path accepts those settings — is still true.

## 6. Explicitly not done

1. **`lib/urlParser.ts` and `lib/validation.ts` are retained with zero
   importers, deliberately.** Verified: `grep` across `rankuno-ui/src` finds only
   their own test files importing them. Both are engine-agnostic, and a path-B
   dispatch form needs exactly them — `urlParser` for a URL-list upload,
   `validation` for seed-URL entry. Both module docstrings now say so, so the
   state reads as a decision rather than as dead code awaiting a tidy-up. The
   consequence is that these exports are also unconsumed: `validateProxyUrl`,
   `validateRate`, `validateConcurrency`, `validateCustomHeaders`,
   `validateGA4PropertyId`, `estimateCrawlSeconds`, `formatCrawlTimeEstimate`
   and `normalizeDomain`.

2. **No `--crawl-list` support exists anywhere in `src/`.** `grep -rn
   "crawl-list" src/` returns nothing. The statement that `urlParser.ts` is
   waiting for a Screaming Frog URL-list upload describes an intended
   destination, not an implemented one. Nothing on path B accepts a URL list
   today.

3. **`LiveCrawlModal` still uses antd's deprecated `destroyOnClose`**
   (`LiveCrawlModal.tsx:164`). Restoring the modal makes that deprecation live
   again on the main crawl path. Already flagged in build-log 0075; not fixed
   here. The rename to `destroyOnHidden` has test-visible behaviour, because
   `destroyOnClose` is what resets the form between opens and several of the
   file's 10 tests depend on that. Three other components carry the same
   deprecated prop (`GscAccountForm.tsx:95`, `PerformancePanel.tsx:158`,
   `ReconcilePanel.tsx:225`), so this is one change across four call sites, not
   one file, whenever it happens.

4. **`LiveCrawlModal` and `validateDomain` hold opposite contracts for the same
   concept.** The modal's antd rule is `{ type: "url" }` and therefore requires a
   scheme; `validateDomain` produces a bare hostname. They do not interact today
   — nothing imports `validation.ts`. Whoever builds the path-B form must pick
   one, and must not assume the two agree because both validate "the domain
   field".

5. **`LiveCrawlModal`'s "Follow links (Path B)" field label was left alone**
   (`LiveCrawlModal.tsx:356`). In that label "path B" means sitemap-versus-link
   discovery *inside the native crawler*; in this entry's vocabulary path B means
   Screaming Frog. The collision is real and will confuse someone. Changing it is
   a user-visible string change nobody asked for, so it is recorded rather than
   made.

6. **The Python gate was not re-run in this session.** The figures in §1 are the
   implementing cycle's. Justified by the commit touching zero `src/` files —
   verified, not assumed — rather than by convenience.

7. **No ADR was written.** This cycle reverses a decision rather than making one,
   and the constraint that forced the reversal (the two-field Screaming Frog
   dispatch envelope) is already recorded in ADR 0015 condition 8 and referenced
   by ADR 0018. An ADR that said "the wizard has been removed" would duplicate
   this entry and add no ruling.

## 7. Files changed

All 13 files in `bfb8518`, plus this cycle's documentation.

| File | Change |
| :--- | :--- |
| `rankuno-ui/src/components/layout/DashboardShell.tsx` | +2/−2 — renders `LiveCrawlModal` |
| `rankuno-ui/src/lib/validation.ts` | +118/−22 — `parseDomain`, `normalizeDomain`, docstring rewritten |
| `rankuno-ui/src/lib/validation.test.ts` | +72 — 29 → 37 blocks |
| `rankuno-ui/src/lib/urlParser.ts` | +17/−1 — `DomainOption` moved in, docstring rewritten |
| `rankuno-ui/src/components/crawl/NewCrawlWizard.tsx` | deleted (266 lines) |
| `rankuno-ui/src/components/crawl/NewCrawlWizard.test.tsx` | deleted (380 lines, 15 blocks) |
| `rankuno-ui/src/components/crawl/SourceStage.tsx` | deleted (199 lines) |
| `rankuno-ui/src/components/crawl/AdvancedStage.tsx` | deleted (355 lines) |
| `rankuno-ui/src/components/crawl/ConfigStage.tsx` | deleted (163 lines) |
| `rankuno-ui/src/components/crawl/DomainStage.tsx` | deleted (123 lines) |
| `rankuno-ui/src/hooks/useCrawlWizard.ts` | deleted (181 lines) |
| `rankuno-ui/src/hooks/useCrawlWizard.test.ts` | deleted (205 lines, 11 blocks) |
| `rankuno-ui/src/types/crawlWizard.ts` | deleted (73 lines) |
| `docs/ARCHITECTURE.md` | advanced-stage gap row rewritten (§5.4) |
| `docs/build-log/README.md` | index row for this entry |
| `docs/build-log/0112-a-wizard-wired-to-the-wrong-crawler.md` | this entry |

## 8. Process anomaly: an unattended push to `main`

`bfb8518` was committed **and pushed to `origin/main`** by something other than
the agent doing the work and other than the main session, which had explicitly
been withholding the push pending user approval.

Only what is verifiable:

| Fact | Value |
| :--- | :--- |
| Author / committer | `Rankuno AI <Rankunoai@gmail.com>`, both |
| Date | `Sun Sep 27 17:05:29 2026 +0530`, author and commit date identical |
| Trailer | `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>` |
| `.git/hooks/` | stock `*.sample` files only, 14 of them, nothing executable installed |
| `scripts/verify.ps1` | contains no `git commit` / `push` / `add` / `checkout` / `restore` / `stash` |
| Remote state | `origin/main` == `bfb8518`; working tree clean |

No cause is asserted. The most likely benign explanation is a second assistant
working in the same clone, but nothing in the repository establishes that, so it
is offered as a possibility and not as a finding.

It belongs in the log because the failure mode is asymmetric: this unattended
push happened to carry a commit whose gate was green and whose content the user
had asked for. Nothing about the mechanism guarantees the next one will.

## 9. Follow-ups

1. Build the path-B dispatch form, and pick one of the two domain contracts in
   §6.4 when doing it. `urlParser.ts` and `validation.ts` exist for this and have
   no other reason to be in the tree.
2. Decide whether `--crawl-list` support is in scope for that form; today nothing
   on path B accepts a URL list (§6.2).
3. Migrate all four `destroyOnClose` call sites to `destroyOnHidden` in one
   change, adjusting `LiveCrawlModal`'s form-reset tests with it (§6.3).
4. Rename or requalify the "Follow links (Path B)" label if path-B-as-Screaming
   Frog becomes settled vocabulary (§6.5).
