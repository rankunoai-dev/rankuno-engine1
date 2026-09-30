# Cycle 0130: A method called without its object

- **Date**: 2026-09-30
- **Scope**: Production bug — the Crawl jobs row menu items "Download URLs" (.xlsx) and
  "Download URLs (PDF)" never downloaded anything
- **Commit**: `65cf0d2` ("fix(ui): call Download URLs methods on the adapter, not detached")
- **Quality gate**: UI only, see §1. The Python gate was not run; no Python changed.

**Numbering note**: the highest committed entry on this branch is `0129`. `0125` exists only as an
uncommitted file in the main checkout (another session) and was treated as taken; `0130` was free
in both places.

## 0. Background

The user reported this repeatedly. On a finished crawl, clicking either download item in the job
row's "More actions" menu produced no file. A toast read
`Cannot read properties of undefined (reading 'baseUrl')`, and the browser Network log showed no
request to `urls.xlsx` or `urls.pdf` at all. The user asked for the fix to be actually downloaded
and tested, not asserted.

## 1. Gate results

### UI, run by the implementer on the fixed code (reported; not re-run by the scribe)

```
tsc --noEmit           -> exit 0
vitest run             -> Test Files  48 passed (48)
                          Tests  607 passed (607)
```

The scribe attempted to re-run `vitest` in this worktree and could not: the worktree has no
`rankuno-ui/node_modules` (`ERR_MODULE_NOT_FOUND`). The figures above are the implementer's, stated
as such.

### Real-browser end-to-end (implementer's run)

Python Playwright 1.62 driving the machine's installed Chrome, headless, against a local server
started from a clean worktree with a production-style UI build (`VITE_API_BASE=/api/v1`, the same
value the Dockerfile uses), a local bootstrap operator, and one real stored crawl (vitaquest.com,
job `bd7354138b2d454ebfda21892f453437`) copied in. The script logs in, opens the engine, opens
Crawl jobs, opens the row's "More actions" menu, clicks each download item, and captures toasts,
requests and the downloaded file.

Before the fix (origin/main `ff3b2a0`):

```
[FAIL] Download URLs: no download within 12s; toasts seen: ["Cannot read properties of undefined (reading 'baseUrl')"]
[FAIL] Download URLs (PDF): no download within 12s; toasts seen: ["Cannot read properties of undefined (reading 'baseUrl')"]
requests to /urls.*: NONE
```

After the fix (`65cf0d2`):

```
[PASS] Download URLs: saved urls-bd735413-2026-09-15.xlsx (21142 bytes, starts b'PK\x03\x04'); toasts: none
[PASS] Download URLs (PDF): saved urls-bd735413-2026-09-15.pdf (16840 bytes, starts b'%PDF'); toasts: none
requests to /urls.*: ['.../jobs/bd7354138b2d454ebfda21892f453437/urls.xlsx', '.../urls.pdf']
```

The downloaded files were opened and checked:

| File | Check | Result |
| :--- | :--- | :--- |
| `.xlsx` | Sheets | `All URLs`, `By Indexability`, `By HTTP Status` |
| `.xlsx` | Rows per sheet | 95 (94 URLs + header) |
| `.xlsx` | Header | `URL`, `Hierarchy Level`, `Page Type`, `HTTP Status`, `GSC Clicks`, `GSC Impressions`, `GSC CTR %`, `GSC Avg Position`, `Depth`, `Discovery Method`, `Reachability Tier` |
| `.pdf` | Pages | 5 |
| `.pdf` | Trailer | ends with `%%EOF` |

**Two earlier browser runs were invalid and do not count.** The first build baked a Windows path
into the API base: Git Bash (MSYS) rewrote `/api/v1` into `C:/Program Files/Git/api/v1`. Fixed by
setting `MSYS_NO_PATHCONV=1` for the build. The second run's menu selector matched nothing, because
each menu item carries a description line under its label, so its "no download" result tested
nothing. Only the before/after runs above were valid.

## 2. What landed

**`rankuno-ui/src/components/jobs/CrawlJobsView.tsx`** — the component now selects the adapter
instance from the store (`useCrawlStore((state) => state.adapter)`) and calls
`adapter.downloadUrlList(row.id)` / `adapter.downloadUrlListPdf(row.id)`. The per-item visibility
flags are unchanged in meaning: `canDownloadUrls` and `canDownloadUrlsPdf` are each derived from
whether that one method exists on the adapter. `HttpAdapter` is unchanged.

**`rankuno-ui/src/components/jobs/CrawlJobsView.httpAdapter.test.tsx`** (new, 89 lines) — drives
`CrawlJobsView` with a real `new HttpAdapter(...)` and `fetch` stubbed, asserting the
`urls.xlsx` / `urls.pdf` request is made, the saved filename, and that no error toast appears.

