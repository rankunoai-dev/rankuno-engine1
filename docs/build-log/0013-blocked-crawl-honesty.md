# Cycle 0013: A blocked crawl must say it was blocked

- **Date**: 2026-08-10
- **Scope**: Stop a fully refused crawl from reporting success with an invented page.
- **Commit**: uncommitted at time of writing
- **Quality gate**: 891 tests, 95.48% coverage, `mypy --strict` clean

---

## 1. Gate results

```
=== Format ===      PASSED   All checks passed!
=== Lint ===        PASSED   All checks passed!
=== Type check ===  PASSED   Success: no issues found in 39 source files
=== Tests ===       PASSED   891 passed in 16.38s
                             Required test coverage of 85.0% reached. Total coverage: 95.48%
ALL GATES PASSED.
```

Frontend: `npx tsc --noEmit` exit 0. 14 new tests.

---

## 2. The defect

An operator crawled macys.com through the new UI and got a green `SUCCEEDED`
badge, one page, `HOMEPAGE`, **97% confidence**. The site had not been crawled at
all.

Every request was refused:

```
https://www.macys.com/robots.txt  -> 403  ct=text/html
https://www.macys.com/sitemap.xml -> 403  ct=text/html
https://www.macys.com/            -> 403  ct=text/html
```

And the stored job confirmed it:

```
total_urls 1 | from_sitemap 0 | from_dom 1 | from_cms 0
pages_fetched 0 | sitemaps_fetched 0 | truncated False
status succeeded
```

Two mechanisms combined to produce a confident lie:

1. `_crawl_dom` seeds the crawl root as a graph node **before** the first
   request, so the graph is never empty regardless of what the network does.
2. Layer 0 classifies a bare `/` as `HOMEPAGE` at 0.97 from the URL string. That
   inference is correct and needs no data — which is exactly the problem.

So a site behind bot protection was indistinguishable from a successful crawl of
a one-page site. Every other way of misreading this screen already had a banner —
truncation, synthetic data, an exhausted DOM reserve — and this one had nothing.

---

## 3. What landed

### `DiscoveryReport.fetch_failures`

Refusals were previously logged at `debug` and otherwise discarded. They are now
counted on `SiteGraph` and reported. Counting happens in both the serial and
concurrent paths — behavioural equivalence between them is this module's central
claim, and a report that differed would break it.

### `DiscoveryReport.retrieved_nothing`

True when `pages_fetched == 0 and sitemaps_fetched == 0 and from_cms == 0`. Note
what it does **not** test: `total_urls`, which is 1 even for a total blackout.

### `CrawlBlockedError`, raised before classification

`execute()` raises when `retrieved_nothing` is true. Checked *before*
`_classify_all`, deliberately: classifying the seed node is what manufactures the
confident `HOMEPAGE`, so the fix is to never produce it rather than to explain it
afterwards.

`BaseTool.run()` converts it to a non-success `ToolResult`, so `scripts/run_crawl.py`
and the API both inherit the behaviour without either knowing about it.

The message distinguishes two causes that would send an operator to fix different
things: requests *refused* (bot protection, IP block — nothing about the crawl
config will help) versus *no request made at all* (everything filtered pre-fetch —
check the page ceiling and URL rules).

### UI banner

Fires on `pages_fetched == 0` whenever a result exists at all, and names the
refusal count when there is one. This covers the partial case the error cannot:
a crawl that read a sitemap but fetched no page still succeeds, and its
classifications still rest on URL patterns alone.

---

## 4. Bugs found and fixed

### 4.1 Counting 404s would have made the new field worthless

Caught by a test, not by review. The first implementation counted every non-2xx.
Discovery probes `/sitemap_index.xml` **and** `/sitemap.xml` speculatively and
almost every site publishes only one, so a healthy crawl scored
`fetch_failures: 2` — and gep.com, which is entirely fine, would have reported a
failure on every run.

A field that is non-zero for everything cannot distinguish anything. Fixed with
`is_refusal()`: `401`, `403`, `407`, `429` and any `5xx` count; `404` does not,
because "the page is not there" is not "the server declined". This also matches
what was actually asked for — 403/503 refusals.

There is now a test asserting a healthy crawl reports **exactly zero**, which is
the assertion that would have caught this.

### 4.2 A non-HTML 200 was counted as a failure

Same root cause, narrower. A PDF or a feed answered at a URL is not a refusal —
the server responded, the payload just is not a page. Counting those would dilute
the signal with ordinary site content.

---

## 5. Live verification

Both sites, real network, through the running server:

```
=== https://www.macys.com/ ===
status : failed
error  : Crawl failed: all 3 requests to https://www.macys.com/ were refused by the
         target server. The site is blocking automated clients — robots.txt, the
         sitemap and the homepage were all unreachable, so nothing could be
         classified from real data.
result : HTTP 409 (no result blob, as expected for a failed job)

=== https://www.gep.com/ ===
status : partial
error  : None
result : total_urls 300 | pages_fetched 61 | sitemaps_fetched 1 | fetch_failures 0
```

The second line is the one that matters as much as the first: a healthy crawl
reports **zero** failures, so a non-zero count means something real.

---

## 6. Explicitly not done

* **No retry or user-agent negotiation for blocked sites.** macys.com is behind
  Akamai bot protection, which refuses before the request reaches the origin.
  Defeating that would mean impersonating a browser to circumvent an access
  control, and this engine will not do it. The legitimate route for a client site
  is a descriptive `user_agent` — already a field on the crawl form — or an
  allowlist arranged with the site owner.
* **No distinction between "blocked" and "robots.txt disallowed".** Both surface
  as refusals. A site that politely disallows crawling and one that hostilely
  blocks it currently read the same in the report.
* **`retrieved_nothing` does not fire on a partial block.** A site that serves
  its homepage but refuses everything below still reports success, with only the
  banner to indicate the coverage is thin.
* **No test of the UI banner.** `rankuno-ui` still has no test runner; the banner
  is covered by `tsc` and manual verification only.
