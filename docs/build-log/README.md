# 📓 Build Log — Implementation Cycle Records

One entry per implementation cycle, written at the close of SDLC Step 8 and
committed alongside the code it describes.

---

## Why this exists

ADRs record **what was decided**. Git history records **what changed**. Neither
records the thing that is most expensive to lose: **why the code looks the way it
does, what was tried, what broke, and what was deliberately left undone.**

A build-log entry captures:

- Reasoning that would otherwise survive only in a chat transcript.
- Bugs found during implementation and what the fix actually was — including
  bugs in the specification, not just in the code.
- Corrections to earlier claims. A wrong number that was published and then
  quietly fixed is worse than one that was never published.
- Work explicitly **not** done, so a later reader does not mistake a gap for an
  oversight, or an oversight for a gap.

The audience is a future engineer or agent with no memory of the session —
which, for an AI-assisted codebase, is every session.

---

## Index

| Cycle | Date | Title | Gate |
| :--- | :--- | :--- | :--- |
| [0001](0001-governance-foundation-and-safety-core.md) | 2026-08-06 | Governance foundation & Phase 1 safety core | 248 tests, 96.91% |
| [0002](0002-weight-seam-and-classification-pipeline.md) | 2026-08-07 | Weight-profile seam & classification pipeline | 424 tests, 96.59% |
| [0003](0003-http-fetcher-and-site-profiling.md) | 2026-08-07 | HTTP fetcher & site profiling | 475 tests, 95.95% |
| [0004](0004-three-path-merged-discovery.md) | 2026-08-07 | 3-path merged discovery | 554 tests, 94.99% |
| [0005](0005-governed-crawl-tool.md) | 2026-08-07 | Governed crawl tool | 583 tests, 95.10% |
| [0006](0006-async-crawl-and-tree-report.md) | 2026-08-07 | Concurrent crawl & hierarchy report | 638 tests, 94.50% |
| [0007](0007-first-live-run.md) | 2026-08-07 | First live run — 3 findings | 640 tests, 94.56% |
| [0008](0008-dom-budget-reserve.md) | 2026-08-07 | DOM discovery budget reserve | 646 tests, 94.55% |
| [0009](0009-golden-corpus.md) | 2026-08-07 | Golden corpus & evaluation harness | 705 tests, 94.92% |
| [0010](0010-draft-label-worksheets.md) | 2026-08-07 | Draft worksheets & multi-archetype crawls | 742 tests, 94.95% |
| [0011](0011-cms-pagination.md) | 2026-08-07 | Multi-page CMS retrieval | 777 tests, 95.15% |
| [0012](0012-live-api-and-unlimited-depth.md) | 2026-08-10 | Live API, job store, unlimited depth | 877 tests, 95.65% |
| [0013](0013-blocked-crawl-honesty.md) | 2026-08-10 | Blocked crawls fail instead of reporting success | 891 tests, 95.48% |
| [0014](0014-navigation-hierarchy.md) | 2026-08-11 | Header-navigation grouping and OTHERS | 943 tests, 95.57% |
| [0015](0015-navigation-dashboard.md) | 2026-08-11 | Navigation dashboard; browser mode actually works | 949 tests, 95.66% |
| [0016](0016-crawl-telemetry.md) | 2026-08-11 | Live crawl telemetry: progress, ETA, URL stream | 966 tests, 95.71% |
| [0017](0017-crawl-speed-and-unlimited-pages.md) | 2026-08-11 | Crawl speed presets; optional page ceiling | 987 tests, 95.74% |
| [0018](0018-stall-detection-and-partial-results.md) | 2026-08-11 | Bounded requests, stall detection, partial results | 992 tests, 95.75% |
| [0019](0019-checkpoints-and-partial-recovery.md) | 2026-08-11 | Crawl checkpoints, IPv6 parse fix, partial-tree recovery | 1,010 tests, 95.69% |

---

## Writing an entry

Copy the structure below. Numbering is sequential and never reused.

```markdown
# Cycle NNNN: <title>

- **Date**: YYYY-MM-DD
- **Scope**: one sentence
- **Commit**: <sha or "uncommitted at time of writing">
- **Quality gate**: <verbatim summary line>

## 1. Gate results
## 2. What landed          (per module: what it does, and WHY it is shaped that way)
## 3. Design decisions      (the choice, the alternatives, the reason)
## 4. Bugs found and fixed  (including spec bugs)
## 5. Corrections           (anything previously stated that turned out wrong)
## 6. Explicitly not done   (with the reason, so gaps read as decisions)
## 7. Files changed
## 8. Follow-ups
```

### Rules

1. **Write it in the same change as the code.** A log written later is a
   reconstruction, and reconstructions omit the parts that were embarrassing.
2. **Record failures, not just outcomes.** A test that caught a real bug is more
   useful to a future reader than three that passed first time.
3. **State what is not done, and why.** Section 6 is not optional. Most
   misunderstanding of this codebase will come from someone assuming a declared
   contract has an implementation behind it.
4. **Never revise history.** If a later cycle proves an earlier entry wrong,
   correct it in the *new* entry's §5 and leave the original intact.
5. **Numbers must be real.** Paste gate output; do not summarise it from memory.
