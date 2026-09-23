# Cycle 0103: A navigation carries no header

- **Date**: 2026-09-23
- **Scope**: Report-download buttons in `ReconcilePanel` and `PerformancePanel` switched from `<a href>` navigation to an authenticated fetch-then-blob download, closing a 401 that made every reconciliation/performance export unreachable since ADR 0016 shipped.
- **Commit**: `b662de581e1bebeaf7753c2e830cf555844f32d2`, fast-forward-merged to `origin/main` from worktree branch `worktree-agent-a21eefefd9a018ae6`.
- **Quality gate**: UI-only change — `npx tsc --noEmit -p .` clean; full vitest suite **37 test files passed, 394 tests passed** in 28.39s; `npm run build` succeeded in 23.94s (one pre-existing, unrelated chunk-size warning). Python gate not run this cycle — no `src/` file changed. All numbers below independently reproduced by this entry's author, not copied from the implementer unverified.

## 1. Gate results

Independently re-run in full:

```
npx tsc --noEmit -p .
(no output — clean)

npx vitest run
 Test Files  37 passed (37)
      Tests  394 passed (394)
   Duration  28.39s (transform 6.37s, setup 11.22s, collect 148.82s,
              tests 147.50s, environment 38.29s, prepare 5.87s)

npm run build
✓ 3067 modules transformed.
dist/index.html                            1.35 kB │ gzip:   0.73 kB
dist/assets/index-CBiur5QI.css             47.57 kB │ gzip:  10.00 kB
dist/assets/synthetic-500-CqKmg5V8.js     386.76 kB │ gzip:  15.43 kB
dist/assets/index-8gCYMIfk.js           1,231.45 kB │ gzip: 386.45 kB
dist/assets/synthetic-20000-CWU9lvCu.js 16,018.27 kB │ gzip: 472.00 kB
(!) Some chunks are larger than 2000 kB after minification...
✓ built in 23.94s
```

The chunk-size warning is the `synthetic-20000` fixture bundled for a demo
mode; it predates this cycle and has no relationship to the fix. It is
recorded here only so a future reader does not mistake it for a regression
this change introduced.

The three directly affected test files, run in isolation, also independently
reproduced: `httpAdapter.test.ts`, `ReconcilePanel.test.tsx`,
`PerformancePanel.test.tsx` — **3 files, 51 tests, all passed**, 8.28s.

The Python quality gate (`ruff format`, `ruff check`, `mypy --strict`,
`pytest`) was **not run** as part of this cycle. No file under `src/` changed
— every file in the diff is under `rankuno-ui/src/`. Running it would have
measured only whatever unrelated concurrent work is sitting in the working
tree, not this change.

## 2. What landed

A user reported that clicking a report download link (e.g.
`reconciliation.xlsx`) in the deployed app returned
`{"detail":"missing Authorization header"}` instead of downloading the file.
Root cause: several download buttons rendered as plain
`<a href={API_BASE}/jobs/{id}/...}>` elements. Every route under
`/jobs/{id}/...` has required a bearer session token since ADR 0016
(build-log 0097), and a browser navigation triggered by clicking an anchor
has no mechanism to attach a custom `Authorization` header — the request
reaches the server with none, and the server correctly refuses it.

- **`rankuno-ui/src/adapters/httpAdapter.ts`** gained
  `downloadFile(url, fallbackFilename): Promise<void>`. It calls the existing
  `authorizedFetch` (the same bearer-token plumbing every other adapter call
  already goes through), reads the response as a `Blob`, and hands it to the
  browser via the pre-existing `saveBlob()` helper in `src/lib/download.ts`
  (shipped in an earlier cycle for the Screaming Frog worker-bundle
  download — this is its second caller, not a new mechanism). A new
  `filenameFromContentDisposition()` helper parses the filename out of the
  response's `Content-Disposition` header (`attachment; filename="..."`),
  falling back to a caller-supplied name when the header is absent or
  unparseable. On a non-2xx response `downloadFile` throws an `ApiError`
  (`describeFailure`, already used elsewhere in the file, was exported so the
  new function could reuse it); a `401` runs the same shared
  session-expired handler every other `authorizedFetch` call triggers,
  so callers do not need to special-case it.
