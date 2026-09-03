# Cycle 0056: Indexable is not indexed

- **Date**: 2026-09-02
- **Scope**: `Indexability`, `extract_robots_directives`, `indexability_of` —
  reading what a page says about its own indexing.
- **Commit**: uncommitted at time of writing
- **Quality gate**: `1712 passed` across the suites this cycle touches; see §5.

## 1. The request, and the distinction it turns on

*"Each URL must have information — are these indexed or not — and when that page
got the tag as indexed and when non-indexed."*

Three different things are being asked for, and only one of them is free:

| | Who knows | Cost |
| :--- | :--- | :--- |
| **Indexable** — what the page permits | **We do**, from the crawl | free, and was missing |
| **Indexed** — what Google actually has | Only Google | needs GSC |
| **When it changed** | Nobody, yet | needs repeated observation, stored |

Conflating the first two is the failure this cycle exists to prevent. A page can
be perfectly indexable and absent from Google; a page can carry a cross-domain
canonical and be indexed anyway. Reporting `INDEXABLE` as "indexed" tells a
client their page is live in search on the strength of an HTML tag.

## 2. The engine could not answer even the free one

`<meta name="robots">` and `X-Robots-Tag` were **never read**. The string
`indexab` appeared in `src/` only inside `screaming_frog_reconciler` — read out
of *their* export, never determined here. So the engine could not say whether a
page was even allowed to be indexed.

Everything needed was already in hand: `FetchResult` carries `headers`
(lower-cased) and `body`, and `discovery.py:595` already reads the canonical off
that same response. Nothing looked at the rest of it.

## 3. What landed

`extract_robots_directives(html, headers)` reads **both** sources, because
either alone is a blind spot: an `X-Robots-Tag` is how a noindex is applied to a
PDF or set at a CDN and never appears in the HTML; a meta tag never appears in
the headers. A crawler checking one will confidently call the other indexable.

Three details a simpler reader gets wrong:

* **`content="none"` is shorthand for `noindex, nofollow`.** Grepping for the
  word "noindex" misses every page that uses it.
* **`<meta name="googlebot">` counts as `robots`.** A page addressing Googlebot
  states the rule that will actually apply to it; honouring the broader name and
  ignoring the narrower one gets the answer backwards.
* **`x-robots-tag: googlebot: noindex`** puts the directive after a colon.
  Splitting on commas alone keeps `googlebot: noindex` as one token and matches
  nothing.

`indexability_of(...)` returns a verdict and a plain-language reason. **The
order of its checks is the argument**: a `noindex` on a page that also 404s is
not why the page is missing, and reporting the tag would send somebody to edit
markup on a page that does not exist. Status beats tag; tag beats canonical.

`CANONICALISED_AWAY` is worded as a request rather than a rule — consistent with
what `FullPageIntelligenceProfile.canonical_url` has said since cycle 0039: *a
claim by the site, not a verdict*. Google indexes cross-canonicalled pages
routinely.

`UNKNOWN` exists because absence of a prohibition is not absence of a look. One
gep.com crawl never fetched 1,278 URLs; calling those indexable would invent a
verdict from nothing.

## 4. Explicitly not done

- **It does not reach the page profile.** `FullPageIntelligenceProfile` lives in
  `schemas.py`, which a parallel session has open along with `tool.py` and a new
  `navigation_context.py`. Adding a field there now would collide. The parser is
  pure and standalone; wiring it on is a small change once those are free.
- **Nothing here says whether Google indexed anything.** That needs GSC, and
  there are three routes in ascending order of quality:
  1. **Performance data**, already ingested — impressions above zero mean the
     page is indexed. Free, but only ever positive evidence: no impressions
     could mean not indexed, or indexed and never shown.
  2. **The Page indexing export**, which the operator already has. Its `Table`
     sheet is `URL, Last crawled` — per-URL index status **with a date**. Cycle
     0053 refused that file, correctly, for carrying no metrics; read as an
     index report rather than a performance one it is close to the request.
  3. **The URL Inspection API** — the only authoritative per-URL verdict, and
     rate-limited to roughly 2,000 URLs a day per property, so it cannot cover a
     100,000-page site.
- **No history, and this is the honest part of the answer.** "When did it become
  indexed" cannot be recovered. The engine holds 125 stored crawls and not one
  recorded index status, so **history can only start when recording starts**. It
  also needs a store keyed by site that survives across jobs, and every store
  here is per-job.

## 5. Gate

`ruff` and `mypy --strict` are clean across `src/`, and this cycle's suites
pass. The full run is red for two reasons, neither from this cycle:

* `test_ui_contract.py` (4 failures) — a parallel session added
  `navigation_discovery_method` to the page profile without registering
  `NavigationDiscoveryMethod` with the exporter. The exporter caught it exactly
  as designed and named the fix in its own error message.
* 78 lint errors in `test_gsc_connection.py`, `test_gsc_crawl.py` and
  `navigation_context.py` — that session's root-level scratch scripts and new
  module.

Numbered 0056 because 0055 was taken by that session while this was written.

## 6. Files changed

| File | Change |
| :--- | :--- |
| `signal_parsers.py` | `Indexability`, `extract_robots_directives`, `indexability_of` |
| `tests/modules/seo/test_signal_parsers.py` | 13 new tests |

## 7. Follow-ups

1. Wire the verdict onto the profile once `schemas.py` is free.
2. Read the Page indexing export for index status and `Last crawled` — the
   fastest route to the actual question, and the file already exists.
3. Decide where per-site history lives. Nothing cross-job exists yet.
