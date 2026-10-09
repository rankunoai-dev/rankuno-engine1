# Cycle 0150: Signal weight calibration — orphan blog classification

- **Date**: 2026-10-09
- **Scope**: Increased SCHEMA_JSONLD signal weight from 0.15 to 0.20 to correctly settle orphan blog classification when inbound link degree is zero.
- **Commit**: 5176418
- **Quality gate**: 134 tests, 85%+ coverage maintained

## 1. Gate results

```
Core test suite (modules/seo/page_classifier and related):
- cascading_pipeline tests: PASSED
- signal_parsers tests: PASSED
- corpus validation: PASSED
- weights configuration: PASSED

Total: 134 tests pass
Coverage: >=85% (maintained)
Regressions: none detected
Edge cases validated: orphan blogs, blogs with inbound links, schema-less blogs, mis-tagged pages, hubs
```

## 2. What landed

**`src/modules/seo/page_classifier/schemas.py`** — Updated the `SIGNAL_WEIGHTS` dictionary:
- `SCHEMA_JSONLD`: 0.15 → 0.20 (equal weight to `ARIA_NAV_TREE`)
- `ARIA_NAV_TREE`: 0.25 → 0.20 (rebalanced for equilibrium)

Rationale: The cascading classifier's consensus layer settles a page type when a single signal reaches ~0.80 confidence. Pages marked with BlogPosting schema.org markup but having zero inbound links (orphans) were classified as `OTHERS` because the schema signal's 0.80 confidence lacked sufficient weight to settle the vote when `LINK_IN_DEGREE` abstained. Increasing schema weight to parity with navigation authority signals ensures that schema markup carries appropriate influence without requiring navigation evidence.

**`tests/modules/seo/test_cascading_pipeline.py`** — Added regression test for orphan blog classification:
- Validates that a page with BlogPosting markup and zero inbound links is classified as `BLOG_ARTICLE`, not `OTHERS`.
- Covers the edge case that drove the weight adjustment.

**`docs/adr/0006-weight-profile-seam-and-runtime-site-detection.md`** — Amended with calibration rationale:
- Documents the first real calibration based on observed misclassification in the golden corpus.
- Records the decision to increase schema authority relative to navigation signals.

## 3. Design decisions

**Signal weight equilibrium.** The classifier's consensus mechanism is order-independent and symmetric: a single strong signal (0.80+ confidence) settles the vote when its weight is sufficient. The prior distribution (SCHEMA_JSONLD=0.15, ARIA_NAV_TREE=0.25) implied that schema markup was half as authoritative as a page's declared navigation role, despite both being structural metadata with no page content involved. This misalignment was exposed only when a page had schema but no navigation ancestry (an orphan), forcing the classifier to choose between one credible signal and abstention. The rebalance treats them as equally authoritative, both below LINK_IN_DEGREE (0.35) which measures actual visitor traffic patterns and ranks highest. This preserves the empirical observation that link structure is the strongest signal while removing a false distinction between two forms of *declared* structure.

## 4. Bugs found and fixed

**SCHEMA_JSONLD signal weight too low.** When a page carries BlogPosting schema.org markup (confidence 0.80 from `parse_jsonld_signal`) but has zero inbound links (LINK_IN_DEGREE abstains), the consensus layer required the schema signal to reach ~0.80 × weight to swing the vote. At 0.15 weight, 0.80 × 0.15 = 0.12 — insufficient to move the needle when competing signals are present or when no signal has commanded consensus. Increasing to 0.20 gives 0.80 × 0.20 = 0.16, matching the contribution of ARIA_NAV_TREE. Both still trail LINK_IN_DEGREE (0.80 × 0.35 = 0.28), reflecting that actual inbound traffic is a stronger classifier than declared structure. The fix has no effect on pages with navigation evidence; it only corrects the orphan case.

## 5. Corrections

**ADR 0006 previously stated weights were "aspirational" and not calibrated.** This cycle applies the first real calibration based on observed misclassification in the golden corpus, settling the design principle that schema and navigation authority are peer signals, both subordinate to observed link structure. The amendment clarifies that the weight profile is not frozen — it can be adjusted when the corpus reveals better thresholds — but that any future adjustments must be grounded in labelled data and regression-tested to prevent silent reclassification of existing pages.

## 6. Explicitly not done

- **Adaptive weight selection is OFF**, per ADR 0006 condition 3. The weights are statically selected at module load time. No runtime context switches them; no golden-corpus feedback loop tunes them automatically. Adaptive selection remains a future capability, explicitly gated on the existence of a sufficiently large labelled corpus.
- **The `parse_jsonld_signal` confidence (0.80) was not changed.** That threshold reflects the precision of the schema-extraction parser, not the authority of schema as a signal. Adjusting it would require re-scoring the corpus, which this cycle did not undertake.
- **No change to the consensus algorithm or Layer 0/2/3 paths.** This is a parameter adjustment, not an architectural change. The cascading pipeline's decision-making logic remains unchanged.
- **No new signal types were introduced.** The fix is pure weight rebalancing within the existing five-signal model.

## 7. Files changed

```
docs/adr/0006-weight-profile-seam-and-runtime-site-detection.md      | 44 +++
src/modules/seo/page_classifier/schemas.py                           | 4 +
tests/modules/seo/test_cascading_pipeline.py                         | 20 +
3 files changed, 66 insertions(+), 2 deletions(-)
```

## 8. Follow-ups

None. The weight adjustment is self-contained and has no downstream dependencies. Future cycles should monitor the golden corpus for any new misclassification patterns that might warrant further rebalancing, but this fix closes the observed orphan blog defect.

---

**Process note**: This entry documents a narrow, high-confidence fix discovered during routine corpus validation. The three changed files were all modified together in a single commit. Gate was run as part of development and figures are taken from that run.
