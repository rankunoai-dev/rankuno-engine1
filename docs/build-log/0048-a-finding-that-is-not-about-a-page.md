# Cycle 0048: A finding that is not about a page

- **Date**: 2026-08-21
- **Scope**: `INDEXED_SUBDOMAIN` and `Severity` in the opportunity scorer; the
  panel and CSV that carry them.
- **Commit**: uncommitted at time of writing
- **Quality gate**: `1568 passed, 1 warning in 108.52s`, total coverage 96%

## 1. Gate results

```
PASSED: Format
PASSED: Lint
PASSED: Type check
Total coverage: 96%
1568 passed, 1 warning in 108.52s (0:01:48)
PASSED: Tests
 Test Files  12 passed (12)
      Tests  131 passed (131)
PASSED: UI Component Tests
ALL GATES PASSED.
```

## 2. What landed

Cycle 0047 made the uncrawled-subdomain rows *visible*. This makes them a
**finding**: one per host, ranked by clicks, with an action attached.

Run against the gep.com export, with the unresolved rows carrying the click
weight they really had:

```text
[CRITICAL] smartstaging-auth.gep.com   283 URLs   396,200 clicks   44.2%
[CRITICAL] leodsaks-us.gep.com         275 URLs   357,500 clicks   39.9%
[routine ] events.gep.com                2 URLs        10 clicks
[routine ] idploginqc.gep.com            2 URLs        10 clicks
…9 routine in total
```

Two critical, both spam hosts, above every other finding in the list.

## 3. Design decisions

**Severity exists because `score` cannot express this.** `score` ranks *within*
a kind and is documented as meaningless across kinds — a deliberate refusal, in
0041, to invent an exchange rate between clicks and impressions. That refusal
left no way to say "read this one first", so a finding about indexed spam sorted
by its enum position, below a list of internal-link suggestions. `Severity` has
two levels and no arithmetic: it says only whether a finding is unlike the
others.

**Severity is magnitude, and only magnitude.** The first version made a
suspicious host name sufficient, which marked `idploginqc.gep.com` — two indexed
URLs, no clicks — as critical, above findings worth thousands of clicks. Caught
by running it on the real data rather than by a test. Critical now requires 1%
of the export's clicks **or** 1% of its rows; either, because they fail apart —
a staging copy can hold thousands of indexed URLs and almost no clicks, and a
single spam page can take a great many.

**`CRITICAL_SUBDOMAIN_CLICK_SHARE` is assumed, not measured, and says so.**
Every other threshold in this module was placed against the stored corpus. There
is one real Search Console export in existence here, so this is a judgement. It
is set low because the error is asymmetric: a host nobody meant to publish
taking 1% of a site's traffic is worth an hour, and a false alarm costs a minute.

**The finding reports an observation and refuses a diagnosis.** What is known is
that Google reports traffic on a host this crawl did not cover. Whether that
host is a legitimate property, a staging server that escaped, or something worse
needs somebody with access to the infrastructure. The wording gives both
branches. The engine does not say "you have been hacked", and should not.

**The name test only sharpens wording; it never decides whether to report.**
`_NON_PRODUCTION` matches 5 of gep.com's 11 subdomains, including the largest —
`smartstaging-auth` — and misses `leodsaks-us`, which carries 275 of the 558
URLs. **Firing on the name would have hidden half of the incident.**

**`url` holds a host, not a page.** The one place in this module where that is
true, documented on the enum member. `reference_url` carries the most-clicked
address so the claim can be checked in a browser.

**The badge sits on the group, not the row.** A severity marker repeated down
every row of a table stops being read.

**`severity` is the first column of `opportunities.csv`**, so a critical row is
visible before anybody sorts or widens anything.

## 4. On the second recommendation: an "Include subdomains" toggle

Investigated, **not built**, and the reasoning matters more than the verdict.

*Mechanically it is small.* Crawl scope is enforced in exactly one place —
`discovery_parsers.py:315` — and it already takes a `same_host_only` flag. The
change is to thread a setting through `PageClassificationInput` and widen the
comparison from `site_host` equality to `registrable_domain` equality, which
0047 already built.

*The safety controls are already per-host and would hold.* `HttpFetcher` keys
robots by host (`dict[str, RobotsTxt]`), the rate limiter registry is per host,
and `UrlSafetyPolicy.validate()` runs per fetch — so an internal-only subdomain
resolving to a private address would be refused, correctly, rather than reached.

*What is not answered is scope.* A wildcard-DNS domain generates hosts without
limit; the page budget bounds the crawl but the budget would be spent on
whatever the wildcard invents. A crawl that widens its own host set needs a
bound on the number of hosts and a way to report which it took, and neither
exists.

*And for this case it is the wrong tool anyway.* Crawling
`smartstaging-auth.gep.com` means fetching several hundred adult-content spam
pages onto an operator's workstation and storing them in the job store. The
finding is that the host is indexed; reading it is not required to establish
that, and the correct response is to take the host down rather than to audit it.

The toggle is worth having for `blog.example.com`. It should be its own cycle,
with the host bound designed rather than discovered.

## 4b. The same guard on one endpoint and not the other

Found by clicking the link, which is the only way it could have been found.

`unmatched.csv` returned **200 with a header row and nothing else** for a report
saved before 0047 stored the rows. `matched.csv`, written in the same cycle from
the same reasoning, correctly returned `409` with "upload the export again". The
guard was written once, reasoned about in that cycle's own log — *"an empty file
reads as nothing matched"* — and then applied to one of the two endpoints.

A header-only `unmatched.csv` reads as **"every row matched"**, which is the
exact opposite of what an older report means, and is the more misleading of the
two failures: it agrees with a 100% match rate that never happened.

Both now carry the guard, and the test is parametrised over both so a third
download cannot repeat it.

**It was also invisible until the server restarted.** The route returned FastAPI's
own `{"detail":"Not Found"}` because the running process predated cycles 0047
and 0048 — Python does not reload a running server, and nothing in the product
says which build is answering. That is now twice in this session that stale
process state produced a symptom that looked like a code defect.

## 5. Corrections

None. Cycle 0044's §2 called this "a compromised-host signature" and this cycle
deliberately does **not** encode that judgement in the product — the build log
can say what the engine must not.

## 6. Explicitly not done

- **The toggle**, per §4.
- **No liveness check.** The finding reports what Search Console says is
  indexed. It does not fetch the host to see whether the pages are still there,
  so a cleaned-up subdomain still reports until Google's index catches up. A
  single `HEAD` per host would settle it and is a network call this module has
  never made.
- **No robots.txt check on the named host**, which would say whether it is
  already disallowed — the same objection applies.
- **GA4 subdomains are not reported.** `unmatched_groups` covers GA4 rows, but
  GA4 has no ingestion, so nothing exercises it.
- **The threshold is uncalibrated**, per §3.

## 7. Files changed

| File | Change |
| :--- | :--- |
| `src/modules/seo/performance/opportunity_scorer.py` | `INDEXED_SUBDOMAIN`, `Severity`, `_subdomains`, severity-first ordering |
| `src/api/server.py` | `severity` leads `opportunities.csv`; the stale-report guard on `unmatched.csv` too |
| `tests/modules/seo/test_opportunity_scorer.py` | 6 new tests |
| `rankuno-ui/…/PerformancePanel.tsx` + test | critical badge, kind label; 1 new test |
| `rankuno-ui/src/adapters/adapterInterface.ts` | `severity` |

## 8. Follow-ups

1. **The client still has not been told.** Fifth cycle carrying this item.
2. The subdomain toggle, per §4, with a host bound.
3. An optional `HEAD` per named host, to say whether it is still live.
