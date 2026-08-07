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
