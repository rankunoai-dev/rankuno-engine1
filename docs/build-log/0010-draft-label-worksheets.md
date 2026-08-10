# Cycle 0010: Draft label worksheets & multi-archetype crawls

- **Date**: 2026-08-07
- **Scope**: Produce reviewable label drafts for the two missing archetypes that exercise Signal 2, without corrupting the corpus with machine-generated labels.
- **Commit**: uncommitted at time of writing
- **Quality gate**: 742 tests, 94.95% coverage, `mypy --strict` clean, drift audit clean

---

## 1. Gate results

```
=== Format ===      PASSED
=== Lint ===        PASSED
=== Type check ===  PASSED   38 source files, mypy --strict
=== Tests ===       PASSED   742 passed in 13.42s, 94.95% coverage
ALL GATES PASSED.
```

---

## 2. The constraint this cycle had to work around

Cycle 0009 wrote a rule into `tests/fixtures/corpus/README.md`:

> Never machine-generate labels into this directory. Scoring the engine against
> its own output measures nothing.

The request was for draft label CSVs — which is exactly what that rule forbids,
unless the drafts are prevented from *being* labels. So the distinction is
enforced in code rather than by convention.

A worksheet row carries the engine's suggestion **and** an empty `expected_*`
pair. `load_reviewed_csv` admits a row only when a human has filled both
expected columns *and* set `reviewed`. An unreviewed worksheet can sit in the
repository indefinitely without influencing any measurement, and there is a test
asserting the two shipped worksheets currently admit exactly zero rows.

A row marked `reviewed` with empty expectations is refused too, and counted in
`ReviewStats.marked_but_unusable` — that is the likeliest sloppy review, and
falling back to the suggestion would silently launder a prediction into ground
truth.

---

## 3. What landed

**`corpus_drafts.py`** — worksheet format, writer, and a reader that refuses
unreviewed rows. Rows are ordered **lowest confidence first**: that is where a
reviewer's time is worth most, and burying the hard cases at the bottom of a
120-row file means they never get looked at.

**`scripts/draft_labels.py`** — crawls a site and emits a worksheet.

**Two real worksheets**, from live crawls:

| File | Site | Archetype | Rows | Platform detected |
| :--- | :--- | :--- | ---: | :--- |
| `www.allbirds.com.csv` | Allbirds | `ECOMMERCE` | 120 | `SHOPIFY` ✅ |
| `www.vitaquest.com.csv` | VitaQuest | `FLAT_URL` | 21 | `WORDPRESS` ✅ |

Both detections are correct. This is the **first time Shopify's Path C has run
against real data** — `/products.json` and `/collections.json` returned records
and fed Signal 2.

---

## 4. The finding: confidence tracks CMS coverage almost exactly

Across three real sites now crawled:

| Site | Archetype | Rows | With CMS signal | Confidence ≥ 0.85 |
| :--- | :--- | ---: | ---: | ---: |
| VitaQuest | `FLAT_URL` | 21 | **95%** | **100%** |
| Allbirds | `ECOMMERCE` | 120 | **29%** | **31%** |
| HighRadius | `B2B_SAAS` | 250 | **27%** | ~2% |

The correlation is close to 1:1. Where Signal 2 fires, the engine is confident
and — per cycle 0009's escalation curve, which showed everything above 0.75 is
classified correctly — right. Where it does not, the engine is guessing.

VitaQuest is the cleanest demonstration of the flat-URL thesis in the
blueprints: 21 pages hanging off root with no path depth to read, and the
WordPress parent lookup resolved **every one of them** at 0.95 confidence. The
case legacy crawlers are documented as failing is the case this engine handles
best.

### This identifies the real lever on cost

Allbirds returned only **35 CMS records** for a catalogue far larger than that.
Shopify paginates `/products.json` at 30 by default; the engine reads page one
and stops. That is the pagination gap deferred since cycle 0004, and it is now
quantified rather than theoretical:

