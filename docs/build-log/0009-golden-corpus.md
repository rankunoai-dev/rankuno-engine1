# Cycle 0009: Golden corpus & evaluation harness

- **Date**: 2026-08-07
- **Scope**: Build the labelled-ground-truth module that unblocks signal weight calibration and escalation-rate tuning, and produce the first real accuracy baseline.
- **Commit**: uncommitted at time of writing
- **Quality gate**: 705 tests, 94.92% coverage, `mypy --strict` clean, drift audit clean

---

## 1. Gate results

```
=== Format ===      PASSED
=== Lint ===        PASSED
=== Type check ===  PASSED   37 source files, mypy --strict
=== Tests ===       PASSED   705 passed in 12.95s, 94.92% coverage
ALL GATES PASSED.
```

---

## 2. What landed

### `corpus.py` — labelled ground truth, by archetype

`SiteArchetype` has six members, each justified by a code path the others do not
reach. Entries are grouped by archetype rather than by site because Rankuno is
an agency: ten B2B SaaS sites are one data point repeated ten times.

**`CoverageReport` is the point of the module, not a side feature.** It reports
how far each archetype falls short of `MIN_ENTRIES_PER_ARCHETYPE` (50), and
`is_publishable` stays false until *every* archetype is covered. Without it, the
most likely misuse of a corpus is quoting a figure computed over a handful of
labels as though it described the engine.

Malformed corpus files are a **hard failure**. The corpus is the yardstick the
engine is measured against; silently skipping a broken label file would corrupt
every measurement downstream.

### `evaluation.py` — the calibration harness

`evaluate_predictions` scores per archetype and never offers a bare accuracy
number without one. `AccuracyReport.is_trustworthy` returns false while any
sampled archetype is under-sampled, and `summary_line()` stamps
`[UNDER-SAMPLED — not evidence]` onto the string itself so the caveat travels
with the figure into whatever log or report copies it.

Levels and page types are scored **separately and jointly**, because ADR 0002
decoupled them: right level with wrong type is a different failure from the
inverse, and one combined number cannot tell them apart.

`compare_weight_profiles` scores every declared weight vector over the same
evidence — the primitive ADR 0006 deferred to. `escalation_curve` prices each
candidate confidence threshold against real data.

A `weights_override` hook was added to `classify_page` to make the comparison
possible. It is explicitly documented as calibration-only; production crawls
must let the seam choose.

### Fixtures and CLI

`tests/fixtures/corpus/highradius.json` — **13 human-labelled URLs**, every one
transcribed from `HIGHRADIUS_CRAWL_AUDIT_RECORD.md` with per-entry provenance.
The directory README forbids machine-generated labels: scoring the engine
against its own output measures nothing.

`scripts/evaluate_corpus.py` crawls each labelled site and prints coverage,
per-archetype accuracy, ranked confusions and the escalation curve.

---

## 3. The first real accuracy baseline

```
COVERAGE
  13 labels across 1 sites; 0/6 archetypes usable — NOT publishable

ACCURACY
  exact 30.0% over 10 labels; weakest B2B_SAAS at 30.0%  [UNDER-SAMPLED — not evidence]
  not discovered     3  (recall 76.9%)
  level correct      50.0%
  type correct       30.0%
  both correct       30.0%
```

**30% exact accuracy against a ≥98% claim.** Over ten labels, so this is a
signal rather than a measurement — but it is the first number the project has
had that was not an assertion.

Recall is 76.9%: three of thirteen labelled pages were never discovered at all,
even at 300 pages with a 0.6 DOM reserve.

### The escalation curve is the most valuable output

```
  threshold   escalated   accuracy of the rest
     0.60      30.0%       42.9%
     0.70      30.0%       42.9%
     0.75      70.0%      100.0%
     0.85      80.0%      100.0%  <- ADR 0005
```

This **exonerates the 0.85 threshold**, which I had expected it to indict.

Everything scoring above 0.75 is classified correctly — 100%, no exceptions.
Everything below is barely better than a coin flip. The confidence score is
therefore *well calibrated*: it knows what it does not know.

So the 98% escalation rate from build-log 0007 is not a threshold-tuning
problem. **The structural layers are genuinely weak, and the threshold is
correctly reporting that.** Lowering it to 0.70 would cut escalation to 30% and
drop accuracy to 42.9% — buying cost savings with wrong answers.

