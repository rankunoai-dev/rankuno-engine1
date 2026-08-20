# Cycle 0032: Resume was a full re-crawl with extra steps

- **Date**: 2026-08-20
- **Scope**: Make "Resume" continue an interrupted crawl instead of restarting
  it. Reported from a live gep.com run.
- **Commit**: uncommitted at time of writing
- **Quality gate**: `1354 passed` Python / `23 passed` UI / `Total coverage: 95.47%`

---

## 1. Gate results

```
PASSED: Format
All checks passed!
PASSED: Lint
PASSED: Type check
Required test coverage of 85.0% reached. Total coverage: 95.47%
1354 passed, 1 warning in 4072.01s (1:07:52)
PASSED: Tests
 Test Files  4 passed (4)
      Tests  23 passed (23)
PASSED: UI Component Tests
ALL GATES PASSED.
```

The 68-minute test run is not a regression. A 5,000-page crawl was running on
the same workstation throughout and the suite normally takes ~100 seconds. It is
recorded verbatim rather than re-run on a quiet machine, because the pasted
figure has to be the one that was actually produced.

---

## 2. The bug

An operator resumed an interrupted gep.com crawl. The new job was labelled
`(resumed +2,940)` — correct, 2,940 URLs were outstanding — and then reported
`299 / 5,311` and climbing from zero. It was crawling the whole site again.

`seed_urls` **adds to the frontier. It removes nothing from it.** Both crawl
paths open with:

```python
graph.add(base_url, dom_link=True, depth=0)
frontier = deque([(base_url, 0)])
```

so a resumed crawl fetched the homepage, followed every link out of it, and
walked the entire site. The seeds were appended to a full re-crawl. Worse, both
docstrings claimed otherwise — "without this the resumed run would rediscover
the same pages in the same order" — which is exactly what it did anyway.

Measured on the operator's own checkpoint:

| | |
| :--- | ---: |
| discovered | 7,761 |
| unfetched (seeded) | 1,147 |
| **already fetched, re-fetched anyway** | **6,614** |

A resume cost 6,614 redundant requests against somebody else's server, and took
roughly as long as the original crawl.

---

## 3. The fix

`PageClassificationInput.exclude_urls` — URLs a previous run already fetched,
never requested again. `resume_job` derives it from the checkpoint:
everything discovered, minus what was still outstanding.

Three decisions:

* **Applied at the fetch, not at the graph.** An excluded URL is still a node
  and still a valid link target, so in-degrees and orphan flags stay meaningful.
  Removing them would make every page that links to them look like it links
  nowhere — and orphan detection is a headline finding in these reports.
* **No special case for the homepage.** The root is nearly always among the
  already-fetched, so it lands in the exclusion like anything else. Skipping its
  fetch means no links are extracted from it, and the traversal simply has
  nowhere to restart from. The bug closes as a consequence of the general rule
  rather than a guard aimed at it.
* **Matched on `normalize_url`.** The same key discovery deduplicates on. A raw
  string comparison misses on a trailing slash and re-fetches the page the
  exclusion exists to skip — silently, once per resumed crawl. There is a test.

Both crawl paths carry it. They are documented as behaviourally
indistinguishable, and an exclusion honoured only by the serial path would make
a resume depend on `use_async_crawl` — which defaults to the async one.

---

## 4. Bugs found and fixed

### The docstrings described the intended behaviour, not the actual behaviour

Three of them — on `seed_urls`, `_crawl_dom` and `_crawl_dom_async` — asserted
that seeding prevented a restart from the homepage. Each was written alongside
code that does not do that. Anyone reading the module to check whether resume
worked would have been told it did.

Corrected in place, and `seed_urls` now says plainly that seeding alone is not a
resume.

### An old checkpoint cannot say what was fetched

Checkpoints written before `urls` existed carry `unfetched` alone, so the
difference cannot be computed. Refusing would throw away real work; resuming
without an exclusion degrades to the old full re-crawl. It resumes, with an
empty exclusion, and logs `resume_without_exclusion` — a silent degradation back
into the bug being fixed is the one outcome not acceptable here.

---

## 5. Corrections

**Build-log 0024 introduced resume and described it as crawling "the URLs an
interrupted job discovered but never fetched". It did not.** It crawled those
URLs *and the entire site*. The entry, the endpoint docstring and both crawl-path
comments all stated the intended behaviour as though it were the implemented one,
and none of the tests written at the time distinguished them: they asserted that
seeds reached the frontier, which was true, and never that anything was left out
of it.

The general lesson is the one this log exists for: **a test that confirms the
mechanism was invoked is not a test that the feature works.** `seed_urls` was
plumbed correctly end to end and the feature was still absent.

---

## 6. Explicitly not done

- **The running crawl was not interrupted, so nothing here is verified live.**
  The operator's gep.com job was mid-run and the API server was deliberately not
  restarted. **The fix is inert until the server is restarted** — the running
  process holds the old code. Unit tests cover both crawl paths and the
  endpoint; a real interrupted-then-resumed crawl has not been observed.
- **The progress denominator still counts the whole site.** A resumed crawl
  re-runs sitemap and CMS discovery, so it will report something like
  `1,147 / 7,761` — it now *fetches* only the 1,147, but the bar is drawn
  against everything discovered. Honest but unhelpful, and not touched here
  because it means changing what telemetry reports rather than what the crawl
  does.
- **Resume still produces a separate job, not a merge.** Unchanged from 0024 and
  still correct: in-degree and orphan flags are properties of the whole graph,
  and a checkpoint holds URLs only.
- **Sitemap and CMS discovery are still re-run on a resume.** They are cheap
  relative to a full page crawl and they establish the denominator, but they are
  redundant work.
- **No cap on the exclusion set.** A 500,000-URL resume builds a 500,000-entry
  set of normalised strings. Same order as the checkpoint already in memory, so
  it changes nothing about the ceiling, but it is not free.

---

## 7. Files changed

| File | Change |
| :--- | :--- |
| `src/modules/seo/page_classifier/tool.py` | `exclude_urls` on the input; passed to both paths |
| `src/modules/seo/page_classifier/discovery.py` | Exclusion honoured in `_crawl_dom` |
| `src/modules/seo/page_classifier/async_discovery.py` | Same, in the level crawler |
| `src/api/server.py` | `resume_job` derives the exclusion from the checkpoint |
| `rankuno-ui/src/types/schema.ts` | Regenerated |
| `rankuno-ui/src/adapters/adapterInterface.ts` | `exclude_urls: []` on the default request |
| `tests/modules/seo/test_discovery.py` | `TestExcludeUrls` — 6 tests |
| `tests/modules/seo/test_async_discovery.py` | `TestExcludeUrlsMatchesTheSerialPath` — 4 tests |
| `tests/api/test_server.py` | Two resume tests |

## 8. Follow-ups

- Report the resumed-crawl denominator honestly: `discovered - excluded` is what
  the run will actually fetch.
- Skip sitemap and CMS re-discovery on a resume, or reuse the checkpoint's
  discovered set instead of re-fetching it.
- Once the operator restarts the server, resume an interrupted crawl for real
  and confirm the fetch count matches the seed count.
