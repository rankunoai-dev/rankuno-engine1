# Cycle 0111: The wizard test had never executed; running it found three real component bugs

- **Date**: 2026-09-27
- **Scope**: `NewCrawlWizard.test.tsx` made runnable (a store mock with stable identities), three defects it then exposed fixed, `verify.ps1` given a real UI-stage timeout, Vitest fork count capped.
- **Commit**: uncommitted at time of writing
- **Quality gate**: UI **473/473** as reported by the operator's run; see §1
- **Session thread**: entry 6 of 6 — see [0106 §0](0106-a-pattern-that-never-reaches-the-form.md)

## 1. Gate results

Statically obtained here; the pass/fail figures are the operator's run, reported
as theirs and not re-executed in this session (a concurrent Vitest run would have
competed for the same fork pool the fork-count change was measured against).

| Measurement | Value | How |
| :--- | :--- | :--- |
| `NewCrawlWizard.test.tsx` `it(` blocks | 9 → **15** | counted at `HEAD` and in the tree |
| Blocks skipped or weakened | **0** | no `it.skip`/`it.todo` in the file |
| `NewCrawlWizard.test.tsx` diff | +306/-77 | `git diff --numstat` |
| `scripts/verify.ps1` diff | +68/-5 | same |
| `rankuno-ui/vite.config.ts` diff | +19/-0 | same |
| Reported UI suite | 41 files / 473 tests, 473/473 green at `maxForks: 4`; 2–3 files failing per run at the default | operator's measurements, recorded in the `vite.config.ts` comment |

## 2. What landed

**One frozen store mock.** The file now builds a single module-scope `STORE`
object with stable `startCrawl` and `adapter.listGscAccounts` identities, and the
`useCrawlStore` mock returns it. The module docstring states the rule and the
reason, so the next person does not "tidy" the object literal back inside the
selector.

**A host that mirrors the app.** `WizardHost` keeps `NewCrawlWizard` mounted and
toggles only `open`, exactly as `DashboardShell` does. That is what makes "is the
wizard clean when it is reopened?" a question about the component rather than
about React's unmount behaviour — and it is what let the Cancel-button defect
(§4) be expressed as a test at all.

**`scripts/verify.ps1 -UiTimeoutSeconds` (default 600).** The UI stage now runs
as a child process the script owns the handle to, via
`System.Diagnostics.ProcessStartInfo`, with `WaitForExit(ms)`; on expiry it runs
`taskkill /T /F` on the tree — cmd → node → one tinypool worker per file — and
reports exit code 124 with the bisect command to run. `NODE_OPTIONS` gains
`--max-old-space-size=2048` for the child only, so a runaway render loop becomes
a fast OOM instead of a process that grows until the workstation swaps. Both
bounds are needed: the cap bounds the damage, the timeout bounds the wait.

**`poolOptions: { forks: { maxForks: 4, minForks: 1 } }`** in `vite.config.ts`,
with the measurement that justifies it in a comment rather than in a commit
message.

## 3. Design decisions

**A timeout in the gate, not a longer test timeout.** No assertion, budget or RTL
timeout was relaxed. The claim being made is narrow: a gate that hangs is worse
than one that fails, because a hang is indistinguishable from a slow run and
produces no verdict for anyone — operator or CI — to act on. 600s is roughly 8×
the measured 67–71s suite, so it is a hang detector, not a performance budget.

**Cap the fork count rather than raise timeouts.** Vitest defaults to one fork per
logical CPU: on the 20-core workstation that is 20 concurrent jsdom environments
each mounting antd. These tests are latency-bound — they sit in `waitFor` polls
and antd's own timers — so the parallelism bought nothing and starved each
worker's timers, and RTL's 1s async timeout began expiring on renders that had
done nothing wrong. Measured: default 20 forks → 2–3 files failing per run, a
*different* set each time, every one green in isolation, 67–70s; 4 forks →
473/473, 67s. Identical wall clock, so the parallelism was costing a deterministic
gate and buying nothing.

**Own the process handle.** See §4: the first implementation used
`Start-Process -PassThru` and could not read an exit code at all.

## 4. Bugs found and fixed

### 4.1 The test file had never executed once since being committed

Its `useCrawlStore` mock rebuilt the store object — including `adapter` — inside
the selector callback, so every call, and therefore every render, produced a new
`adapter` identity. `NewCrawlWizard` lists `adapter` in the dependency array of
its GSC-account effect and stores the result with `setGscAccounts`, which closes
the loop: render → effect → resolve → setState → render. It never settled.
`listGscAccounts` was measured at 32, 70, 109, 148, 187 and 234 calls across
successive drains of the event loop. The heap grew from the retained `vi.fn()`
spy call records, not from the DOM — the DOM stayed flat at 83 nodes — and the
worker was killed past 3 GB.

Three of the original nine tests survived this because they returned before the
loop had ticked twice. The two that awaited a `waitFor` handed it the event loop
and died. And because **Vitest does not exit after `Worker exited unexpectedly`**
— it waits on a worker that is gone — `verify.ps1` hung rather than failed, which
is why this had never been diagnosed: the stage produced no failure to read.

The real zustand store cannot behave this way; `adapter` is a field it hands back
by reference. The single frozen `STORE` is therefore not a convenience, it is the
part of the mock that makes it a faithful stand-in.

### 4.2 Three component bugs, found because a test was right and the code was wrong

