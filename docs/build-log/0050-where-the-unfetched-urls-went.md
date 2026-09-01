# Cycle 0050: Where the unfetched URLs went

- **Date**: 2026-09-01
- **Scope**: a per-outcome fetch ledger on `SiteGraph` and `DiscoveryReport`;
  a progress tooltip that stops saying something untrue.
- **Commit**: uncommitted at time of writing
- **Quality gate**: `1572 passed, 1 warning in 91.46s`

## 1. Gate results

```
PASSED: Format
PASSED: Lint
PASSED: Type check
1572 passed, 1 warning in 91.46s (0:01:31)
PASSED: Tests
 Test Files  12 passed (12)
      Tests  131 passed (131)
PASSED: UI Component Tests
```

## 2. The question that started it

A finished gep.com crawl showed `7,015 / 8,293` beside the word "done", and it
read as though the crawl had stopped halfway. It had not: `truncated: False`,
`stopped_reason: None`, `max_pages: null`, all 8,293 URLs classified and in the
result.

The gap is URLs that were tried and did not come back. The discovery report
accounted for some of them:

```text
total_urls        8293
pages_fetched     7015
fetch_failures     833
traps_skipped        2
malformed_skipped    1
```

**7,015 + 833 + 3 = 7,851.** The other **442 were recorded nowhere at all.**

## 3. Why 442 URLs could vanish

`is_refusal` decides what counts as a failure, and it excludes `404`
deliberately — with a good reason, written down at the time:

> Discovery probes `/sitemap_index.xml` and `/sitemap.xml` speculatively and
> most sites publish only one, so treating `404` as a failure would mark nearly
> every healthy crawl as partly failed.

That reasoning is right *for the sitemap probes* and wrong everywhere else. A
`404` on a URL something **links to** is a broken internal link — a finding, not
noise — and it was being fetched, discarded, and counted by nothing. The same
held for a `200` carrying a non-HTML payload: the server answered, the code
returned `None`, and no counter moved.

The two questions had been collapsed into one predicate. `is_refusal` answers
*"should the server be blamed?"*. Nothing answered *"what happened?"*.

## 4. What landed

`outcome_for(status_code)` names what happened, beside `is_refusal` which still
decides blame. `SiteGraph.record_outcome` is the single write point, and
`DiscoveryReport.fetch_outcomes` publishes the tally:

```text
ok · not_found · refused · server_error · other_status · not_html · transport_error
```

**One write point, deliberately.** The two crawl paths increment
`fetch_failures` in six places between them. A ledger filled the same way would
drift the first time one path grew a branch the other lacked — and behavioural
equivalence between the serial and async paths is `async_discovery`'s central
claim.

Verified on a live gep.com crawl through the running API:

```text
fetch_failures: 10        (the old single number)
fetch_outcomes:
   ok                114
   transport_error    10
   not_found           1
```

The `404` was invisible before this. On a 600-URL sample it is one page; on the
full 8,293-URL crawl it is most of 442.

## 5. The tooltip was stating a falsehood

The progress figure carried this explanation:

> "Pages fetched against URLs discovered. **Sitemap URLs count toward the total
> but are never fetched**, so a sitemap-heavy crawl completes below 100%."

Sitemap URLs *are* fetched. The sentence sent a reader looking for a cause that
does not exist, and explained none of the 1,278 URLs actually missing. It now
says what the gap really is — 404s, refusals, timeouts, non-HTML replies — and
differs while running from when finished, because "the total keeps growing" and
"the total is final" are different facts.

The bar itself was already correct: it is forced to 100% on a finished crawl.
The number beside it was doing the misleading.

## 6. Bugs found and fixed

**The contract exporter had no mapping for `Mapping[str, int]`** and raised
`UnmappedTypeError` — which is the exporter working: it refuses to emit `any`
rather than silently weakening the contract. `dict` was mapped and `Mapping`
was not, though TypeScript cannot tell them apart. Both now render
`Record<K, V>`.

**A test fixture omitted `content-type`**, so a mock `200` was read as non-HTML,
the crawl followed no links, and the ledger recorded `not_html` where the test
expected `ok`. The fixture was wrong, not the code — but it is worth recording
that a response without a content type is *correctly* treated as not-a-page.

## 7. Explicitly not done

- **Pagination.** 1,681 of the 8,293 URLs on that crawl — **20.3%** — are
  `?page=N`, with 327 pages on `/knowledge-bank/procurement` alone. The fix
  belongs in `url_rules.is_faceted_filter`, and a parallel session has that file
  open with build-log 0049 in progress. Deferred on purpose rather than merged
  into a contested file.
- **The 833 failures are broken down but not surfaced.** `fetch_outcomes`
  reaches the UI contract; no component reads it yet. `AuditView` and
  `DashboardShell` are the natural homes and both are open in the other
  session's tree.
- **No per-URL list.** The ledger counts outcomes; it does not say *which* URLs
  404ed. That is the form a broken-internal-link finding would need, and it is a
  bigger change — the page contract would have to carry a status.
- **The 442 are explained but not re-measured.** The reasoning is confirmed on a
  fresh crawl; the original 8,293-URL run predates the ledger and cannot be
  re-read without crawling gep.com again.

## 8. Files changed

| File | Change |
| :--- | :--- |
| `discovery.py` | `outcome_for`, `OUTCOME_*`, `OUTCOME_MEANINGS`, `record_outcome`, `fetch_outcomes` on the report |
| `async_discovery.py` | both fetch paths record outcomes |
| `scripts/export_ui_contract.py` | `Mapping` renders as `Record` |
| `rankuno-ui/src/types/schema.ts` | regenerated |
| `rankuno-ui/src/test/factories.ts` | new field |
| `CrawlJobsView.tsx` | the tooltip says something true |
| `tests/modules/seo/test_discovery.py` | 2 new tests |

## 9. Follow-ups

1. Pagination, once `url_rules.py` is free.
2. Surface `fetch_outcomes` in the crawl view — 10% of a client site failing to
   fetch is a finding, and it is still only visible in JSON.
3. A broken-internal-link finding, which needs per-URL status on the profile.