> 29% CMS coverage → 31% confident → ~69% escalation.

Cycle 0009 concluded that ADR 0005's cost problem is caused by weak structural
signals rather than a mis-set threshold. This cycle names the specific weakness:
**CMS pagination**. Reading every page of `/products.json` and
`/wp-json/wp/v2/pages` should move Allbirds toward VitaQuest's 95%/100% profile,
and escalation cost falls with it.

That is a far more valuable finding than the worksheets themselves, and it came
from crawling two sites the corpus did not previously cover — which is precisely
the argument for archetype coverage.

---

## 5. Design decisions

| Decision | Alternative rejected | Reason |
| :--- | :--- | :--- |
| Suggestions and expectations in separate columns | Pre-fill expectations | Pre-filled answers get accepted wholesale; an empty column has to be typed into |
| Reviewed-but-empty rows are refused | Fall back to the suggestion | Falling back would launder a prediction into ground truth — the exact failure the gate exists to prevent |
| Hardest-first ordering | Site order | Review time is finite; spend it where the engine is guessing |
| Drafts in a `drafts/` subdirectory | Alongside the corpus | `load_corpus_dir` globs `*.json` at one level, so `.csv` files nested one deeper cannot be picked up by accident. Tested |
| Permissive review flags (`y`/`yes`/`ok`/`done`) | Strict `y` only | The gate should catch *absence* of review, not spelling |

---

## 6. Corrections

Nothing published in cycles 0001–0009 turned out wrong during this cycle.

Cycle 0009 §5 listed "stored HTML fixtures — not implemented, offline
signal-level calibration currently needs a live crawl". Still true; worksheets
are labels, not evidence, so this does not resolve it.

---

## 7. Explicitly not done

| Item | Status |
| :--- | :--- |
| **Reviewing the worksheets** | 141 rows, **0 reviewed**. This needs your domain judgement, not mine — see §8 |
| CMS pagination | **Now the highest-value fix**, quantified in §4, still deferred |
| `HEADLESS_SPA`, `MULTI_REGION`, `LARGE_CATALOGUE` | Still zero labels |
| Confusion fixes from cycle 0009 | Still deliberately deferred until the corpus can validate them |
| Recall gap | 3 of 13 HighRadius labels never discovered; uninvestigated |
| Stored HTML fixtures | Not implemented |

One small defect noticed and not fixed: `https://www.allbirds.com/agents.md` was
crawled and classified. `_NON_PAGE_SUFFIXES` in `discovery_parsers.py` does not
include `.md`, so a markdown file entered the graph as a page. Harmless here,
but it is crawl budget spent on something that can never be classified.

---

## 8. What I need from you

The worksheets are **inert until reviewed**, and reviewing them is a domain
judgement I should not make on your behalf — that is the whole point of the gate.

Start with `www.vitaquest.com.csv`: 21 rows, all high confidence, so it is
mostly confirmation rather than adjudication and will take a few minutes.
`www.allbirds.com.csv` is the valuable one — its first rows are where the engine
scored 0.0 and is guessing outright.

Fill `expected_level` and `expected_page_type`, set `reviewed=y`, and the rows
become corpus entries with no further work.

---

## 9. Files changed

**New — source**: `corpus_drafts.py`
**New — scripts**: `draft_labels.py`
**New — fixtures**: `drafts/www.allbirds.com.csv`, `drafts/www.vitaquest.com.csv`,
`drafts/README.md`
**New — tests**: `test_corpus_drafts.py` (37)

---

## 10. Follow-ups

1. **Review the two worksheets** (§8).
2. **CMS pagination** — §4 makes it the single highest-value change available,
   and it is now backed by numbers from three sites.
3. Then re-run `evaluate_corpus.py` and see whether accuracy and escalation move
   as predicted.
4. `.md` and similar non-page extensions (§7).
5. Remaining archetypes.
