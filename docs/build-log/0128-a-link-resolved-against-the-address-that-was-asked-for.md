# Cycle 0128: A link resolved against the address that was asked for

- **Date**: 2026-09-30
- **Scope**: Relative links on a fetched page are resolved against the URL the fetch landed on
  after redirects, and against the page's first usable `<base href>`, instead of against the URL
  that was requested
- **Commit**: `0dc21bf`, integrated on branch `provenance-integration` and pushed to `origin/main`
  as `5c0d149`
- **ADR**: none. The fix makes link resolution follow the HTML standard; it does not change a
  project ruling.
- **Quality gate**: GREEN on the combined tree of cycles 0127, 0128 and 0129. `pytest --cov=src`
  exit code 0, "Required test coverage of 85.0% reached. Total coverage: 92.90%". No pass count
  printed; see §1.

## 0. Background

Found during the URL-provenance investigation ([0127](0127-a-reason-the-crawl-never-recorded.md)).
A `dom_link` flag is only evidence if the link it records exists. This bug made the crawl record
links that no page contains, so it was fixed as its own cycle, as the user asked.

## 1. Gate results

Shared with 0127 and 0129: one run, by the lead, on the combined tree after all three branches
merged into `provenance-integration` with no conflicts.

```
ruff format --check .                    -> 550 files already formatted
ruff check .                             -> All checks passed!
mypy src                                 -> Success: no issues found in 152 source files
scripts/export_ui_contract.py --check    -> UI contract is up to date.
scripts/drift_check.py                   -> PASSED: no drift detected across 215 markdown files.
pytest --cov=src                         -> exit code 0
                                            Required test coverage of 85.0% reached. Total coverage: 92.90%
```

The pytest pass-count summary line did not print (same buffering artifact as build-log 0098 §1 and
0100 §1). No test count is claimed.

```
tsc --noEmit                             -> exit 0
vitest                                   -> Test Files  47 passed (47)
                                            Tests  605 passed (605)
npm run build                            -> ✓ built in 8.07s
```

Fail-then-pass, run by the lead: the four new tests failed on the pre-fix code, including the
off-site `<base>` safety test, and all pass on the fix. The scribe did not re-run them.

## 2. What landed

`discovery_parsers.extract_page_links(html, base_url, *, same_host_only=True, document_url="")`
gained `document_url`, the URL the fetch finally landed on. `_AnchorCollector` records the first
`<base>` element that carries an `href`, as a browser does. `_resolution_base()` picks the URL
relative links resolve against:

1. the `<base href>`, itself resolved against the landed URL, if it parses, is `http` or `https`,
   and names the same site;
2. otherwise the landed URL.

A `<base>` that fails any of those checks is ignored and logged at debug level
(`base_href_ignored`). The same-site filter is still applied to every resulting link, anchored to
the requested URL.

`SiteGraph.landed_url(url)` returns the final URL recorded for a fetched node. Both call sites pass
it: `discovery.py` (`extract_page_links(result, url, document_url=graph.landed_url(url))`) and
`async_discovery.py` (the same call on `html`).

## 3. Design decisions

- **Links are still credited to the requested node.** The graph edge runs from the node that was
  fetched, not from the redirect target.
- **The redirect target is not added as a node.** Doing so would change page counts and duplicate
  handling, which is out of scope for a resolution fix.
- **An off-site or non-http(s) `<base>` is ignored, not obeyed.** Page markup is third-party input.
  Obeying it would let a page aim the crawl's relative links at another host before the same-site
  filter ran. The filter would still drop them, but resolution should not depend on that.
- **First `<base>` only**, matching browser behaviour.

## 4. Bugs found and fixed

| Bug | Where | Effect |
| :--- | :--- | :--- |
| Relative links resolved against the requested URL, not the landed URL | `async_discovery.py` (~L831), `discovery.py` (~L1278), both into `discovery_parsers.urljoin` | Probe: `/old/` 301 → `/new/sub/` containing `<a href="child">` recorded the fabricated `https://e.com/old/child` as a `dom_link`, and it was fetched |
| `<base href>` ignored | `discovery_parsers.py` | Pages that set a base resolved every relative link against the wrong directory |

Both produce `dom_link` flags for URLs no page links to, which makes 0127's
`LINKED_NOT_IN_EXPORT` reason wrong for them. A fabricated URL usually 404s, so on stored crawls it
more likely shows up as a 4xx gap than as an orphan.

## 5. Corrections

- **`dom_link` flags in crawls made before `0dc21bf`** on sites with cross-directory redirects or
  `<base href>` may include URLs that no page links to. Build-log 0004 scoped Path B as the "DOM
  link graph"; since that cycle the graph could contain edges to URLs no page links to. Stored
  results are not rewritten.
- **0127 §3.1's measured split** (47.6% of saved orphans had `dom_link`) was taken from crawls made
  before this fix, so some unknown fraction of that 47.6% may rest on fabricated links. The split
  was not re-measured.

## 6. Explicitly not done

Handed off, not fixed:

- **Breadcrumbs** are still resolved against the requested URL (`discovery.py` ~L818).
- **`rel=canonical`** resolution ignores `<base href>`.
- **Sitemap and nav-tree parsers** ignore `<base>`. Low impact: sitemap `<loc>` values are
  absolute by specification, and header navigation links are usually root-relative.
- **No re-measurement** of existing crawls or of the 0127 orphan split.
- **No change to how redirects are recorded** in the graph (§3).

## 7. Files changed

```
 src/modules/seo/page_classifier/async_discovery.py   |   2 +-
 src/modules/seo/page_classifier/discovery.py         |  13 ++-
 src/modules/seo/page_classifier/discovery_parsers.py |  53 +++++++++--
 tests/modules/seo/test_async_discovery.py            | 100 +++++++++++++++++++++
 tests/modules/seo/test_discovery_parsers.py          |  54 +++++++++++
 5 files changed, 215 insertions(+), 7 deletions(-)
```

## 8. Follow-ups

The three items in §6, most usefully breadcrumbs, since breadcrumb URLs feed hierarchy placement.
Documentation drift for this cycle is recorded in [0127 §9](0127-a-reason-the-crawl-never-recorded.md#9-documentation-drift-step-8).