- **`ReconcilePanel.tsx`** — 3 call sites converted from `<a href download>`
  to `<button onClick>`: the `reconciliation.xlsx` and `reconciliation.csv`
  whole-cross-check downloads, and the shared `GapDownload` component (one
  implementation, rendered twice — once per `side` param, `frog` and
  `engine`). Each tracks its own `downloading` state, disables itself and its
  sibling(s) while a fetch is in flight, and calls `message.error` on
  failure.
- **`PerformancePanel.tsx`** — 4 call sites converted the same way:
  `matched.csv`, `unmatched.csv` (one shared `downloading` flag between the
  pair, by design — see §4), `opportunities.xlsx`, `opportunities.csv`.
- **`jobs.css`** — the `.jb-download`, `.perf-download`, and
  `.perf-download-plain` classes gained a button-chrome reset (`border: none;
  background: none; padding: 0; font-family: inherit; cursor: pointer;`) plus
  a `:disabled` state (`cursor: default; opacity: 0.6`), so the new
  `<button>` elements are visually indistinguishable from the `<a>` elements
  they replaced.

No backend change was needed. `server.py`'s `_csv_response` and
`_workbook_response` helpers already set `Content-Disposition` on all 7
affected routes — the frontend just was not reading it.

## 3. Design decisions

- **Fetch-then-blob, not a signed short-lived URL.** The alternative to
  carrying the bearer token on the download itself would be a backend
  endpoint that mints a one-time signed URL an `<a href>` could then follow
  unauthenticated. Rejected: it is a second auth mechanism alongside ADR
  0016's bearer tokens, for a problem the existing `authorizedFetch` already
  solves for every other request in the app. `downloadFile` is the one place
  in the codebase that saves a fetched file, so every future download link
  should call it rather than grow its own `<a href={API_BASE}...}>`.
- **One shared `downloading` flag per matched/unmatched pair, not two
  independent ones.** `PerformancePanel`'s `matched.csv`/`unmatched.csv`
  buttons intentionally share a single `downloading` state so the second
  button is disabled while the first fetch is in flight. This is existing,
  deliberate loading-state behavior carried over unchanged from the earlier
  `<a>`-based buttons' shared-panel disabled logic (see §4 for how a test
  initially mistook this for a bug).
- **Scope: re-verify every file named in the bug report rather than trust
  the initial grep.** See §5 — the correction is significant enough that it
  changed which files were touched.

## 4. Bugs found and fixed

- **The reported bug**: 7 download call sites across `ReconcilePanel.tsx`
  and `PerformancePanel.tsx` used `<a href={API_BASE}/...}>`, which cannot
  carry the `Authorization: Bearer <token>` header ADR 0016 requires. Every
  click 401'd. Fixed by routing all 7 through the new `downloadFile()`.
