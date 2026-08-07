# Cycle 0002: Weight-profile seam & classification pipeline

- **Date**: 2026-08-07
- **Scope**: Separate architecture from calibration via a weight-selection seam, then implement Layer 0 URL rules, the five structural signal parsers, and the Layer 0→3 cascade.
- **Commit**: uncommitted at time of writing
- **Quality gate**: 424 tests, 96.59% coverage, `mypy --strict` clean, drift audit clean

---

## 1. Gate results

```
=== Format ===      PASSED   86 files already formatted
=== Lint ===        PASSED   All checks passed
=== Type check ===  PASSED   26 source files, mypy --strict
=== Tests ===       PASSED   424 passed in 1.89s, 96.59% coverage
ALL GATES PASSED.

Drift audit: PASSED — 39 markdown files, all links resolve
```

Per-module coverage for new code:

| Module | Coverage |
| :--- | ---: |
| `signal_parsers.py` | 98% |
| `url_rules.py` | 97% |
| `cascading_pipeline.py` | 91% |
| `weights.py` | 100% |

**Total coverage fell from 96.91% to 96.59%.** Not a regression in test quality —
1,537 statements now versus 1,116, and `cascading_pipeline.py` at 91% is the
lowest new module. The uncovered lines there are the Layer 2 branch, which cannot
be fully exercised without a GPU implementation.

---

## 2. The question that shaped this cycle

The operator asked whether building for specific site archetypes was wise, given
that Rankuno is a services agency rather than a product company serving one
vertical.

The resolution was to separate two things that were being conflated:

- **Architecture must be client-agnostic.** It already was — a grep confirmed
  zero site-specific logic in `src/`; the only two HighRadius references are prose
  in docstrings explaining *why* a rule exists.
- **Calibration cannot be.** `SIGNAL_WEIGHTS` is five numbers taken from a
  specification and fitted against nothing. Numbers fit to no data are guesses
  wearing decimals.

A single global vector is wrong in two directions at once:

| Site type | `CMS_API_ENDPOINT` at 0.30 |
| :--- | :--- |
| Shopify | **Undersells it** — `/products.json` is near-authoritative |
| Headless React | **Dead weight** — the endpoint does not exist |

And being an agency makes generalisation *more* important, not less: every
engagement is a site the engine has never seen, and nobody will state in advance
whether it is Shopify or a headless SPA. So the answer is not "pick archetypes at
design time" but **detect the archetype at runtime and adapt**.

Recorded as [ADR 0006](../adr/0006-weight-profile-seam-and-runtime-site-detection.md).

---

## 3. What landed

### `weights.py` — the seam (100% coverage)

`get_weight_profile(site_profile)` is the single call the consensus engine makes.
It never reasons about CMS families itself, so enabling adaptation later is a
change *here* rather than a rewrite of the pipeline.

Four profiles declared — `default`, `wordpress`, `shopify`, `headless` — each
verified by test to sum to 1.0. A vector that does not sum to 1.0 silently
rescales every confidence score in the system.

**`ADAPTIVE_WEIGHTS_ENABLED = False`.** Every site currently receives the
calibrated `default` vector. This is deliberate and is the most important thing in
the module: only `default` derives from the approved blueprint. The other three
are *reasoned* guesses. Enabling them now would replace one set of unmeasured
numbers with four — which looks like tuning while being guesswork, and is strictly
worse than a single specified baseline.

Two things make the seam more than a claim:

- **A test flips the flag** and asserts Shopify then receives a *different*
  vector. Without that, "we built a seam" is unfalsifiable.
- **`WeightProfileReport` records applied and detected profiles separately**, so a
  reviewer comparing two sites' accuracy can tell a genuine difference from an
  artefact of different weighting.

Profile reasoning, recorded so the numbers are not mysterious later:

| Profile | Shape | Why |
| :--- | :--- | :--- |
| `wordpress` | CMS 0.38, sitemap 0.24 | `/wp-json/wp/v2/pages` states parent IDs outright; sitemaps reliably grouped by post type |
| `shopify` | CMS 0.42, schema 0.20 | `/products.json` is effectively authoritative; Schema.org markup is generated, not hand-written |
| `headless` | CMS **0.0**, ARIA 0.40 | No content API exists, so its weight must redistribute rather than linger as dead weight |

`resolve_profile_name()` lets client-side rendering dominate an *unknown* CMS —
if the content API is unreachable, what generated the markup is moot. But a
**headless WordPress keeps its profile**, because `/wp-json` still answers. That
distinction is tested.

### `url_rules.py` — Layer 0, entirely pre-fetch (97% coverage)

Everything here runs **before a network packet is sent**. One SKU with 20 filter
options generates 2²⁰ ≈ 1,048,576 permutations, and a crawler that discovers this
by fetching them has already lost.

- **Tracking-param stripping** — `utm_*`, `gclid`, `ref`, `qid`, `sr`, `pf_rd_*`
  and 25 more. `ref` and `qid` are the Amazon case specifically: they turn one
  product page into fifty frontier entries.
- **Deterministic param sorting** so order cannot fork one page into several keys.
- **Locale folding** so `/de/software/` and `/software/` share a dedup key.
- **Facet detection** on two independent triggers: more than 5 surviving params,
  or a known facet param.
- **Depth ceiling** at 15 segments.

`url_fast_path()` is deliberately conservative. A wrong answer here is **never
revisited by a later layer**, so it fires only on patterns unambiguous on any
site. There is a test asserting it stays silent on `/software/order-to-cash/`,
`/capsules`, and `/resources/blog/some-post/` — things that merely *look*
classifiable.

One subtlety worth keeping: `/?utm_source=x` is the homepage, but `/?s=widgets`
is a search results page wearing the root path. Tracking params are stripped
*before* the root check; surviving params mean it is not the homepage.

### `signal_parsers.py` — the five structural signals (98% coverage)

Every parser is a **pure function over already-fetched content**. Nothing here
opens a socket — fetching belongs to a connector, which is what keeps
`UrlSafetyPolicy` and `robots` on the single code path that reaches the network,
and what makes these rules exhaustively testable offline.

| Signal | What it reads | Confidence |
| :--- | :--- | ---: |
| `CMS_API_ENDPOINT` | Platform record: parent ID, record type | 0.88–0.95 |
| `ARIA_NAV_TREE` | Nav landmark position and nesting depth | 0.70–0.90 |
| `SCHEMA_JSONLD` | Schema.org `@type`, walking nested `@graph` | 0.80 |
| `SITEMAP_INDEX` | Which grouped sitemap listed the URL | 0.75 |
| `LINK_IN_DEGREE` | Internal in-degree, scaled to crawl size | 0.35–0.72 |

Returning `None` means *"this signal has nothing to say"*, which is materially
different from a low-confidence opinion — an absent signal must not drag the
consensus down. That distinction is enforced by the `SignalParser` type alias and
its docstring.

**The ARIA parser reads the DOM**, so `display: none` is irrelevant. A
hamburger-collapsed mobile menu classifies identically to a desktop one, which is
the entire reason Signal 1 outranks visual scraping. Tested directly with a
`style="display:none"` nav.

**Deliberate omission: `selectolax`.** `TECH_STACK_SPECIFICATION.md` selects it,
and it will be right at crawl scale. It is *not* imported here because it lives in
the optional `seo` extra, CI installs only `[dev]`, and a module-level import
would break the build for a performance benefit that does not exist until a
crawler actually runs. The stdlib `html.parser` sits behind the same signature, so
substituting it later is a change inside one function.

**Link in-degree scales with crawl size.** A fixed 1,000-link threshold is
impossible on a 200-page site and unremarkable on a 50,000-page one, so it would
misfire at both ends. The threshold is `min(1000, max(10, total * 0.5))`.
Near-orphans are also reported weakly — a genuine SEO finding, and weak evidence
of a leaf, since hubs are never orphans.

