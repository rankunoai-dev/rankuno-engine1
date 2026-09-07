# Cycle 0068: What a page permits, and what Google did

- **Date**: 2026-09-07
- **Scope**: Label every URL indexable / non-indexable, wire the existing
  `indexability_of` into the crawl, and read it against Search Console without
  inventing a verdict Search Console cannot give.
- **Commit**: uncommitted at time of writing
- **Quality gate**: UI `177 passed` / 17 files, `tsc` clean. Python suite exits
  zero; `ruff` clean on every file this cycle touched. See §1.

---

## 1. Gate results

```
> npx vitest run
 Test Files  17 passed (17)
      Tests  177 passed (177)

> npx tsc --noEmit
 (no output)

> .venv\Scripts\python.exe -m pytest tests/ --no-cov -q
 EXIT=0

> ruff check <the six files this cycle changed>
All checks passed!
```

`tsc` was reported red at 13 errors in cycle 0067. It is now clean: those errors
were all missing types from `schema.ts`, and regenerating the contract (§4)
emitted them. Nothing was fixed by hand.

`ruff check src/ scripts/` still reports **3 errors, none in this cycle's
files** — `navigation_context.py` (SIM102) and `reports.py` (S110, I001), both
untracked work belonging to parallel sessions.

---

## 2. The request could not be answered as asked

The ask was to label every URL indexable or non-indexable **from the GSC
report**. Search Console cannot answer that, and the shape of the whole cycle
follows from why.

`GscApiClient` exposes `list_accessible_properties` and `fetch_analytics`.
Search Analytics returns rows **only for URLs that drew impressions in the
requested window**. That makes it a positive-only instrument:

* present in the export → Google indexed it. Real proof.
* absent → *unexplained*. Indexed but unsearched, outside the date range, past
  the row cap, or reported under a different canonical.

Reading absence as exclusion on the gep.com crawl — 7,591 pages against an
export covering a fraction of them — would declare thousands of pages
non-indexable, and would be wrong in the direction that gets healthy pages
deleted.

The only Google endpoint that states indexing status is the URL Inspection API,
quota **2,000 URLs/day per property**: four days of polling for one gep.com
crawl. Rejected for this cycle as a separate feature with its own queue,
backoff and staleness story (§8).

So `GoogleState` has three members and **none of them is "not indexed"**:
`CONFIRMED`, `NOT_IN_EXPORT`, `NO_GSC_DATA`. It can confirm, and it can decline
to say.

---

## 3. The logic already existed and was called from nowhere

Commit `ad63da4` added `Indexability`, `indexability_of` and
`extract_robots_directives` to `signal_parsers.py` — meta robots, `X-Robots-Tag`,
canonical-away, status, with `UNKNOWN` as a first-class member. Tested, and
**referenced by no production code**. No field on the profile, no call in
`tool.py`.

Meanwhile `reports.py` shipped a `By Indexability` worksheet whose
`_extract_status_code` returns `None` under the comment *"for now, all pages are
assumed indexable"*.

Nothing was rewritten. The gap was the wiring, and three defects sat in it.

---

## 4. Bugs found and fixed

### 4.1 `record_fetch` never saw a failure — the one that mattered

`record_fetch` is the single seam that receives a whole `FetchResult`. Both
crawl paths called it **after** `if not result.ok: return`, so every 404, 403 and
500 bailed first.

The consequence is not a missing column. A dead page would have carried
`status_code=None` → `UNKNOWN` → *"this crawl never fetched the page"*, about a
page the crawl fetched and found dead. That is exactly the conflation the
`Indexability` docstring exists to prevent, arriving through the back door.

Fixed by moving the call above both bails in `discovery.py` and
`async_discovery.py`.

### 4.2 The two crawl paths already disagreed

The async path — the default, `use_async_crawl: true` — called `record_fetch`
below the `is_html` bail as well, while the serial path called it above.
Non-HTML 200s were therefore recorded on one path and dropped on the other,
under a comment asserting the paths were behaviourally equivalent. Pre-existing
and unrelated to this field; it would have made the label depend on which
crawler ran.

### 4.3 A followed redirect reports the destination's 200

The fetcher follows redirects, so `status_code` is the **destination's**. The
`300 <= status < 400` branch in `indexability_of` could therefore almost never
fire, and every one of the 18 sitemap-redirects from cycle 0067 would have been
labelled `INDEXABLE` on markup belonging to a different page.

`indexability_of` gained a `redirected_to` argument and checks the destination
rather than the status. Verified: a fetch landing elsewhere now returns
`NOT_A_PAGE` with *"Redirects to …. That destination is the page, not this
address."*

### 4.4 The exporter blocker from cycle 0067 is gone

Cycle 0067 §4 recorded `UnmappedTypeError: … references 'NavigationDiscoveryMethod'`
and left it alone as another session's unfinished model. That session has since
registered those enums. Adding `Indexability` to `ENUMS` and running the
exporter now succeeds, which is what cleared the 13 `tsc` errors.

---

## 5. Design decisions

### 5.1 Two fields, not one merged label

A single column would have to guess what absence from Search Console means.
Two columns state what each source knows and let the reader see where they
disagree — which is the only place the pair beats either alone:

| Verdict + confirmed by Google | Reading |
| :--- | :--- |
| `NOINDEX` + impressions | Traffic on its way out. Google honours a noindex. |
| `CANONICALISED_AWAY` + impressions | Google overruled the canonical. |
| `NOT_A_PAGE` + impressions | A dead URL still ranking. |

The reverse direction — indexable, no impressions — is deliberately **not** a
finding. It is the ordinary case of content nobody searches for, and Search
Console omits every URL without impressions, so that set is mostly pages that
are fine.

### 5.2 The verdict is computed at fetch time, not stored as inputs

`record_fetch` holds the status, the headers, the body and the canonical
together; nothing downstream does. Holding the headers of 20,000 pages to
re-derive one enum later is memory a crawl that already keeps its whole graph in
RAM cannot spend. Two short fields per node instead.

### 5.3 The enum moved to `schemas.py`

`FullPageIntelligenceProfile` carries it, and `schemas` cannot import from
`signal_parsers`, which imports `schemas`. It also puts `Indexability` where the
other domain-taxonomy enums live, per CLAUDE.md §7 ruling 3.

### 5.4 `UNKNOWN` defaults, and the UI says which kind of unknown

`GET /jobs/{id}/result` returns stored JSON **unvalidated**, so on every existing
crawl this key is absent rather than defaulted — the same shape that blanked the
dashboard when `discovery_sources.sitemap` was read off a crawl that never had
it. `indexabilityOf` tolerates absence, and the audit shows a one-line caveat
distinguishing *"this crawl predates the field"* from *"nothing was fetched"*.
Both are all-grey on screen; only the second is a site problem.

---

## 6. Verified on a live crawl

Existing stored crawls all predate the field, so a fixture-only check would have
proved nothing. Crawled `rankuno.com` fresh, 60 pages:

```
pages=60  fetched=59
INDEXABLE 56 · CANONICALISED_AWAY 2 · NOINDEX 1 · UNKNOWN 1

NOINDEX             /privacy-policy/
                    The page says 'noindex'. Google honours this.
CANONICALISED_AWAY  /job-application/?role=content-editors-and-writers
CANONICALISED_AWAY  /job-application/?role=senior-ppc-analyst
                    Names https://rankuno.com/job-application/ as its canonical …
UNKNOWN             /job-application/
```

Each is independently correct, including the last: the canonical *target* was
discovered but never fetched (59 of 60), so it has said nothing about itself.
Reporting it as `INDEXABLE` would have been an invented fact, and it is the case
a fixture would not have produced.

---

## 7. Explicitly not done

- **No URL Inspection API.** Nothing here reports Google's own index verdict.
  `CONFIRMED` means "drew impressions", which is evidence of indexing and not
  the same claim.
- **`robots.txt`-disallowed URLs are not a distinct state.** A URL the crawler
  was told not to fetch reads as `UNKNOWN` alongside one that simply ran out of
  budget. Those are different facts and a sixth member was not added for it.
- **`reports.py` still assumes every page is indexable.** Its
  `_extract_status_code` TODO is now answerable from the profile, but that file
  is another session's uncommitted work and was left untouched.
- **No indexability column in the audit worklists.** The label reaches the node
  inspector, every audit CSV, and the three new findings. `OrphanTable`,
  `DuplicateTable` and `RedirectTable` keep their existing columns.
- **`gsc_avg_position` is not read.** Only impressions decide `CONFIRMED`.
- **No screenshot verification.** Verified by test and by the live crawl in §6.

---

## 8. Files changed

```
src/modules/seo/page_classifier/schemas.py           Indexability moved here;
                                                     two profile fields
src/modules/seo/page_classifier/signal_parsers.py    redirected_to arg;
                                                     PageEvidence carries verdict
src/modules/seo/page_classifier/discovery.py         node fields; verdict in
                                                     record_fetch; ordering fix
src/modules/seo/page_classifier/async_discovery.py   ordering fix (§4.2)
src/modules/seo/page_classifier/cascading_pipeline.py  evidence -> profile
scripts/export_ui_contract.py                        register Indexability
rankuno-ui/src/types/schema.ts                       regenerated
rankuno-ui/src/lib/indexing.ts                       new — the two axes
rankuno-ui/src/lib/indexing.test.ts                  new — 16 tests
rankuno-ui/src/lib/indexConflicts.test.ts            new — 8 tests
rankuno-ui/src/lib/audit.ts                          three conflict findings
rankuno-ui/src/components/audit/AuditView.tsx        CSV columns + caveat
rankuno-ui/src/components/inspector/NodeInspector.tsx  the per-URL label
rankuno-ui/src/styles/design-system.css              .kv .ix-*
rankuno-ui/src/test/factories.ts                     defaults to UNKNOWN (§9)
```

---

## 9. Corrections

**Cycle 0067 §1 said `tsc` shows 13 errors.** True when written; they are gone,
and not by being fixed — regenerating the contract emitted the types that were
missing.

**Cycle 0067 §4 said the exporter refuses on `NavigationDiscoveryMethod`.** No
longer true; see §4.4.

---

## 10. Follow-ups

1. **URL Inspection API** behind a queue, if a client needs Google's own verdict
   rather than impression evidence (§2).
2. **Point `reports.py` at the profile field** so its `By Indexability` sheet
   stops assuming, once that file lands (§7).
3. **A `BLOCKED_BY_ROBOTS` member**, if disallowed URLs prove common enough that
   folding them into `UNKNOWN` hides a finding.
