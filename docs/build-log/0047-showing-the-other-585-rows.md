# Cycle 0047: Showing the other 585 rows

- **Date**: 2026-08-21
- **Scope**: split `off_site` from `other_subdomain`; group and download every
  export row that reached no page; surface it in the panel.
- **Commit**: uncommitted at time of writing
- **Quality gate**: `1535 passed, 1 warning in 133.59s`, total coverage 95.76%

> Numbered 0047, not 0045. A parallel session landed 0045 and 0046 while this
> was being written, and both were on disk before this entry was committed.
> Numbering is sequential and never reused.

## 1. Gate results

```
PASSED: Format
PASSED: Lint
PASSED: Type check
Required test coverage of 85.0% reached. Total coverage: 95.76%
1535 passed, 1 warning in 133.59s (0:02:13)
PASSED: Tests
 Test Files  11 passed (11)
      Tests  105 passed (105)
PASSED: UI Component Tests
ALL GATES PASSED.
```

## 2. A match rate is a claim, and the panel offered no way to check it

The panel said **41.5%** and stopped. Everything below that number depends on
it, and the reader had nothing to test it against — a rate on its own asks to be
taken on trust, and the correct response to "41.5% of your export matched" is
"which 58.5% did not?".

Three things now answer that:

* `PerformanceSummary.unmatched` — one group per (host, reason), with the URL
  count, clicks and impressions, and a few example addresses. It rides in the
  same response as the rate rather than behind a second request.
* `GET /jobs/{id}/unmatched.csv` — every unresolved row, with its host, reason,
  plain-language meaning and metrics. The group totals ride at the top as
  summary rows, for the same reason they do in the cross-check download.
* The sidecar keeps the rows themselves, not just the grouping. "585 rows
  reached no page" is the headline; the 585 addresses are what an analyst checks
  it against, and re-deriving them would mean asking for the export again.

**Grouped by host, not by reason.** That is the axis the answer lies along: on
the gep.com export the two largest groups were one host each, 558 rows between
them, and no other view puts them side by side.

**The groups partition the gap exactly**, and there is a test asserting it —
`sum(urls) == rows - matched` and `sum(clicks) == unattributed.clicks`. A group
view that does not add up is worse than none, because it invites a reader to
trust it twice.

## 3. `off_site` was doing two jobs

Cycle 0044 recorded this and did not fix it. `smartstaging-auth.gep.com` is not
"off site" — it *is* gep.com, and the word said otherwise. Reported identically
to genuinely unrelated domains, 558 rows of indexed spam disappeared into a
count of ordinary third-party noise.

`MatchFailure.OTHER_SUBDOMAIN` now separates them. Re-run against the real
export:

| host | reason | URLs |
| :--- | :--- | ---: |
| smartstaging-auth.gep.com | `other_subdomain` | 283 |
| leodsaks-us.gep.com | `other_subdomain` | 275 |
| gep.com | `not_crawled` | 16 |
| events.gep.com | `other_subdomain` | 2 |
| idploginqc.gep.com | `other_subdomain` | 2 |

`OTHER_SUBDOMAIN` is still a **failure**, not a match. The engine keeps
subdomains apart deliberately — `blog.example.com` and `shop.example.com` really
are separate properties, and `site_host` has said so since the crawler was
written. Resolving them here would undo that. What changes is only that the
report now says which kind of stranger a row is.

## 4. Design decisions

**`registrable_domain` is a heuristic, and is named as one.** The correct
answer needs the Public Suffix List — a network-fetched dataset with its own
staleness problem — so this takes the last two labels, or three when the
second-to-last is a suffix-like label (`co.uk`, `com.au`, `ac.jp`). It errs
toward calling two hosts *different*, which is the safer mistake: it
under-reports a relationship rather than inventing one. There is a test that
`a.co.uk` and `b.co.uk` are different organisations.

**IPv4 literals are excluded explicitly.** Slicing the last two labels of
`1.2.3.4` produced `3.4`, which would have made every host on a private range
look like one organisation. Caught by trying it rather than by a test.

**Examples are capped at three per group.** Enough to recognise the group
without downloading; the CSV holds the rest.

## 5. Bugs found and fixed

**The `1.2.3.4 → 3.4` case above**, found by running the new function over a
handful of hosts before wiring it in.

**A test asserted the behaviour this cycle deliberately changed.**
`test_a_subdomain_is_off_site_not_missing` had encoded "a subdomain is off-site"
as correct. It is not wrong that a subdomain fails to resolve — that part still
holds and is still asserted — but the name and the reason both needed to change,
and the docstring now says why rather than restating the assertion.

## 6. Explicitly not done

- **The spam subdomains are described, not acted on.** The engine now says
  "283 URLs on smartstaging-auth.gep.com, a subdomain of this site, carrying N
  clicks". It does not crawl them, does not check whether they are live, and
  does not call them a compromise. That judgement needs a person.
- **No finding fires on this.** A large `other_subdomain` group is visible in
  the panel and in the download; it is not an `Opportunity` and does not appear
  in the recommendations list. It belongs there, and the shape of that finding
  is not settled — "a subdomain you did not crawl holds 70% of your clicks" is a
  crawl-scope question as much as an SEO one.
- **GA4 rows are grouped by the same code but carry no clicks**, so a GA4-only
  gap will show URL counts and zeroes. GA4 ingestion does not exist yet, so this
  is untested against anything real.
- **The Public Suffix List**, per §4.

## 7. Files changed

| File | Change |
| :--- | :--- |
| `src/modules/seo/page_classifier/url_rules.py` | `registrable_domain` |
| `src/modules/seo/performance/schemas.py` | `MatchFailure.OTHER_SUBDOMAIN` |
| `src/modules/seo/performance/url_identity.py` | tells a subdomain from a stranger |
| `src/modules/seo/performance/aggregator.py` | `UnmatchedGroup`, `unmatched_groups` |
| `src/api/server.py` | `unmatched` on the summary; `unmatched.csv`; rows in the sidecar |
| `tests/…/test_url_identity.py`, `test_performance_endpoints.py` | 6 new tests |
| `rankuno-ui/…/PerformancePanel.tsx` + test | the gap table, 2 new tests |
| `rankuno-ui/src/adapters/adapterInterface.ts` | `UnmatchedGroup` |

## 8. Follow-ups

1. Make a large `other_subdomain` group a real finding, per §6.
2. Tell the client about the gep.com subdomains — carried from 0044 and still
   the most urgent item in this log.
3. A second real export, to see whether 41.5% is gep.com's property
   configuration or the resolver.