### `cascading_pipeline.py` — Layers 0→3 (91% coverage)

```
Layer 0  URL rules              ~0.0ms   $0      ~65% of pages
Layer 1  Structural consensus   ~1-3ms   $0      ~25% of pages
Layer 2  Local zero-shot ML     ~15ms    $0      ~8%  of pages
Layer 3  Governed LLM           ~300ms   paid    <2%  of pages
```

`needs_llm_escalation()` exists so callers can determine *before making any call*
which pages will escalate, batch them, and submit once. The 50% Batch API discount
in ADR 0005 depends entirely on this being knowable in advance.

`ConsensusOutcome` extends `SignalScore` rather than duplicating its shape — the
outcome of consensus is structurally the same thing as one signal's opinion, and
two parallel shapes would drift.

---

## 4. Design decisions

### Confidence is normalised against *participating* weight, not 1.0

The most consequential decision in the cycle, and the least obvious.

A page seen only by the sitemap signal (weight 0.20) at 0.75 confidence should
report **0.75**, not 0.15. Dividing by the full weight vector would make almost
every page look uncertain and escalate it to the paid layer — **turning a missing
signal into a bill**. A test pins this specifically.

### Incoherent taxonomy pairs are reconciled, not rejected

Independent signals can vote for a level and type that cannot coexist — a sitemap
saying `BLOG_ARTICLE` while nav depth says `L0_HOMEPAGE`. The profile validator
would reject that outright, **failing a whole crawl over one disagreement**.

`_coerce_valid_pair()` reconciles instead, trusting structural level over page
type — level comes from graph position, type is often inferred from a slug.

### An unclassifiable page returns `UNKNOWN`, it does not raise

A 20,000-page crawl must not die on one page it cannot classify. `UNKNOWN` with
0.0 confidence is a **measurable defect signal**; a crash is lost work.

### Intent and conversion role are derived, not classified separately

A product detail page reporting `INFORMATIONAL` intent would be a contradiction,
not a nuance. Deriving them from the resolved taxonomy keeps them consistent by
construction.

---

## 5. Bugs found and fixed

### Critical: the locale regex silently corrupted real URLs

My first implementation matched **any** two-letter path segment as a language
code:

```python
_LOCALE_RE = re.compile(r"^[a-z]{2}(?:[-_][a-z]{2,4})?$", re.IGNORECASE)
```

`amazon.com/dp/B0001234` therefore had `dp` stripped, producing the dedup key
`/b0001234/`. The same applies to `/ai/`, `/hr/`, `/us/`, `/qa/` — extremely
common content sections on ordinary sites.

This is the worst class of bug in a crawler: **silent, and it corrupts the dedup
key**, which means two genuinely different pages can collapse into one node and
the damage propagates through the entire site graph.

Caught by `test_amazon_style_url_collapses`, which I had written from the
specification's own worked example.

**Fix**: a curated ISO 639-1 list instead of shape matching, plus a
`known_locales` parameter threaded through `strip_locale_prefix`, `normalize_url`
and `depth_of` — so a crawler that has *observed* a site's real locales can remove
the guesswork entirely. `SiteProfile.locale_prefixes` already existed to feed it.

`it` (Italian) and `hr` (Croatian) are **deliberately excluded** from the default
list. Both collide with very common English sections — `/it/` for IT services,
`/hr/` for human resources — and mis-stripping real content is worse than missing
a locale fold. Sites genuinely serving those languages pass `known_locales`.

Regression test covers all seven colliding segments.

### `strip_locale_prefix` had inconsistent trailing-slash behaviour

`/software/` (no locale) returned unchanged with its trailing slash, but
`/de/software/` returned `/software` without one. Fixed to preserve the original
form so it composes predictably with `normalize_path`.

### Two wrong test expectations — the code was right both times

Worth recording, because "the test failed so I changed the code" is the reflex to
avoid:

