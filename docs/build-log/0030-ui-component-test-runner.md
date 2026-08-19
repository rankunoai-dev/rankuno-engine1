# Cycle 0030: A component test runner, and the four bugs it found in an hour

- **Date**: 2026-08-19
- **Scope**: Vitest + React Testing Library in `rankuno-ui`, wired into the Step 7
  gate, with tests for the four components most likely to crash on mount.
- **Commit**: uncommitted at time of writing
- **Quality gate**: `1320 passed` Python / `23 passed` UI / `Total coverage: 94.98%`

---

## 1. Gate results

```
PASSED: Format
PASSED: Lint
PASSED: Type check
Required test coverage of 85.0% reached. Total coverage: 94.98%
1320 passed, 1 warning in 103.95s (0:01:43)
PASSED: Tests

=== UI Component Tests ===
 Test Files  4 passed (4)
      Tests  23 passed (23)
   Duration  3.37s (tests 1.25s)
PASSED: UI Component Tests

ALL GATES PASSED.
```

Frontend: `tsc --noEmit` exit 0.

---

## 2. Why this was worth a cycle

Three cycles shipped UI with no automated check that a component renders. The
bill so far, all of it invisible to `tsc` and `vite build`:

* **0021** — `CrawlReport` called `.toLocaleString()` on a counter absent from
  stored results. React unmounts the whole tree on an uncaught render throw, so
  the dashboard went black with no message.
* **0029** — `Upload.Dragger` would have POSTed the export to an endpoint that
  does not exist, and a size guard was written where only the browser can
  enforce it.

Both typecheck. Both build. Neither is reachable without mounting the component.

### Does it actually catch that class of bug?

Tested rather than assumed. Reverting `beforeUpload` to `return true` — the
exact cycle-0029 defect — fails five tests including the one written for it, and
restoring it returns the file to 9 passing. A test suite that has never been
seen to fail is a suite nobody should trust.

---

## 3. What landed

`vitest` + `@testing-library/react` + `@testing-library/jest-dom` + `jsdom`, four
test files, a fixture factory, and a gate stage.

### The gate stage skips rather than fails when node is missing

`Invoke-UiGate` is separate from `Invoke-Gate` because the latter runs
everything through the venv's python. Two deliberate behaviours:

* **node is located, not assumed.** It is routinely absent from `PATH` on
  Windows even when installed; the fallback is the default install location.
  This cost time in three previous cycles.
* **A missing toolchain skips in yellow and is not counted as a pass.** A
  Python-only contributor should not be blocked, but a check that did not run
  has protected nothing and must not print `PASSED`.

### Fixtures built from the generated types

`src/test/factories.ts` constructs whole `PageClassificationOutput` values from
`schema.ts` rather than casting `{}`. That paid for itself within the hour: it
would not compile against the current contract, because a concurrent session had
added `loop_urls_skipped` to `DiscoveryReport`. A stubbed fixture would have
sailed past.

---

## 4. Bugs found and fixed

### The setup file is four polyfills, and every one was a crash first

None is precautionary. `matchMedia`, `ResizeObserver` and
`HTMLElement.scrollTo` are absent or throw in jsdom, and antd or the tree calls
each on mount. The fourth is the interesting one:

**`Blob.prototype.text` does not exist in jsdom at all.** `typeof file.text` is
`undefined`, so `ReconcilePanel` threw the moment a file was chosen. Polyfilled
over `FileReader` — which jsdom does implement — rather than returning a canned
string, because a stub that ignored the blob would let a test pass while the
component read the wrong file.

### A cleanup hook that broke every test it was meant to fix

antd Modals portal into `document.body`, outside RTL's container, and the
wrapper can outlive `cleanup`. The symptom is the worst kind: tests pass alone
and fail together, because the second to open the same modal sees two copies.

The first fix made it worse. Registered as a *second* `afterEach`, it ran
**before** `cleanup` — Vitest runs those hooks last-registered-first — and tore
the DOM out from under React, failing all nine tests with "the node to be
removed is not a child of this node". It also removed each node's *parent*,
which invalidated the sibling still to be swept. Now one hook: `cleanup()`,
then remove the nodes themselves.

### A 10-second hang charged to every gate run

The suite finished in ~1s and then sat for the full teardown timeout. The
`hanging-process` reporter reports 26 open file handles with no stack trace
between them — Vite's, not ours, on Windows. `pool: "forks"` did not help.
`teardownTimeout: 1_000` cuts wall clock from 12.6s to ~3.4s. The run has
already exited zero by then; this is a shortened wait, not a fix, and it is
labelled as one.

