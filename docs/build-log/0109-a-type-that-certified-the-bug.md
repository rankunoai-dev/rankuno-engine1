# Cycle 0109: Every crawl start in main returned 422; the payload type had been widened to allow it

- **Date**: 2026-09-27
- **Scope**: `useCrawlWizard.serializeToPayload` posts exactly the keys `PageClassificationInput` declares; the widened `CrawlJobInput` type is deleted.
- **Commit**: uncommitted at time of writing
- **Quality gate**: see §1; session-wide figures in cycle 0110
- **Session thread**: entry 4 of 6 — see [0106 §0](0106-a-pattern-that-never-reaches-the-form.md)

## 1. Gate results

Statically obtained (the operator's full-gate run was in flight; see cycle 0110).

| Measurement | Value | How it was obtained |
| :--- | :--- | :--- |
| `useCrawlWizard.test.ts` `it(` blocks | 9 → **11** | counted at `HEAD` and in the working tree |
| Keys removed from the posted payload | **6** | `git diff` on `useCrawlWizard.ts` |
| Lines deleted from `types/crawlWizard.ts` | 30 | `git diff --numstat` (+9/-30) |
| Python files touched by commit `8d606db`, which claimed to extend `PageClassificationInput` | **0** | `git show 8d606db --name-only` |

## 2. What landed

`serializeToPayload()` now returns `PageClassificationInput` and builds the body
from `DEFAULT_CRAWL_REQUEST` plus the fields the model declares. The six
offending keys — `source`, `proxy`, `auth`, `custom_headers`, `verify_ssl`,
`ga4_property_id` — are no longer spread into it. They remain in
`CrawlWizardFormData`, so the advanced stages keep collecting them and the form
still round-trips what the operator typed; the fix was to stop *posting* them,
not to gut the UI that gathers them.

`CrawlJobInput`, the `PageClassificationInput & { six extras }` intersection, is
deleted. `crawlWizard.ts`'s module docstring now says why there is intentionally
no "request plus Phase 2 extras" type, so the next person to need one reads the
reason before reintroducing it.

Two new tests, and one rewritten:

- `posts exactly the keys PageClassificationInput declares` compares
  `Object.keys(payload).sort()` against `Object.keys(DEFAULT_CRAWL_REQUEST).sort()`.
  Compared against that constant rather than a hand-written list, because it is
  typed as the generated `PageClassificationInput`: a backend field added to the
  contract has to be added there too, so the test tracks the schema instead of
  drifting from it.
- `keeps the advanced-stage fields out of the payload` asserts the six by name.
- `still records proxy and auth in wizard state` pins that dropping them from the
  body did not remove them from the form.

## 3. Design decisions

**Assert the whole key set, not the absence of six names.** A test that lists
six forbidden keys passes the day a seventh is added. Comparing the full key set
against the generated default fails on any undeclared key, which is the actual
contract `extra="forbid"` enforces.

**Delete the widened type rather than mark it deprecated.** Its only value was
making an invalid payload type-check. There is no migration to stage: nothing
else referenced it.

**Keep collecting the six fields.** The alternative — removing the advanced
stages — would discard working UI for a server limitation, and would have to be
rebuilt when a backend field exists. The docstring records the rule that closes
the loop: add the field to the Pydantic model first, and this mapping second.

## 4. Bugs found and fixed

**Every crawl start from the dashboard returned `422`.** `PageClassificationInput`
inherits `StrictModel`, which sets `extra="forbid"` (CLAUDE.md ruling 4), so an
undeclared key does not get ignored — the whole request is rejected. The payload
carried six of them. Since commit `8d606db` replaced `LiveCrawlModal` with
`NewCrawlWizard` in `DashboardShell.tsx` (`DashboardShell.tsx:22,304` — the
wizard is the only crawl entry point the shell renders), this was not a
degraded path, it was the *only* engine-crawl entry point. `main` could not start
a crawl.

**The root cause is the type, not the payload.** `CrawlJobInput` was declared as
`PageClassificationInput & { source?, proxy?, auth?, custom_headers?,
verify_ssl?, ga4_property_id? }`, and the payload reaches `startCrawl` as a
**variable**, not an object literal. TypeScript's excess-property check applies
only to fresh object literals assigned to a typed target, so it never fired: the
widened type made the invalid body type-correct at both the construction site and
the call site. `tsc --noEmit` was green on a request the server could only
refuse. That is the reason this can only be caught by a test that inspects the
posted key set, and the new test's own docstring says so.

**`validateDomain` accepted invalid domains** — found by the gate work in cycle
0110 and recorded there, since the fix landed in `lib/validation.ts` with that
cycle's lint pass. It is relevant here only because both defects were in the same
wizard.

## 5. Corrections

### 5.1 Commit `8d606db`'s message

| Claim in the commit message | Measured |
| :--- | :--- |
| "API schema: Extended `PageClassificationInput` with optional Phase 2 fields (proxy, auth, custom_headers, verify_ssl, ga4_property_id, source)" | **No Python file is in that commit.** `git show 8d606db --name-only` lists 16 files: 12 `.tsx`/`.ts`, one build-log entry, and `.worker_consumed_jobs.json`. What was actually extended was a new TypeScript intersection type, `CrawlJobInput`, in `rankuno-ui/src/types/crawlWizard.ts`. The Pydantic model was never touched, which is precisely why the payload was refused |
| "Quality Gate: PASS — 397 tests passing (69 new + 328 existing)" | Not reproducible. The four test files added in that commit contain 68 `it(` blocks, not 69 (21 + 29 + 9 + 9), and 9 of those — the whole of `NewCrawlWizard.test.tsx` — cannot pass: the file hangs the runner (cycle 0111). A run that reported PASS did not include this file |
| "Hook tests (15)" | `useCrawlWizard.test.ts` contains **9** `it(` blocks at that commit and at `HEAD` |
| "Validation tests (27)" | 29. An undercount, unlike the rest, but it shows the numbers were not read off a run |
| "TypeScript strict: 0 errors" | True, and beside the point — see §4. A later commit, `76079b9` ("Resolve all TypeScript compilation errors in crawl wizard"), indicates the claim was also not true at the time it was made |

`.worker_consumed_jobs.json`, a runtime artifact, was committed with that change.
Not fixed here; noted so it is not mistaken for a fixture.

### 5.2 Build-log `0102-phase2-new-crawl-wizard.md`

Not edited, per the standing rule. It carries the same false claims: "Total:
**69 new tests** across 4 test files", "Hook: 15 tests", "All tests passing (exit
code 0 on npm test)". Corrected by the table above. The entry also describes the
wizard's advanced stage as sending fields that are "stored but not yet consumed
by the crawl engine" — they were not stored anywhere; they were rejected at the
door, and the crawl never started.

That entry is also absent from the build-log index, which is part of why nothing
caught up with it. It has been added to the index in this session.

## 6. Explicitly not done

- **No backend field was added for any of the six.** Proxy, HTTP auth, custom
  headers, SSL-verification opt-out and a GA4 property id are collected by the
  UI and consumed by nothing. Anyone reading `AdvancedStage.tsx` and concluding
  the engine honours a proxy would be wrong.
- **`useCrawlWizard` still has no test that a payload is actually accepted by the
  server.** The new tests assert the key set against the generated contract, which
  is a shape check, not an integration check. A field that exists on the model but
  is rejected by validation (a bad range, say) would still get through this test.
- **Nothing prevents the next widened type.** The rule is written in a docstring
  and enforced by one test on one hook. Another component that builds its own
  body is unconstrained.
- **`crawlWizard.ts`'s `CrawlSource` and `BasicAuthCredentials` types remain**,
  because the form state still uses them.

## 7. Files changed

| File | Change |
| :--- | :--- |
| `rankuno-ui/src/hooks/useCrawlWizard.ts` | +15/-11 — returns `PageClassificationInput`; the six keys dropped; docstring records why |
| `rankuno-ui/src/types/crawlWizard.ts` | +9/-30 — `CrawlJobInput` deleted, module docstring rewritten |
| `rankuno-ui/src/hooks/useCrawlWizard.test.ts` | +69/-3 — 9 → 11 tests, key-set contract test |

## 8. Follow-ups

1. Add the six fields to `PageClassificationInput` (and the fetcher that would
   honour them) or remove the advanced stage that collects them. Today it is
   neither.
2. One test that posts a serialized payload through the real FastAPI app and
   asserts `200`/`202` rather than a key set, so a valid-shaped but invalid-valued
   body is caught too.
3. Delete `.worker_consumed_jobs.json` from the repository and add it to
   `.gitignore` if it is a runtime artifact.
