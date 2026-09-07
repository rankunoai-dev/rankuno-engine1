# Cycle 0067: A redirect finding has to say where it goes

- **Date**: 2026-09-03
- **Scope**: Render the sitemap-redirect finding through a worklist that shows
  the destination and the hop count, and export those columns.
- **Commit**: uncommitted at time of writing
- **Quality gate**: UI `151 passed` / 14 files. Python gate red on two parallel
  sessions' in-flight work — see §1.

---

## 1. Gate results

```
> npx vitest run
 Test Files  14 passed (14)
      Tests  151 passed (151)

> npx tsc --noEmit   → 13 errors, all in src/components/crawl-results/Gsc*
                       and adapters/factories touched by the GSC session.
                       None in any file this cycle changed.
```

The Python gate is **red**, on work belonging to other sessions running at the
same time:

* `test_gsc_connection.py`, `test_gsc_crawl.py` — root-level scratch scripts,
  `T201 print found` × many. `CLAUDE.md` §4 says scratch scripts are deleted
  before the gate; these are somebody's live debugging files.
* `navigation_context.py` — `SIM102`.
* `tests/test_ui_contract.py` — 4 failures, because the contract exporter cannot
  run. See §4.

Scoped to what this cycle touched:

```
> ruff check src/modules/seo/page_classifier/signal_parsers.py
All checks passed!
```

---

## 2. The finding already existed

The request was to write `sitemapRedirects.ts` against the test file waiting for
it. That turned out to be done: a parallel session had implemented
`sitemapRedirectFindings` **inside `audit.ts`** — not as the separate module the
test filename implies — along with `finalUrlOf` and `sameAddress`. All 8
assertions in `sitemapRedirects.test.ts` pass untouched.

Nothing was rewritten. Building a second implementation to satisfy a test that
already passes would have produced two definitions of one finding.

---

## 3. What was actually missing: the destination

The finding was reaching the screen through the **orphan** worklist, because
`AuditView` dispatched on shape alone — `groups` → `DuplicateTable`, otherwise
`pages` → `OrphanTable`.

`OrphanTable` answers *how was this page discovered?* Its columns are the
discovery-source split and the grouped sitemap filename. For a redirect that is
the wrong question and, worse, the destination is not among its columns. So a
report could say **318 sitemap entries redirect** and not say where a single one
of them went.

The card-level `Download CSV` had the same hole: `url, page_type,
hierarchy_level, gsc_*`. A list of redirecting URLs without the address each one
resolves to is a file nobody can act on.

### 3.1 `Finding.worklist`, not another shape check

Adding a third branch keyed on `finding.id` would have worked and would have
been the wrong shape of fix — the dispatch would then be part shape, part magic
string. `Finding` gained an explicit optional `worklist: "redirects"`, and the
docstring states the rule it encodes: an orphan set is read by *how it was
found*, a redirect set by *where it goes*.

### 3.2 Three columns, and the hop count is one of them

`redirect_chain` was already stored and never shown. A single 301 is ordinary; a
chain is a round trip paid on every crawl, and Google stops following at five —
so hops above one are tagged rather than left as a number to scan for.

### 3.3 Homepage redirects are filterable, not just mentioned

The finding's `detail` already said how many land on the homepage. The table
makes that a filter and a per-row tag, because it is the subset to act on first:
search engines read a redirect to the root as the page being *gone* rather than
*moved*.

The filter is withheld entirely when the count is zero — a control that can only
ever return an empty table reads as a defect.

---

## 4. Bugs found and fixed

**`signal_parsers.py` was missing `from enum import StrEnum`.** A parallel
session's in-flight `Indexability` enum referenced `StrEnum` without importing
it, which made `src.modules.seo.page_classifier` **unimportable**. That took down
the contract exporter and four `test_ui_contract` tests, and would have taken
down the API server on its next restart.

Fixed here because it is one line with no design content, and because it blocked
verifying anything else. Not claimed as this cycle's work: the other 149 lines in
that file are the other session's.

**A second exporter blocker was left alone, deliberately.** With the import
fixed, the exporter now refuses for a different reason:

```
UnmappedTypeError: FullPageIntelligenceProfile.navigation_discovery_method
references 'NavigationDiscoveryMethod', which the exporter does not emit.
```

That is the guard working correctly on a model still being shaped. Registering
the enum would commit a contract for someone else's unfinished work.

---

## 5. Corrections

**Cycle 0051 §7 said "No `.xlsx`. Same as every export in this project."** That
is no longer true — `reconciliation.xlsx` writes a real workbook, one sheet per
reason. It was true when written and is now stale; the audit exports named here
remain CSV.

---

## 6. Explicitly not done

- **Redirects outside the sitemap are not reported.** The finding is scoped to
  sitemap entries by design — a link-discovered page that redirects properly is
  the site working. On the latest gep.com crawl that is 18 reported out of 318
  redirecting pages.
- **`redirect_chain` is not shown as a chain.** The count is a column; the
  intermediate hops are on the profile and nowhere on screen. A two-hop chain is
  flagged without saying what it passes through.
- **No server-side export for this finding.** Client-side like every other audit
  export, for the reason in build-log 0035 §3.4.
- **The finding still lives in `audit.ts`, not `sitemapRedirects.ts`.** The test
  filename implies a module that does not exist. Left as found: moving it is a
  rename across a file another session is editing.
- **No screenshot verification.** The dev server was restarted during this cycle
  after being killed by a `| head` in an earlier invocation; the table is
  verified by test and by the stored-crawl measurement in §7, not by eye.

---

## 7. Verified against stored crawls

```
job 7f38319144  gep.com   7,591 pages   sitemap-redirects=18   to-homepage=0   max hops=2
job 9677817839  prospur.io   39 pages   sitemap-redirects=0
job ceed3a02fb  rankuno.com  83 pages   sitemap-redirects=0
```

The finding fires on 18 of 7,591 pages — 0.24%. That sharpness is the point, and
it matches the docstring's claim of roughly 1 in 300.

---

## 8. Files changed

```
rankuno-ui/src/lib/audit.ts                          Finding.worklist;
                                                     finalUrlOf/redirectHops/
                                                     landsOnHomepage exported
rankuno-ui/src/components/audit/RedirectTable.tsx    new — the worklist
rankuno-ui/src/components/audit/AuditView.tsx        dispatch + redirect CSV
rankuno-ui/src/components/audit/audit.css            .au-redirect-to
rankuno-ui/src/components/audit/RedirectTable.test.tsx  new — 8 tests
src/modules/seo/page_classifier/signal_parsers.py    StrEnum import only (§4)
```

---

## 9. Follow-ups

1. **Register `NavigationDiscoveryMethod`** with the exporter, once that model
   settles (§4).
2. **Delete or ignore the root-level GSC scratch scripts** so the gate can go
   green (§1).
3. **Show the chain, not just its length**, if two-hop redirects prove common on
   a client site.
