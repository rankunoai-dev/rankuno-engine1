# Cycle 0094: A fourth speed with no label

- **Date**: 2026-09-13
- **Scope**: A "Custom" fourth option on `LiveCrawlModal.tsx`'s crawl-speed
  Segmented control, letting an operator set an independent
  requests-per-second rate (down to 0.05) and concurrency instead of only
  choosing Polite / Standard / Turbo. UI-only; no schema or backend change.
- **Commit**: uncommitted at time of writing
- **Quality gate**: `LiveCrawlModal.test.tsx` 10 passed (independently
  re-run); `tsc --noEmit` clean; `npm run contract` up to date; whole-repo
  Python gate not touched by this cycle (no Python file changed)

---

## 1. Gate results

Targeted, independently re-run by the doc-log author, not summarised from the
implementer's report:

```
$ npx vitest run src/components/layout/LiveCrawlModal.test.tsx
 ✓ src/components/layout/LiveCrawlModal.test.tsx > LiveCrawlModal custom speed > ... (10 tests)
 Test Files  1 passed (1)
      Tests  10 passed (10)
```

```
$ npm run typecheck
> tsc --noEmit
(exit 0, no output)
```

```
$ npm run contract
> python ../scripts/export_ui_contract.py --check
UI contract is up to date.
```

`npm run build` and the full 26-file `npm test` were not independently
re-run this cycle (see §9). The implementer reported `npm run build` →
"built in 11.64s" with a pre-existing >2000kB chunk-size warning, and full
`npm test` → 284 passed / 3 pre-existing unhandled-rejection notices in
`GscAccountForm.test.tsx`. `GscAccountForm.test.tsx` was confirmed to exist
and belongs to a concurrent session's GSC work (`git log` shows
`b3d7105 feat(seo,core,api): GSC account profiles and deliverables
boundary` and `4cee3b8 feat(ui): Add GSC property URL field to crawl form`
ahead of this branch's crawl-speed work) — plausible, not independently
re-executed.

`git diff --stat` for the two touched files:

```
 .../src/components/layout/LiveCrawlModal.test.tsx  |  87 ++++++++++++++
 .../src/components/layout/LiveCrawlModal.tsx       | 129 ++++++++++++++++++---
 2 files changed, 202 insertions(+), 14 deletions(-)
```

---

## 2. Origin

Client feedback (infosys.com and other large/defensive enterprise sites)
reported that the three fixed presets — Polite (1 rps, concurrency 5),
Standard (10 rps, concurrency 20), Turbo (25 rps, concurrency 50) — do not go
slow enough. Polite's 1 rps still trips defensive infrastructure on some
sites; the operator needs a rate below the slowest preset, not just a fourth
point between the existing three.

The design below was proposed and approved by the operator earlier in this
session, as a Step 3 HITL design pass. There is no prior build-log cycle to
cite for the design itself — this entry is its first written record.

---

## 3. Design decisions (from the approved plan)

* **Extend the Segmented control, do not replace it.** The three labelled
  presets keep their fixed rate/concurrency pairs and their explanatory
  detail text (the labelled-preset rationale from build-log 0017 §5). Custom
  is a fourth option, not a redesign of the other three, so an operator who
  never needs finer control sees no change.
* **Reuse `rate_limit_rps` / `concurrency` as-is.** No schema change, no
  backend change. Both fields already exist on the crawl input model, are
  already wired through to the per-host `AsyncTokenBucket`, and already carry
  server-side bounds independent of anything the UI does:
  `rate_limit_rps: float | None = Field(default=None, gt=0.0, le=25.0)` and
  `concurrency: int = Field(default=DEFAULT_CONCURRENCY, ge=1,
  le=MAX_CONCURRENCY)` (`src/modules/seo/page_classifier/tool.py:155,212`),
  with `MAX_CONCURRENCY = 200` (`src/modules/seo/page_classifier/
  async_discovery.py:102`). Confirmed by direct read of both files this
  cycle — the bounds the implementer cited are exact.
* **Custom rate floor: 0.05 rps** (one request per 20 seconds), deliberately
  below Polite's 1 rps, specifically to serve the infosys-class use case that
  motivated this feature.
* **Custom concurrency is independently settable**, seeded to Polite's value
  (5) the first time the operator switches into custom mode via the form's
  `initialValues`, rather than carrying over whatever the previously
  selected preset implied. A stale carried-over value would silently pair an
  intentionally slow custom rate with an unrelated preset's concurrency.
