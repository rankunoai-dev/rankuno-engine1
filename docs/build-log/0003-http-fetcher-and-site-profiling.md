# Cycle 0003: HTTP fetcher & site profiling

- **Date**: 2026-08-07
- **Scope**: Wire the safety controls to real requests, and give `SiteProfile` a producer.
- **Commit**: uncommitted at time of writing
- **Quality gate**: 475 tests, 95.95% coverage, `mypy --strict` clean, drift audit clean

---

## 1. Gate results

```
=== Format ===      PASSED
=== Lint ===        PASSED   All checks passed
=== Type check ===  PASSED   28 source files, mypy --strict
=== Tests ===       PASSED   475 passed in 10.17s, 95.95% coverage
ALL GATES PASSED.
```

| Module | Coverage |
| :--- | ---: |
| `site_profile.py` | 99% |
| `http_fetcher.py` | 89% |
| `retry.py` | 94% |
| `base_client.py` | 91% |

Total moved 96.59% → 95.95% on 1,841 statements (from 1,537). `http_fetcher.py`
at 89% is the floor; the uncovered lines are the async robots-cache path and
peer-address extraction, neither of which `MockTransport` exercises.

Test time rose from 1.9s to 10.2s. Cause identified: a throttling test that
genuinely waits on a token bucket. Noted rather than fixed — see §7.

---

## 2. Why this cycle

A grep before starting showed the actual state:

- `url_safety.py` and `robots.py` had **zero callers**. Both correct, both
  tested, both enforcing nothing.
- No concrete `BaseAPIClient` subclass existed; `llm_client.py` is abstract.
- `PageEvidence` and `SiteProfile` were contracts **no code produced**. Every
  test constructed them by hand.

So the codebase was well-tested components with a missing middle. Wiring is the
critical path; everything else is downstream of it.

---

## 3. What landed

### `pyproject.toml` — httpx promoted to a core dependency

Pinned `httpx>=0.27.0,<1.0.0`. Upper bound is deliberate: httpx has made
breaking changes across minor versions, and a silent transport change would
surface as a crawl failure rather than an import error.

Removed from the `seo` extra to stop the two bounds drifting apart.

### `src/core/retry.py` — `with_async_retries` / `async_retry_policy`

The async fetch path needed backoff matching the sync path. Two independently
tuned policies would drift, and **the one that drifted would be the one
hammering a client's server**. Built on tenacity's `AsyncRetrying`, so waits use
`asyncio.sleep` and yield to the loop rather than blocking it.

### `src/integrations/http_fetcher.py` — the platform's only outbound fetcher

Where `UrlSafetyPolicy` and `robots` stop being libraries and start being
enforcement. Every request passes, in order: SSRF validation → robots check →
per-host throttling → retry with backoff → peer verification.

**Redirects are followed manually.** `follow_redirects=True` would defeat the
SSRF guard entirely — a public URL that 302s to `http://169.254.169.254/` is
validated once, then transparently followed to the instance metadata service.
Every hop is re-validated and the chain is bounded. Tested on both paths.

**Peer verification, honestly scoped.** `_verify_peer` compares the address
actually connected to against `SafeUrl.resolved_ips` and refuses the response on
mismatch. The module docstring states plainly that this is **detection after
connect, not prevention** — the TCP connection has already been made. It closes
the window in which a rebound address could return data, which is the part that
matters, but it does not prevent the connection attempt. A guard believed to do
more than it does is worse than none.

**Robots bootstrapping.** `/robots.txt` is exempt from the robots check, or the
check could never bootstrap. Fetched once per host and cached — re-fetching per
page would double every crawl, which has a test.

**Unreachable robots means no rules**, per RFC 9309. Failing the crawl instead
would let a single 500 block an entire site.

**Both sync and async paths, genuinely separate.** `fetch()` uses `httpx.Client`;
`afetch()` uses `httpx.AsyncClient`. The sync path never calls `asyncio.run()`.
Calling `fetch()` from inside a running loop raises with a message naming
`afetch()` rather than silently blocking the loop — the safeguard requested at
the start of this cycle, and it has a test.

### `src/modules/seo/page_classifier/site_profile.py` — the probe pass

Gives `SiteProfile` a producer, which activates the weight seam built in cycle
0002. Six requests per crawl job, never per page.

Detection is evidence-based:

| Probe | Establishes |
| :--- | :--- |
| `/wp-json/wp/v2/types` returns parseable JSON | WordPress |
| `/products.json` or `/collections.json` | Shopify + catalogue |
| Hydration root **and** near-empty text | Client-rendered |
| robots.txt `Sitemap:` entries | Locale prefixes |

**Detection parses the body rather than trusting a 200.** A great many sites
answer unknown paths with an HTML error page at status 200, and a soft 404 would
otherwise read as a positive detection. Tested explicitly.

**Client-side rendering needs both conditions**: a recognised hydration root
*and* almost no text after stripping markup. Either alone produces false
positives — plenty of server-rendered React sites keep a `<div id="root">`, and a
genuinely thin page is not a SPA. Script and style bodies are stripped before
measuring, or a shell full of inline JS would look content-rich.

