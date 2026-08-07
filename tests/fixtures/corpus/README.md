# Golden Corpus

Hand-labelled ground truth. This is the yardstick the classification engine is
measured against, and it is currently **far too small to measure anything**.

Read [ADR 0006](../../../docs/adr/0006-weight-profile-seam-and-runtime-site-detection.md)
and [build-log 0007 §4.2](../../../docs/build-log/0007-first-live-run.md) for why
it exists.

---

## Current state

| File | Archetype | Entries | Labels by |
| :--- | :--- | ---: | :--- |
| `highradius.json` | `B2B_SAAS` | 13 | Human, from the audit record |

Every other archetype has **zero** entries. `GoldenCorpus.coverage()` reports the
shortfall, and `AccuracyReport.is_trustworthy` returns `False` while any sampled
archetype is under `MIN_ENTRIES_PER_ARCHETYPE` (50).

**No accuracy figure from this corpus should leave the team yet.** A number
computed over 13 labels describes which pages happened to be labelled, not the
engine.

---

## Why archetypes rather than sites

Rankuno is an agency: every engagement is a site nobody has seen before. What
needs covering is *kinds* of site, not particular ones — ten B2B SaaS sites are
one data point repeated ten times.

| Archetype | Exercises | Have |
| :--- | :--- | :--- |
| `B2B_SAAS` | Grouped sitemaps, ARIA nav, blog and case-study types | 13 |
| `ECOMMERCE` | `/products.json`, SKU variants, faceted filters | — |
| `FLAT_URL` | Pages off root; Signal 2 is the only thing that can resolve hierarchy | — |
| `HEADLESS_SPA` | No content API; ARIA and schema carry everything | — |
| `MULTI_REGION` | Locale folding and the dedup key | — |
| `LARGE_CATALOGUE` | Crawl budget, depth ceiling, DOM reserve | — |

`ECOMMERCE` and `FLAT_URL` are the highest-value gaps. Between them they are the
only archetypes that reach Signal 2 — the **highest-weighted** structural signal
at 0.30 — which is currently calibrated against no data whatsoever.

---

## Adding a site

1. Create `<site-name>.json` here, matching `CorpusSite` in
   `src/modules/seo/page_classifier/corpus.py`.
2. Label URLs by hand. Record **who** labelled them and **from what**.
3. Prefer hard cases. Twenty pages that are obviously blog articles teach the
   engine nothing; five flat URLs whose parent is only knowable from the CMS
   teach it a great deal.

```json
{
  "name": "example-shop",
  "base_url": "https://example.com",
  "archetype": "ECOMMERCE",
  "labelled_by": "Your Name, 2026-08-07",
  "entries": [
    {
      "url": "https://example.com/collections/summer",
      "expected_level": "L1_PRIMARY_NAV_HUB",
      "expected_page_type": "PRODUCT_CATEGORY_HUB",
      "source": "manual review",
      "notes": "Top-level collection, linked from the main nav."
    }
  ]
}
```

### Rules

- **Provenance is mandatory.** A label with no `source` cannot be re-checked
  when someone disputes it, and disputed labels are the normal case.
- **Never machine-generate labels into this directory.** Scoring the engine
  against its own output measures nothing. If a first pass is used as a
  starting point, a human must review every entry and `labelled_by` must say so.
- **Keep sites in separate files.** `load_corpus_dir` merges them, and one file
  per site keeps provenance and review history attributable.
