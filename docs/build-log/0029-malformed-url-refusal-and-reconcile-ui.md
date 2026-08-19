# Cycle 0029: Refusing markup artefacts, and a UI for the Screaming Frog gap

- **Date**: 2026-08-19
- **Scope**: Two things. Stop URLs fabricated by broken HTML entering the graph;
  and give the cycle-0028 reconciliation an upload control and a gap panel, so
  the feature is reachable by someone who is not holding a terminal.
- **Commit**: uncommitted at time of writing
- **Quality gate**: `1315 passed, 1 warning in 89.26s` / `Total coverage: 95.29%`

---

## 1. Gate results

```
168 files already formatted
PASSED: Format
All checks passed!
PASSED: Lint
Success: no issues found in 45 source files
PASSED: Type check
Required test coverage of 85.0% reached. Total coverage: 95.29%
1315 passed, 1 warning in 89.26s (0:01:29)
PASSED: Tests
ALL GATES PASSED.
```

Frontend: `tsc --noEmit` exit 0, `vite build` exit 0 (built in 9.97s).

Live server, port 8099 — the endpoint exercised over real HTTP rather than
through `TestClient`, because the browser path is the one that had never run:

```
routes: ['/api/v1/jobs/{job_id}/reconcile/screaming-frog']
status 200
  frog_rows 3   in_both 0   missed_pages 1   orphans 24835   merged 1
  frog_reasons {'MISSED_PAGE': 1, 'CLIENT_ERROR': 1, 'MEDIA_URL': 1}
  new job created: True
empty body -> 400
bad job    -> 404
```

---

## 2. The malformed-URL problem, and the rule that nearly went in wrong

Cycle 0028 noticed `https://kinsta.com/ blog/disk-usage-wordpress/` in a report
and called it a discovery bug. It is. The obvious fix — refuse URLs containing
whitespace — would have been **badly wrong**, and only measuring stopped it.

Across 65 stored crawls and 392,835 URLs:

| Pattern | Count | Verdict |
| :--- | ---: | :--- |
| Whitespace anywhere in the URL | 387 | **mostly legitimate** |
| Path *begins* with whitespace or `%20` | 20 | fabricated |
| Markup remnants in the path (`<`, `>`, `href=`, curly quotes) | 100 | fabricated |

The 387 are real published assets whose filenames contain spaces:

```
infosys.com/.../pdf/Infosys ESG - climate change.pdf
infosys.com/confluence/.../digital%20bank%20in%20a%20bank_icici%20bank.pdf
```

Refusing those would have deleted indexable documents from the audit — the same
mistake cycle 0020 avoided when it kept `.pdf` on the grounds that a whitepaper
is a ranking asset. The discriminator is **position**: no page is served at a
path whose first character is a space, while a filename containing one is
ordinary.

### What the second rule caught

`MARKUP_MARKERS` catches a family the whitespace rule misses entirely — 99
further distinct URLs, none of them pages:

```
gep.com/<nolink>
linear.app/team/%3Cteam%20ID%3E/new
highradius.com/about/news/highradius-launches-livecube/<a href=
kinsta.com/blog/how-to-use-mailchimp/%E2%80%9C>MailChimp</a>%20per%20potenziare%20le%20tue%20…
```

The last is the clearest illustration of the cause: a curly quote where `"`
should have closed an attribute, so the parser swallowed an entire paragraph of
Italian body copy into an address. Two of these are documentation placeholders
the site publishes as if they were links.

Enforced at `SiteGraph.add`, counted as `malformed_skipped`, and kept apart from
`media_skipped` and `traps_skipped` because the three have three different
fixes — a media sitemap, a broken template, and broken HTML.

---

## 3. The reconcile UI

`ReconcilePanel` is a modal launched from a row in the jobs table, not a page. A
reconciliation is *about one crawl*, and a standalone screen would need its own
job picker that could disagree with the row the operator clicked.

The panel reads the file in the browser and POSTs its text; the gap comes back
as counts per reason, in two tables — one per direction — with the enum names
translated. That translation is load-bearing: of the seven frog-side reasons
only `MISSED_PAGE` is a defect, and an untranslated table of enum values reads
as a list of failures when five of its rows are the engine working correctly.

The closing note says the thing the tables cannot: **the two gaps need opposite
fixes.** A page Screaming Frog reached and the engine did not is missing from a
sitemap; a page only the engine found has no internal link pointing at it.

### Optional, still

The button is hidden unless `adapter.reconcileScreamingFrog` exists, so fixtures
never offer it. `MockAdapter` does not implement it and was not made to. Nothing
in the crawl path imports any of it.

---

## 4. Bugs found and fixed

### An 80 MB client-side guard that the server can never enforce

