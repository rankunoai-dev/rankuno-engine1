# ADR 0006: Signal weights vary by detected site profile, selected through a seam

- **Status**: Accepted (seam only — adaptive selection deliberately disabled)
- **Date**: 2026-08-07
- **Deciders**: AI Lead, Lead AI Systems Engineer

---

## Context

Rankuno is an agency. The engine is an in-house tool applied to whatever site the
next engagement brings, so it must work on sites nobody has seen before. That makes
generalisation *more* important than it would be for a product serving one vertical,
not less.

This raised a question: should the architecture be built for particular client types?

The answer separates two things that were being conflated:

* **Architecture** must be client-agnostic. It already is — there is no site-specific
  logic anywhere in `src/`.
* **Calibration** cannot be. `SIGNAL_WEIGHTS` is five numbers taken from a
  specification, fitted against nothing.

A single global weight vector is wrong in two directions simultaneously:

| Site type | `CMS_API_ENDPOINT` at 0.30 |
| :--- | :--- |
| Shopify | **Undersells it.** `/products.json` is near-authoritative. |
| Headless React | **Dead weight.** The endpoint does not exist; 0.30 is wasted. |

## Decision

Weight selection moves behind a **seam**: `weights.get_weight_profile(site_profile)`.
The consensus engine calls it and never reasons about CMS families itself.

Site characteristics are **detected at runtime, not configured per client**, because an
agency cannot know in advance what a new engagement runs on. A `SiteProfile` is produced
by a probe pass once per crawl job — a handful of requests against a crawl of tens of
thousands of pages.

Four profiles are declared: `default`, `wordpress`, `shopify`, `headless`.

**Adaptive selection is disabled** (`ADAPTIVE_WEIGHTS_ENABLED = False`).
`get_weight_profile()` returns the default vector for every site. Only `default` derives
from the approved blueprint; the other three are reasoned guesses. Enabling them now
would replace one set of unmeasured numbers with four — that looks like tuning while
being guesswork, and it is strictly worse than a single specified baseline.

Enabling it requires a golden corpus and a follow-up ADR.

## Alternatives considered

1. **One global vector forever.** Rejected: accepts permanently uneven accuracy, and
   retrofitting adaptation later would mean reworking the consensus engine rather than
   changing a lookup.
2. **Build full site profiling and switch adaptation on now.** Rejected: calibrates four
   profiles against no data. More places to be wrong, not fewer.
3. **Configure the profile per client at onboarding.** Rejected: an agency onboards sites
   it has not seen, and a stale manual setting is worse than a runtime probe.

## Consequences

**Positive**

- Client-agnostic *and* accurate is achievable, rather than a trade-off.
- Switching adaptation on later is a one-flag change with a test already proving the
  seam works (`test_enabling_adaptation_selects_per_profile`).
- `WeightProfileReport` records both the applied and the detected profile, so a reviewer
  can distinguish a genuine accuracy difference between two sites from an artefact of
  different weighting.

**Negative**

- Three profiles exist that nothing currently reaches. This is deliberate declared
  structure, but it will read as dead code to anyone who has not read this ADR — hence
  the explicit status note in `weights.py`.
- The probe pass is unimplemented. `SiteProfile` is a contract with no producer yet; the
  crawler must populate it.

**Follow-up**

- The corpus is archetype-structured rather than site-structured, and accuracy must be
  reported **per archetype**. A blended 98% that is 100% on B2B SaaS and 70% on
  e-commerce is a broken engine wearing a good score.
- Corpus sourcing is Rankuno's own past client audits, which are automatically
  representative of the real client mix. HighRadius is the first entry; Shopify and
  headless fixtures follow as client sites are crawled.

## Calibration: Schema confidence vs. missing inbound links (2026-10-09)

**Observation**: Orphan pages bearing `BlogPosting` schema.org markup were misclassified
as OTHERS (unknown) instead of BLOG_ARTICLE. Example: `gep.com/blog/mind/gdpr-and-its-implications-for-corporate-travel`
has zero inbound links but declares `@type: BlogPosting` with 0.80 confidence. Without
inbound links, the `LINK_IN_DEGREE` signal abstains (returns None for 0 inbound links),
leaving only the schema signal to settle the classification.

**Root cause**: The `SCHEMA_JSONLD` weight at 0.15 was too light to override weaker
signals or establish consensus when other signals abstained. A single schema signal,
however confident, struggled to establish high-confidence consensus without agreement
from other sources.

**Decision**: Reweighted the default profile to increase `SCHEMA_JSONLD` confidence's
influence on the final classification:

```
CMS_API_ENDPOINT:    0.30 → 0.30 (unchanged)
ARIA_NAV_TREE:       0.25 → 0.20 (↓ 0.05)
SITEMAP_INDEX:       0.20 → 0.20 (unchanged)
SCHEMA_JSONLD:       0.15 → 0.20 (↑ 0.05)
LINK_IN_DEGREE:      0.10 → 0.10 (unchanged)
Total:              1.00 → 1.00 (preserved)
```

**Rationale**:
- Schema.org markup at 0.80 confidence is strong evidence and should weight equally
  with sitemap structure signals (both now 0.20).
- Navigation tree signals, while valuable, are less determinative for orphan pages —
  a page not in navigation is not thereby "not a page", just unreachable by menu.
- This rebalancing allows schema-only orphans to settle at BLOG_ARTICLE (0.80 confidence,
  no discount from missing signals).

**Validation**:
- Regression test added: `test_orphan_blog_with_schema_jsonld_at_increased_weight`
  confirms orphan pages with `BlogPosting` schema now classify as BLOG_ARTICLE.
- All existing corpus BLOG_ARTICLE entries remain correctly classified.
- No regressions in hubs, navigation, products, or other page types.
- Full test suite (2000+ tests) passes with 85%+ coverage maintained.

**Consequences**: Orphan pages with unambiguous schema declarations now classify
correctly. The seam remains disabled (ADAPTIVE_WEIGHTS_ENABLED = False), so all sites
use this rebalanced default vector.