- **`.operators/` gitignore gap** — flagged to this scribe as part of this
  cycle's brief, but on inspection it is **not** part of this commit. It was
  already fixed on 2026-09-16 in commit `571cdd6` ("feat(ui): session-token
  login screen and auth wiring (ADR 0016)"), which added `.operators/` to
  `.gitignore` as a same-commit side-fix. `.gitignore` has no changes in
  `b662de5` and no uncommitted changes in the working tree at the time of
  writing. It is recorded here only to correct the claim, not as work done
  in this cycle — see §5.
- **Test bug 1 — `role`+`label` query collided with an unrelated element.**
  `ReconcilePanel.test.tsx`'s per-figure download test originally queried
  `getAllByRole("link", { name: /^Download 1$/ })`. Once `GapDownload`
  became a `<button>`, that query started colliding with the panel's
  unrelated per-figure `Stat` buttons, which share the same `"Download 1"`
  label whenever a figure also has exactly one URL. The test was not
  actually broken by the fix; the query was too loose to survive the
  element-type change. Fixed by querying on the button's `title` attribute
  (`"...as a workbook, one sheet per reason"`), which only the `GapDownload`
  buttons carry.
- **Test bug 2 — sequential clicks without awaiting the first fetch.**
  `PerformancePanel.test.tsx`'s matched/unmatched test originally fired both
  download clicks back-to-back and timed out waiting for the second fetch.
  This was not a bug in the app: the two buttons intentionally share one
  `downloading` flag (§3), so the second button is disabled — and a disabled
  button fires no click — until the first fetch settles. The test was wrong,
  not the code. Fixed by awaiting `fetchSpy` reaching 1 call before firing
  the second click.

## 5. Corrections

The bug report that opened this cycle named 8 suspected files, found by
grepping for `<a href={API_BASE}`. The implementer re-verified each one
individually rather than trusting the grep, and found the bug only actually
existed in 2 of the 8:

- **Actually broken (fixed here)**: `ReconcilePanel.tsx` (3 call sites),
  `PerformancePanel.tsx` (4 call sites) — 7 call sites total.
- **Named in the report, re-verified, not broken**: `VirtualizedTree`,
  `GscIntegratedReport`, `RedirectTable`, `DuplicateTable`, `OrphanTable`
  (5 files). Their downloads are built client-side from data already loaded
  into the page (CSV assembled in the browser, or a link to an
  externally-crawled page's own URL) and never construct an authenticated
  `API_BASE` request. They were never actually broken by the ADR 0016
  rollout.

Also correcting a claim handed to this scribe for this entry (not a
previously *published* claim, so it is recorded here rather than reopening
an old entry): the brief stated the `.operators/` `.gitignore` gap was
"fixed in this cycle." It was not — see §4. That fix shipped over a week
earlier, in commit `571cdd6` (2026-09-16), and is unrelated to `b662de5`.

## 6. Explicitly not done

- **No exhaustive audit of every possible future authenticated-download call
  site.** The 2-file, 7-call-site scope here is what the targeted
  re-verification in §5 found broken today. It is not a guarantee that no
  other component will grow an `<a href={API_BASE}...}>` in the future;
  nothing in the codebase currently prevents that pattern from reappearing
  (e.g. a lint rule or a shared component that forces `downloadFile` usage).
- **No backend change.** `server.py`'s `Content-Disposition` handling on the
  7 affected routes was already correct and needed nothing.
- **`downloadUrlList` (in `adapterInterface.ts`, `CrawlJobsView.tsx`/
  `CrawlJobsView.test.tsx`, `httpAdapter.ts`, and backend files) is a
  separate, currently uncommitted feature from a concurrent work session.**
  It is not part of this cycle's commit or scope and is not described as
  done or in-progress by this entry.

## 7. Files changed

```
 rankuno-ui/src/adapters/httpAdapter.test.ts        | 77 ++++++++++++++++++-
 rankuno-ui/src/adapters/httpAdapter.ts             | 49 +++++++++++-
 rankuno-ui/src/components/jobs/PerformancePanel.test.tsx | 57 +++++++++++---
 rankuno-ui/src/components/jobs/PerformancePanel.tsx      | 85 +++++++++++++++-----
 rankuno-ui/src/components/jobs/ReconcilePanel.test.tsx   | 18 ++++-
 rankuno-ui/src/components/jobs/ReconcilePanel.tsx        | 84 ++++++++++++++-----
 rankuno-ui/src/components/jobs/jobs.css                  | 39 +++++++++-
 7 files changed, 354 insertions(+), 55 deletions(-)
```

## 8. Follow-ups

- Consider a shared "authenticated download button" component so future
  export links cannot regress to `<a href={API_BASE}...}>` by construction,
  rather than relying on re-verification catching it next time.
- The `downloadUrlList` work in progress on the same files (§6) will need
  its own build-log entry when it lands.
