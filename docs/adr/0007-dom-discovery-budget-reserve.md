# ADR 0007: Reserve part of the crawl budget for DOM-only discoveries

- **Status**: Accepted
- **Date**: 2026-08-07
- **Deciders**: AI Lead, Lead AI Systems Engineer

---

## Context

The first live crawl (`docs/build-log/0007-first-live-run.md`) reported
**`dom_only: 0`** on every run against `highradius.com` — the DOM link crawl
contributed no URLs that the sitemaps had missed.

That is the headline capability of 3-path discovery. `HIGHRADIUS_CRAWL_AUDIT_RECORD.md`
§4 exists specifically to document pages absent from every sitemap:
`/anti-corruption-and-bribery-policy/`, `/code-of-ethics/`,
`/human-rights-policy/`, `/glossary/`, `/finsider/`.

The cause was budget allocation, not a defect in Path B. Discovery runs
Path A (sitemaps) → Path C (CMS) → Path B (DOM). HighRadius publishes ~3,145
sitemap URLs, so on a 250-page crawl Path A filled every slot before Path B
started. `SiteGraph.add()` then correctly refused every new URL the DOM crawl
found, and a sitemap-omitted page could never be recorded.

This fails **precisely on the sites where the capability matters most**: the
larger a site's sitemap, the more certain it is that Path B contributes nothing.
Small fixture sites never exposed it, which is why 638 passing tests did not.

## Decision

Reserve a fraction of `max_pages` that **only the DOM crawl may fill**.

- `DEFAULT_DOM_RESERVE_FRACTION = 0.2`.
- Sitemap and CMS discovery stop at `pre_crawl_budget = max_pages - reserve`.
- DOM discovery may use the full `max_pages`.
- The hard ceiling is unchanged: the reserve **redistributes** the budget, it
  never enlarges it.

Configurable per job via `PageClassificationInput.dom_reserve_fraction`, bounded
to `[0.0, 0.9]`. `0.0` restores the starved behaviour and is retained only so the
regression can be pinned by test.

`DiscoveryReport` gains `dom_reserve` and `dom_reserve_used`. When those are
equal the reserve was exhausted, which means it is too small for that site and
sitemap-omitted pages are still being dropped — a condition an operator can now
see rather than infer.

## Alternatives considered

1. **Run Path B before Path A.** Inverts the starvation rather than removing it:
   a link-rich site would then starve out sitemap-only pages, losing orphan
   detection — which is the other finding the audit record cares about.
2. **Separate hard budgets per path.** Most explicit, but adds three parameters
   where one suffices, and forces an operator to predict the shape of a site
   they have not crawled yet.
3. **Raise `max_pages` instead.** Does not solve it. Any budget below the
   sitemap size reproduces the problem exactly, and HighRadius alone is 3,145.
4. **Interleave the paths round-robin.** Fairest in principle, but it entangles
   three independent discovery mechanisms into one scheduler for a benefit the
   simple reserve already delivers.

## Consequences

**Positive**

- Sitemap-omitted pages are reachable at any budget, which is what 3-path
  discovery was built to do.
- The reserved slots are the highest-value ones in the crawl: a URL no sitemap
  lists is exactly what an audit is looking for.
- Exhaustion is observable via `dom_reserve_used`, so an operator can raise the
  fraction on a site that needs it instead of guessing.

**Negative**

- At a fixed budget, **20% fewer sitemap URLs are captured**. On a site whose
  sitemap is complete and accurate, that is a pure loss — the reserve is
  insurance against a condition that site does not have.
- The default is unmeasured. 0.2 is a judgement call, not a fitted value. What
  fraction actually recovers the missing pages on a real site is a question the
  golden corpus should answer, and this ADR should be revisited then.
- `dom_only` is still bounded by the reserve. A site where the sitemap omits
  more than 20% of its pages will still drop some.

**Follow-up**

- Measure the right fraction once the corpus exists.
- Consider making the reserve adaptive: if `dom_reserve_used` hits the cap,
  a second pass could grow it.