**(A) Cancel did not reset the wizard.** The Modal's close icon, Esc and a mask
click all went through a handler that called `onClose()` *and* `reset()`; the
Cancel button called `onClose` alone. Invisible in isolation, but
`DashboardShell` never unmounts the wizard — it toggles `open` — so cancelling on
the Domain stage and reopening put the operator back on the Domain stage with the
previous domain still in the field. One click from crawling the wrong site. Every
close affordance now routes through one `handleClose()`.

**(B) One successful crawl bricked the wizard.** `setSubmitting(false)` existed
only on the `catch` branch, so after a crawl that *worked*, `submitting` stayed
true for the life of the page: reopening showed a permanently spinning primary
button and a disabled Cancel, and no second crawl could be started without a
reload. Moved to `finally`. `reset()` is deliberately still absent from the
failure path, so a failed start reopens holding what the operator typed.

**(C) The payload was serialized after `onClose()`.** Closing re-renders the
parent and can clear the wizard; reading the form after that point worked only by
accident of closure capture. `serializeToPayload()` now runs before `onClose()`,
so the body cannot depend on when the close lands.

**Also fixed while in the file:** `destroyOnClose` is deprecated in antd 5 and
warned on every render; replaced with `destroyOnHidden`.

### 4.3 A bug in the harness fix itself, caught before it shipped

The first attempt at the UI-stage timeout used `Start-Process -PassThru`. That
cmdlet does not retain the process handle, and the object it returns reports
`$null` for `ExitCode` **even after a clean exit**. Measured: a 473-test run that
passed came back with `ExitCode` null, `$null -ne 0` evaluated true, and the stage
announced FAILED on a green suite. Replaced with
`[System.Diagnostics.Process]::Start($psi)`, which keeps the handle and gives a
real exit code — verified 0 on pass and 1 on fail, and the timeout path verified
by expiry. A gate change that turns passes into failures is the same class of
defect as one that turns failures into passes, so it is recorded here rather than
dropped as a discarded draft.

## 5. Corrections

**"Component tests (6+)" / "Integration tests for full wizard flow"**, in commit
`8d606db` and in build-log `0102-phase2-new-crawl-wizard.md`: the file contained 9
`it(` blocks and none of them had ever run. Neither document is edited; see cycle
0109 §5 for the full correction of that commit's claims.

**A green UI stage before this cycle did not mean the UI suite passed.** Because a
dead worker makes Vitest hang rather than exit, any run that included this file
produced no verdict at all — so an operator who stopped a hanging gate and
concluded "the tests are slow" was reading a silent failure. The `-UiTimeoutSeconds`
default exists so that reading is no longer available.

**The fork-count change is not a flakiness fix.** It made the suite
deterministic on the machine it was measured on. The three files that were
failing under contention — `GscAccountForm`, `ReconcilePanel`, `ScreamingFrogView`
— are still timing-fragile; see §6.

## 6. Explicitly not done

- **The three timing-fragile test files were not hardened.** `GscAccountForm`,
  `ReconcilePanel` and `ScreamingFrogView` are worked around at the harness level
  by limiting parallelism. On a machine with different core count or load they can
  fail again, and the fix would be to remove their dependence on wall-clock
  timers, not to cap forks further.
- **`maxForks: 4` is a constant measured on one 20-core workstation.** It is not
  derived from `os.availableParallelism()`, so a 4-core CI agent gets the same
  cap, and a 64-core one gets no benefit from the extra cores.
- **The timeout is only on the UI stage.** The Python stages of `verify.ps1` can
  still hang indefinitely; nothing bounds them.
- **`NewCrawlWizard.test.tsx` still mocks the store rather than the transport.** It
  proves the component's behaviour, not that a payload is accepted by the server
  (cycle 0109 §6 makes the same point about the hook).
- **No test asserts that `submitting` recovers** after a *successful* submit
  through a real `startCrawl` resolution ordering other than the one mocked here;
  bug (B) is covered by the reopened-state assertions, not by a state-machine test.
- **Nothing prevents the next selector-built mock.** The rule lives in one file's
  docstring. A lint rule or a shared `renderWithStore` helper would generalise it;
  neither exists.

## 7. Files changed

| File | Change |
| :--- | :--- |
| `rankuno-ui/src/components/crawl/NewCrawlWizard.test.tsx` | +306/-77 — frozen `STORE`, `WizardHost`, 9 → 15 tests, module docstring recording the loop |
| `rankuno-ui/src/components/crawl/NewCrawlWizard.tsx` | +36/-9 — `handleClose()`, `finally { setSubmitting(false) }`, payload serialized before `onClose()`, `destroyOnHidden` |
| `scripts/verify.ps1` | +68/-5 — `-UiTimeoutSeconds` (default 600), owned process handle, `taskkill /T /F`, exit 124, child-only `NODE_OPTIONS` heap cap |
| `rankuno-ui/vite.config.ts` | +19 — `maxForks: 4`, with the measurement in a comment |

## 8. Follow-ups

1. Remove the wall-clock dependence in `GscAccountForm`, `ReconcilePanel` and
   `ScreamingFrogView` tests, then re-test whether the fork cap is still needed.
2. Derive `maxForks` from available parallelism instead of hardcoding 4, once (1)
   is done.
3. Bound the Python stages of `verify.ps1` the same way.
4. A shared test helper that provides the store with stable identities, so the
   frozen-mock rule is structural rather than a docstring.