### The units in the size guard disagreed with the message it printed

`MAX_CSV_BYTES` was `80 * 1024 * 1024` while the refusal divides by `1e6`, so an
84 MB file was rejected by an "80 MB" limit, leaving the operator 4 MB to
explain. Found because the test asserted `/200 MB/` and the component said
`210 MB`. Limit is now decimal, and the two agree.

### Two of my own tests asserted the wrong thing

Recorded because both were nearly kept:

* `getByText(/https:\/\/e\.com\//)` on `CrawlReport` failed on **correct**
  output — header and footer both name the site. Fixed the assertion, not the
  component.
* `VirtualizedTree` was asserted with `toBeLessThan(model.nodes.length)`, which
  **also passes when nothing renders at all**. jsdom has no layout engine, so
  the viewport measures 0 and the window collapses to 3 rows for 601 nodes.
  Measured, then bounded on both sides. A vacuous assertion is worse than none:
  it reports protection that does not exist.

---

## 5. Corrections

**Cycle 0029 §8 asked for "a frontend test runner" and implied that would make
the UI verified. It does not.** These tests mount components in jsdom. They
cannot see layout, paint, focus rings, print CSS, or anything requiring a real
viewport — `FocusGraphStage`'s whole purpose is geometry and it is untestable
here. The claim this cycle supports is narrower and worth stating exactly: **a
component that throws on mount, a handler that is never wired, and a prop that
arrives undefined can no longer reach a green gate.**

**The plan's "<1s" is the test duration, not the wall clock.** Tests take
~1.25s; the command takes ~3.4s including transform, environment setup and the
shortened teardown. Both numbers are above, and the second is the one an
operator waits for.

---

## 6. Explicitly not done

- **No coverage threshold on the UI.** Python enforces 85%; the UI enforces
  nothing. Four components are covered out of roughly twenty. A number here now
  would be a target nobody chose.
- **`FocusGraphStage`, `HeaderBar`, `CrawlJobsView`, `KpiMetricStrip` and the
  adapters are untested.** The four in this cycle were picked because they crash
  or have crashed; the rest are simply not covered yet.
- **No interaction testing beyond file choice.** No `user-event` dependency was
  added, so clicks, keyboard navigation and drag-and-drop proper are unexercised
  — the upload tests fire a `change` on the hidden input, which is what antd
  listens to, not a real drop.
- **Still nothing is rendered in a browser.** jsdom is not a browser. The plan's
  manual verification step remains outstanding, and these tests do not replace
  it.
- **The teardown hang is worked around, not fixed.** If Vitest resolves the
  Windows file-handle issue upstream, `teardownTimeout` should go.
- **`docs/build-log/` now holds two 0029 entries** as well as two 0022s, from
  concurrent sessions. The numbering rule in that directory's README says
  numbers are never reused. This is the second occurrence and it needs an owner.

---

## 7. Files changed

| File | Change |
| :--- | :--- |
| `rankuno-ui/package.json` | vitest, RTL, jest-dom, jsdom; `test` and `test:watch` |
| `rankuno-ui/vite.config.ts` | `test` block — jsdom, forks, teardown, include glob |
| `rankuno-ui/src/test/setup.ts` | New — cleanup hook and four polyfills |
| `rankuno-ui/src/test/factories.ts` | New — contract-valid fixtures |
| `rankuno-ui/src/components/report/CrawlReport.test.tsx` | New — 7 tests |
| `rankuno-ui/src/components/jobs/ReconcilePanel.test.tsx` | New — 9 tests |
| `rankuno-ui/src/components/tree/VirtualizedTree.test.tsx` | New — 3 tests |
| `rankuno-ui/src/components/inspector/NodeInspector.test.tsx` | New — 4 tests |
| `rankuno-ui/src/components/jobs/ReconcilePanel.tsx` | Size limit now decimal MB |
| `scripts/verify.ps1` | `Invoke-UiGate` |

## 8. Follow-ups

- Cover `HeaderBar` and `CrawlJobsView`; both branch on adapter capability and
  on live-job state, which is exactly where a prop-wiring bug hides.
- Set a UI coverage floor once enough components are covered for a number to
  mean something.
- Decide whether `FocusGraphStage` gets a geometry harness or is accepted as
  browser-only. Its measure pass is the most intricate code in the UI and the
  least protected.