* **No new duration-estimate math.** A non-blocking advisory `Alert` appears
  only when `max_pages / custom_rate > 21,600` seconds (6 hours), worded
  explicitly as a rough single-host floor, and points to the crawl's own
  live ETA (`JobTelemetry.eta_seconds`) rather than reimplementing it. This
  keeps the estimate logic in exactly one place.
* **Robots `Crawl-delay` reconciliation is unchanged.** The `min()` of
  declared vs. configured rate (build-log 0017 §3) operates on whatever
  `rate_limit_rps` value reaches the backend, regardless of whether it came
  from a preset or from the custom fields — this cycle changed nothing there
  because it is UI-only.

---

## 4. What shipped

* `rankuno-ui/src/components/layout/LiveCrawlModal.tsx` — a fourth
  `"custom"` `SpeedChoice`; two new `Form.Item`/`InputNumber` fields
  (`custom_rate`, `custom_concurrency`) that replace the preset detail text
  when `speed === "custom"`; validation rules (`required`, `type: "number"`,
  `min`/`max`) mirroring the existing `base_url` rule pattern; the advisory
  `Alert`; and `submit()` branching to read the custom values instead of
  `preset.rate_limit_rps`/`preset.concurrency` when custom is selected.
* `rankuno-ui/src/components/layout/LiveCrawlModal.test.tsx` — new tests
  covering the custom fields, validation, the warning `Alert`, and that
  presets still submit their own unmodified rate/concurrency.

No changes to `adapterInterface.ts`, `tool.py`, `async_discovery.py`,
`http_fetcher.py`, `rate_limiter.py`, or `robots.py` — confirmed by `git
diff --stat` restricted to the two files above, and separately confirmed
`CRAWL_SPEEDS`/`CrawlSpeed` are untouched (no diff against them in this
branch).

---

## 5. Bugs found and fixed

Testing the new required-field validation surfaced a pre-existing latent
bug, not introduced by this cycle: `onOk={() => void submit()}` discarded
the promise returned by `submit()`. When `form.validateFields()` rejects —
which it already did correctly, with antd rendering the error inline for
the operator — the discarded rejection surfaced as an unhandled promise
rejection in the test runner. This predates this cycle (the same `onOk`
wiring existed for the three original presets) and was only caught now
because the new custom-rate validation path was the first one exercised by
a test that deliberately submits an invalid value.

Fixed with:

```tsx
onOk={() => {
  submit().catch(() => {});
}}
```

One line. No visible behavior change for the operator — antd's own
`Form.Item` error text was already rendering — the fix only stops the
dangling rejection. Confirmed by reading the diff directly (see §1); this
is a bug fix, not part of the new feature's design.

---

## 6. Corrections

None. No prior build-log entry described crawl-speed presets incorrectly;
build-log 0017 remains accurate.

---

## 7. Explicitly not done

* No pre-crawl duration-estimate/ETA math beyond the single advisory
  threshold check — the live ETA (`JobTelemetry.eta_seconds`) remains the
  only real estimate, and this cycle does not duplicate its logic.
* No mid-crawl rate adjustment.
* No per-host adaptive rate.
* No backoff-on-429.
* No pre-flight robots.txt preview.
* No auto-snapping a custom rate into a matching preset (e.g., 1.0 rps
  entered under "custom" stays custom, it does not silently become Polite).
* No persisted custom-value template — `CRAWL_SPEEDS` remains a static
  array; there is no mechanism to save a custom rate/concurrency pair for
  reuse across crawls.

---

## 8. Handoffs

A concurrent session is modifying many files under GSC account management,
job telemetry, and `tool.py` (visible in `git status` at the top of this
session and in the two most recent commits touching
`LiveCrawlModal.tsx`'s history — `b3d7105` and `4cee3b8`, both GSC-related,
neither touching the speed control). Not resolved by this cycle, per
standing practice this session: flagged, not fixed. No backend handoff is
needed for this feature specifically, since no backend or schema change was
made.

---

## 9. Files changed

* `rankuno-ui/src/components/layout/LiveCrawlModal.tsx`
* `rankuno-ui/src/components/layout/LiveCrawlModal.test.tsx`

## 10. Follow-ups

* Independently re-run the full `npm test` (26 files) and `npm run build`
  once the concurrent GSC session settles, to confirm the 284-passed /
  3-pre-existing-unhandled-rejection count this entry could not
  independently re-verify without spending the full suite's runtime.
* No golden-corpus or backend follow-up — this cycle touched no `src/`
  Python file.