- **`/a/*/c` vs `/a/c`** (cycle 0001's robots parser, re-checked here). I expected
  a match on grounds that `*` matches empty. It does — but the pattern has literal
  slashes on *both* sides, so `/a/c` would need to be `/a//c`. Expectation
  corrected; a genuine empty-wildcard case (`/a*b` vs `/ab`) added.
- **CMS `page` with a parent and no children.** I expected `L2_SUB_NAV_HUB`; the
  code returned `L3_LEAF_PAGE`. The code is right — having a parent places it
  *beneath* something, but childless means leaf. Expectation corrected, and two
  cases added that genuinely exercise the hub path.

### A self-contradictory assertion I wrote

`assert rate == 0.01` followed by `assert rate < 0.005 * 2`. The second is
`0.01 < 0.01`, which is false. Removed; the first assertion already made the
point.

---

## 6. Corrections

Nothing published in cycle 0001 turned out wrong during this cycle. The ADR 0005
cost table corrected in 0001 §4 remains accurate and is still test-pinned.

One clarification to 0001's ADR 0002 note: the entry said `reasoning` is excluded
from the LLM response schema. That remains true, and `SignalScore.notes` is
`max_length=500` to enforce it structurally — notes are diagnostic metadata, not a
place for prose. Tested.

---

## 7. Explicitly not done

| Item | Status | Consequence |
| :--- | :--- | :--- |
| `SiteProfile` **producer** | Contract exists; **no probe pass writes it** | Every call site passes `None`, so `default` weights apply. Not a bug — adaptation is off anyway |
| Layer 2 `ZeroShotClassifier` | Protocol only | Cascade falls straight through to the **paid** Layer 3. Correct but more expensive; the pipeline reports it rather than hiding it |
| `tool.py` | Not started | No `BaseTool` entry point yet, so this is not invocable through the governed pipeline |
| `tree_visualizer.py` | Not started | — |
| Golden corpus | Not started | **The ≥98% accuracy claim remains unverifiable.** Blocked on Python network access |
| Adaptive weighting | Seam live, selection **off** | Requires the corpus and a follow-up ADR |
| Breadcrumb extraction | `PageEvidence.breadcrumb_path` exists; nothing populates it | Field is always `()` |
| `canonical_url` | Set to `url` | SKU variant clustering needs real `<link rel="canonical">` extraction |

The three non-default weight profiles are **declared structure that nothing
currently reaches**. This will read as dead code to anyone who has not read
ADR 0006 — hence the explicit status note at the top of `weights.py`.

---

## 8. Files changed

**New — source** (4 files, ~1,000 lines):
`src/modules/seo/page_classifier/{weights,url_rules,signal_parsers,cascading_pipeline}.py`

**New — tests** (4 files, 216 tests):
`tests/modules/seo/test_{weights,url_rules,signal_parsers,cascading_pipeline}.py`

**New — docs**: `docs/adr/0006-weight-profile-seam-and-runtime-site-detection.md`,
`docs/build-log/` (this log and its index)

**Modified**: `page_classifier/__init__.py` (22 exports), `CLAUDE.md` (§6 decision
row for ADR 0006), `README.md` (status table), `docs/ARCHITECTURE.md` (module tree,
ADR index, planned list)

---

## 9. Follow-ups

1. **Commit as `feat(seo)`** — uncommitted at time of writing.
2. **`git push -u origin main`** — still pending interactive auth.
3. **Site-profile probe** — the highest-value next piece. Cheap (a handful of
   requests per job) and it activates the `SiteProfile` contract.
4. **Golden corpus, archetype-structured.** Accuracy must be reported **per
   archetype**: a blended 98% that is 100% on B2B SaaS and 70% on e-commerce is a
   broken engine wearing a good score. Source from Rankuno's own past client
   audits, which are automatically representative of the real client mix.
5. **Only after 4**: calibrate the three non-default profiles and enable
   `ADAPTIVE_WEIGHTS_ENABLED`, with an ADR.
6. `tool.py` to bring the pipeline under governed execution (ADR 0003).