**Locales come from the site's own sitemaps**, not from path shape. This is the
direct remedy for the `/dp/` bug in cycle 0002: the site tells us its locales
instead of us guessing.

---

## 4. Design decisions

| Decision | Alternative rejected | Reason |
| :--- | :--- | :--- |
| Manual redirect following | `follow_redirects=True` | Auto-follow defeats the SSRF guard completely |
| Time requests ourselves | `response.elapsed` | Unavailable under `MockTransport`; depends on httpx internals |
| WordPress checked before Shopify | Either order | WooCommerce answers both; `/wp-json` parent IDs are the stronger signal |
| Probe failures return a 404 result | Propagate the exception | A probe is a question; "no" is a valid answer. One blocked endpoint must not abort a crawl |
| Body ceiling at 5 MB | Unbounded | A 2 GB response would take out a 512 MB worker |

---

## 5. Bugs found and fixed

### `BaseAPIClient.call()` disguised policy refusals as upstream faults

The important find. `call()` wrapped every non-`IntegrationError` exception into
`IntegrationError`, which meant an **SSRF block and a robots exclusion were
reported as upstream service failures**.

That is wrong well beyond the test that surfaced it. `IntegrationError` is in
`TRANSIENT_ERRORS`, so a caller applying the standard retry policy would
**retry a refused SSRF request** — turning a working security control into a
retry loop against an internal address.

Fixed in `base_client.py`: `GuardrailViolationError` and its subclasses
(`UnsafeUrlError`, `RobotsDisallowedError`) now propagate unchanged. A refused
request stays refused.

This is a `core`-layer fix that benefits every future connector, not just the
fetcher.

### `response.elapsed` is unavailable under `MockTransport`

`RuntimeError: '.elapsed' may only be accessed after the response has been read
or closed` — 20 tests failed on it. Replaced with our own `time.perf_counter()`
measurement around the request, which is more robust and does not depend on
httpx internals.

---

## 6. Corrections

**"CI will need a one-line change."** Wrong — I said moving httpx to core
dependencies would require editing `ci.yml`. It does not. `pip install -e
".[dev]"` installs core dependencies *plus* the dev extra, so httpx arrives
automatically. No CI change was needed or made.

**"My shell has no network" (cycle 0001 §5, already partially corrected).**
Further refined this cycle: `pip` also reaches PyPI. The accurate statement is
that **git and pip networking work; Python and PowerShell outbound requests
hang.** This is why the fetcher is tested entirely against `MockTransport` — not
a design preference, an environment constraint that happens to align with good
practice.

---

## 7. Explicitly not done

| Item | Status | Consequence |
| :--- | :--- | :--- |
| `discovery.py` | Not started | **`PageEvidence` still has no producer.** The fetcher returns `FetchResult`; nothing yet assembles that into evidence |
| `tool.py` | Not started | Pipeline is still not invocable through the governed `BaseTool` path |
| HTTP/2 | Disabled (`http2=False`) | Requires the `h2` package. The tech spec calls for HTTP/2 pooling; enabling it is a dependency decision, not an oversight |
| Live-site validation | Not possible here | Every test uses `MockTransport`. **The fetcher has never made a real request.** First live run should be against a site Rankuno owns |
| Layer 2 classifier | Protocol only | Unchanged from cycle 0002 |
| Golden corpus | Not started | Accuracy claim still unverifiable |
| Async robots-cache coverage | Partial | The async path's cache branch is not covered; it mirrors the tested sync path |

**Test suite slowdown, not investigated.** Runtime went 1.9s → 10.2s. The cause
is a crawl-delay throttling test that genuinely waits on a token bucket. It is
correct behaviour under test rather than a performance regression in the code,
but at 8 seconds it is the single slowest thing in the suite and should be made
to use an injected clock rather than real time.

---

## 8. Files changed

**New — source**: `src/integrations/http_fetcher.py`,
`src/modules/seo/page_classifier/site_profile.py`

**New — tests**: `tests/integrations/test_http_fetcher.py` (31),
`tests/modules/seo/test_site_profile.py` (26)

**Modified**: `pyproject.toml` (httpx to core, removed from `seo` extra),
`src/core/retry.py` (+`async_retry_policy`, `with_async_retries`),
`src/integrations/base_client.py` (guardrail passthrough — see §5),
`README.md`, `docs/ARCHITECTURE.md`

---

## 9. Follow-ups

1. **`discovery.py`** — the 3-path merged discovery (sitemap XML, DOM link
   graph, CMS REST API) that finally produces `PageEvidence`. This is the last
   structural gap before an end-to-end crawl.
2. **First live run** against a Rankuno-owned site, to validate the fetcher
   against something other than a mock.
3. **Make the throttling test use an injected clock** — see §7.
4. Decide on HTTP/2: adding `h2` is a small dependency for a real throughput
   gain at crawl scale.
5. Golden corpus, archetype-structured, from Rankuno's own past client audits.