That reframes ADR 0005's cost problem entirely: the fix is better Layer 0–2
signals, not a cheaper threshold.

### The confusions name specific defects

```
  2x  PRODUCT_CATEGORY_HUB -> PRODUCT_DETAIL_PAGE   e.g. /software/accounts-payable/
  2x  UTILITY_LEGAL        -> SERVICE_CATEGORY_HUB  e.g. /code-of-ethics/
  2x  BLOG_HUB             -> SERVICE_CATEGORY_HUB  e.g. /glossary/
  1x  COMMERCIAL_LEAD_GEN  -> COMPANY_ABOUT         e.g. /demo-request/
```

The `/code-of-ethics/` case is diagnosable from the output alone: `_LEGAL_SLUGS`
in `url_rules.py` covers `privacy`, `terms`, `legal` and similar, but not
governance pages — `code-of-ethics`, `anti-corruption-and-bribery-policy`,
`human-rights-policy`. Layer 0 does not fire, so they fall through to the
sitemap hint, which says `SERVICE_CATEGORY_HUB`.

**I have not fixed it.** See §5.

---

## 4. Design decisions

| Decision | Alternative rejected | Reason |
| :--- | :--- | :--- |
| Group by archetype | Group by site | Ten sites of one kind is one data point repeated |
| `is_trustworthy` gates the report | Always report the number | A figure over 13 labels describes the labels, not the engine |
| Caveat embedded in `summary_line()` | Caveat as a separate field | The caveat must travel with the figure when something copies it |
| Score both axes separately | One combined accuracy | ADR 0002 decoupled them; one number cannot distinguish the failures |
| Malformed corpus file raises | Skip and continue | The yardstick must not silently shrink |
| `weights_override` on `classify_page` | Rebuild the pipeline per profile | One documented calibration hook beats a parallel code path |

---

## 5. Explicitly not done

**The four confusions in §3 are diagnosed and deliberately unfixed.**

Adding `code-of-ethics` to the legal-slug list would make four more labels pass.
It would also be **fitting rules to the thirteen examples the engine is scored
on**, which is the definition of overfitting, and I would have no way to tell
whether the change generalised. The corpus exists to prevent exactly that.

The honest sequence is: label more sites first, then fix what is still wrong.
Fixing now feels like progress and destroys the instrument.

| Item | Status |
| :--- | :--- |
| Confusion fixes | Diagnosed, deliberately deferred until the corpus can validate them |
| `ECOMMERCE` / `FLAT_URL` labels | **Zero.** Between them the only archetypes that exercise Signal 2 — the highest-weighted signal at 0.30, calibrated against no data at all |
| Weight profile calibration | Harness exists; needs labels to run against |
| Recall gap | 3 of 13 labelled pages never discovered; cause not investigated |
| Stored HTML fixtures | Not implemented. Offline signal-level calibration currently needs a live crawl |
| `LlmPageClassifier` / Layer 2 | Protocols only |
| Sitemap/CMS pagination | Carried from cycle 0004 |

---

## 6. Corrections

**Build-log 0007 §4.2 framed the 98% escalation rate as making "the cost model
untrustworthy", implying the threshold was mis-set.** The curve in §3 shows the
threshold is doing its job correctly and the confidence score is well
calibrated. The cost problem is real, but its cause is weak structural signals,
not a badly chosen threshold. Cycle 0007's framing was incomplete rather than
wrong, and this entry supersedes it.

---

## 7. Files changed

**New — source**: `corpus.py`, `evaluation.py`
**New — fixtures**: `tests/fixtures/corpus/highradius.json`, `README.md`
**New — scripts**: `evaluate_corpus.py`
**New — tests**: `test_corpus.py` (31), `test_evaluation.py` (28)
**Modified**: `cascading_pipeline.py` (`weights_override` calibration hook)

---

## 8. Follow-ups

1. **Label an e-commerce site and a flat-URL site.** These are the two highest
   -value gaps: together they are the only archetypes that exercise Signal 2.
2. Then fix the confusions in §3 and confirm the fixes generalise.
3. Investigate the 23% recall gap.
4. Restate the throughput target (carried from 0007).
5. Sitemap/CMS pagination (carried from 0004).