A large export read with `file.text()` becomes a string in the tab. A 200 MB
file crashes the tab, and a crashed tab shows the operator nothing at all — the
server's own refusal is never reached because the request is never sent. The
size check therefore has to be in the browser, and it names the fix ("export
Internal → HTML rather than the full crawl") rather than just refusing.

### antd would have POSTed the file itself

`Upload.Dragger` uploads to its `action` prop by default. There is no endpoint
for it to use — the store owns the request — so without `beforeUpload`
returning `false` it fires a silent network error next to a spinner that never
stops. Caught while wiring, not by a test; there is still no frontend test
runner.

### A docstring was orphaned from its interface

Inserting `ReconciliationSummary` before `export interface CrawlDataAdapter`
placed it between that interface and its own doc comment, silently
re-documenting the new type with the old text. Found by reading the file back
after the edit. Scripted insertion into a commented block needs the comment
treated as part of the anchor.

### Two scripted patches broke the import sort

Both `discovery.py` and `server.py` needed `ruff --fix` afterwards. Recorded
because it is now the third time in three cycles: string-replacement edits into
a sorted import block always cost an `I001`.

---

## 5. Corrections

**Cycle 0028 §8 called the malformed URLs "a real discovery-side bug", which is
right, and implied the fix was to sanitise whitespace, which is wrong.**
Sanitising whitespace generally would have removed 387 legitimate URLs to catch
20 fabricated ones. The entry did not have the measurement; this one does.

**The live-server check found nothing wrong with the code, but did find the
verification itself was nearly worthless.** The first attempt reported `404`
against `127.0.0.1:8000` and looked like a routing bug. It was not: a server
started before this endpoint existed still holds that port, and the new process
had failed to bind with `[Errno 10048]` in a log nobody had read. A green
"server up" line printed anyway, because the readiness probe only checked that
*something* answered. Re-run on port 8099 against a freshly built app, it passes.
Worth stating plainly: **a readiness check that does not verify it is talking to
the process it just started is not a readiness check.**

---

## 6. Explicitly not done

- **Stored results are not re-filtered.** The 119 malformed URLs already in
  `.jobs/` stay there; the refusal is at discovery time. A reparse will not
  remove them either — `reparse_placement` re-places pages, it does not re-admit
  them. Only a fresh crawl is clean.
- **Anchor text published as a URL is not caught.** A third family exists and is
  measured but unfixed: `backlinko.com/Exploding%20Topics`,
  `backlinko.com/25-34%20(36.6%)`, `backlinko.com/Title%20Tag%20Formulas` — prose
  in an `href`, with capitals and spaces but no markup characters and no leading
  space. Distinguishing it from a legitimate `%20` filename needs a rule I could
  not measure to zero false positives, and the Infosys PDFs are exactly what
  would be lost by guessing. Roughly 250 URLs across the corpus.
- **Nothing was clicked.** The panel typechecks and builds, and the endpoint is
  verified over real HTTP, but no browser has rendered the dragger, the gap
  tables, or the "Open merged tree" button. There is still no frontend test
  runner in this repository — `tsc` and `vite build` remain the only automated
  frontend checks and neither mounts a component.
- **No real Screaming Frog export.** Still none in the repository. The reconciler
  was calibrated against one in cycle 0027; the merge and now the UI have never
  seen one.
- **The panel does not list the URLs.** It shows counts per reason. The sample
  lists exist in `ReconciliationReport` but are not returned by the endpoint,
  so an analyst still needs the CLI to see which pages were missed.
- **`MockAdapter` cannot reconcile**, so the whole feature is invisible when the
  engine is not running. That is deliberate — fixtures have no server to POST
  to — but it does mean the UI cannot be demonstrated offline.

---

## 7. Files changed

| File | Change |
| :--- | :--- |
| `src/modules/seo/page_classifier/url_rules.py` | `MARKUP_MARKERS`, `is_malformed_url` |
| `src/modules/seo/page_classifier/discovery.py` | Refusal in `SiteGraph.add`; `malformed_skipped` |
| `scripts/run_crawl.py` | Prints `malformed skipped` |
| `rankuno-ui/src/types/schema.ts` | Regenerated |
| `rankuno-ui/src/components/report/CrawlReport.tsx` | Malformed row |
| `rankuno-ui/src/adapters/adapterInterface.ts` | `ReconciliationSummary`, optional method |
| `rankuno-ui/src/adapters/httpAdapter.ts` | `reconcileScreamingFrog` |
| `rankuno-ui/src/store/useCrawlStore.ts` | Store action; refreshes the job list |
| `rankuno-ui/src/components/jobs/ReconcilePanel.tsx` | New — dragger and gap tables |
| `rankuno-ui/src/components/jobs/CrawlJobsView.tsx` | "Cross-check" button |
| `rankuno-ui/src/components/jobs/jobs.css` | Panel styles |
| `tests/modules/seo/test_url_rules.py` | `TestIsMalformedUrl` — 18 tests |
| `tests/modules/seo/test_discovery.py` | `TestMalformedRefusal` — 6 tests |

## 8. Follow-ups

- Return the sample URL lists from the endpoint so the panel can show *which*
  pages were missed, not just how many.
- Decide whether anchor-text-as-URL is worth a rule. It needs a corpus where the
  legitimate `%20` filenames are labelled, which the golden corpus could hold.
- A frontend test runner. Three cycles have now shipped UI with no automated
  check that a component renders, and two defects in this cycle alone would have
  been caught by mounting the thing once.