```
rankuno-ui/.../jobs/CrawlJobsView.httpAdapter.test.tsx | 89 +++++++++++++++++
rankuno-ui/src/components/jobs/CrawlJobsView.tsx       | 30 +++++---
2 files changed, 108 insertions(+), 11 deletions(-)
```

## 3. Root cause

Before the fix, the component pulled the methods off the adapter and called them bare:

```ts
const downloadUrlList = useCrawlStore((state) => state.adapter?.downloadUrlList);
...
await downloadUrlList(row.id)
```

`HttpAdapter.downloadUrlList` and `downloadUrlListPdf` are class methods whose first line builds
`${this.baseUrl}/jobs/...`. Called detached, `this` is `undefined`, so reading `.baseUrl` throws a
`TypeError` before `fetch` is reached. That is why the Network log showed no request: nothing ever
left the browser. The `catch` block turned the `TypeError` into the toast.

The existing tests did not catch it because `CrawlJobsView.test.tsx` supplied a plain object of
`vi.fn()` mocks as the adapter. A `vi.fn()` never reads `this`, so a detached call behaves
identically to a bound one.

A repo-wide search found no other detached call on an adapter method. `LiveCrawlModal` already
calls its method with `.call(adapter)`.

## 4. Bugs found and fixed

| # | Bug | Where | Fix |
| :--- | :--- | :--- | :--- |
| 1 | Detached `HttpAdapter` method calls; `this` undefined, request never sent | `CrawlJobsView.tsx` | Call the methods on the adapter instance |
| 2 | Test double could not detect the defect class: plain-object `vi.fn()` adapter never touches `this` | `CrawlJobsView.test.tsx` | New test file using a real `HttpAdapter` with `fetch` stubbed. On the old code both new tests failed with exactly `Cannot read properties of undefined (reading 'baseUrl')`; on the fix both pass |

## 5. Corrections

1. **"Probably a stale browser cache."** Earlier in this session the assistant told the user the
   `baseUrl` toast was probably a stale browser cache. That was wrong. The toast came from the
   current bundle and reproduced on a fresh production-style build (§1).
2. **Build-log 0125** (`0125-boundaried-like-its-siblings.md`, another session, uncommitted on this
   branch) wrapped `CrawlJobsView` in an `ErrorBoundary` and stated that it did not locate the throw
   site. It contained a crash; it did not fix this bug, and the download items stayed broken after
   it. 0125 is not edited; this entry is the correction.
3. **A read-only investigation in this session** concluded that `this.baseUrl` "cannot be
   undefined unless the object isn't a real class instance", and on that basis pointed away from
   `HttpAdapter`. The reasoning inspected the wrong variable: `this.baseUrl` was never the thing
   that was undefined. `this` was, because the method had been detached from its instance.

## 6. Explicitly not done

- **Not clicked on production.** This session had no production credentials, so the end-to-end
  run in §1 was local against a production-style build. What *was* confirmed on production: about
  90 s after the push, Railway began serving `assets/index-BRLBqX0h.js` in place of
  `assets/index-BwW0ScSS.js`, and `BRLBqX0h` is exactly the content hash of the locally built,
  browser-tested bundle — so the code in production is byte-identical to the code that passed §1.
  The user was asked to hard-refresh and confirm both downloads.
- **No lint rule against detached adapter methods.** The repo has no ESLint config, so no rule
  (for example `@typescript-eslint/unbound-method`) was added. The same mistake can be reintroduced
  in any component; only the new test guards this one.
- **The end-to-end browser script is not in the repo.** It lives only in the session scratchpad.
  Recommended follow-up: a committed Playwright smoke test that opens Crawl jobs and exercises both
  downloads against a real stored crawl.
- **The Python gate was not run.** No Python changed.
- **`/api/v1/crawl-activity` 404s** seen in the user's console were not investigated further. An
  unauthenticated probe of production returned 401, so the route exists; the 404s were most likely
  the redeploy window after a push. Not confirmed. The reconciliation 404 for job `202c2acc…` is
  the normal "no saved reconciliation" response, not a bug.

## 7. Documentation drift (Step 8)

`README.md` already described both download items and their endpoints correctly as intended
behaviour; the description did not change. One sentence was added after that paragraph recording
that the items were broken in production until this cycle, linking this entry.
`docs/ARCHITECTURE.md` does not list `CrawlJobsView` or the UI download path (only the server
endpoints and `reports.py`, which are unchanged), so it was not edited. No ADR: this is a bug fix
with no new decision.
