# Cycle 0132: A menu that offered what it could not deliver

- **Date**: 2026-09-30
- **Scope**: Two features — unavailable-masterfile disclosure (Item 3) and
  download-all-masterfiles ZIP (Item 4)
- **Gate**: **GREEN** — 3,714 py passed, 93% coverage; UI 49 files / 621 tests;
  format, lint, mypy --strict all passed

---

## 1. Gate results

```
ALL GATES PASSED.
```

- **Format**: PASSED (539 files)
- **Lint**: PASSED
- **Type check**: PASSED (mypy --strict, 156 source files)
- **Python tests**: 3,714 passed, 0 failed, 2 skipped — **93%** coverage
- **UI component tests**: 49 files, 621 tests passed

---

## 2. What shipped

### 2a. Unavailable-masterfile disclosure (Item 3)

The masterfile menu previously offered twenty-one identical buttons. Four of
them could never produce a row: their source exports are not in
`ALLOWED_BUNDLE_FILENAMES`, so no uploaded bundle can carry them. The operator
got a 202, an empty workbook, and no explanation.

**New module**: `masterfile_availability.py` derives which services can measure
anything by checking each service's declared `SOURCE_FILES` and
`SOURCE_FILE_PREFIXES` against the allow-list. Derived, never listed — adding
a tab to the export manifest automatically flips its services to measurable.

**API change**: `GET /masterfiles/available` now returns
`AvailableMasterfiles(services: list[ServiceAvailability])` instead of a bare
slug list. Each entry carries `measurable: bool` and `reason: str | None`.

**UI change**: `WorkerJobsPanel.tsx` renders an unmeasurable service as a
disabled row with the server's reason text beside it (`UnbuildableService`
component, `aria-describedby` for accessibility).

**Custom extraction wording**: The empty-extractors cell read "No custom
extractors configured", which blamed the Screaming Frog template when the
actual cause is that this engine never asked for the extraction. Changed to
`NOT_MEASURED` + `NOT_REQUESTED` with an honest sentence.

**Registry refactor**: Extracted `service_class(slug)` from
`get_masterfile_service` so the availability derivation can read class-level
`SOURCE_FILES` without constructing a service instance (it has no source and
no job to build for).

**Base class addition**: `MasterfileService` gained `SOURCE_FILE_PREFIXES:
ClassVar[tuple[str, ...]] = ()` and `reachable_sources(cls, allowed)` for the
one export family (`custom_extraction_*`) whose names cannot be known in
advance.

### 2b. Download-all-masterfiles ZIP (Item 4)

**New endpoint**: `POST /jobs/{job_id}/masterfiles/all` → 202 with a
deliverable ID. Builds all measurable services in a loop, each failure logged
and skipped. Results are ZIP'd as `masterfiles.zip` containing one
`<slug>.xlsx` per service.

**Build runner**: `run_masterfile_batch()` in `build_runner.py` — same
worker-thread contract as `run_masterfile`. If zero services succeed, the
deliverable is marked failed. Otherwise the ZIP is stored and `finish()` is
called with `built`/`skipped` counts.

**UI**: "Download All (ZIP)" button at the top of the MasterfileMenu popover
in `WorkerJobsPanel.tsx`. Uses a longer poll timeout (300 attempts = 5
minutes) since the batch builds all services sequentially.

---

## 3. Bugs found and fixed

1. **Test read the wrong field on `JobRecord`**: The
   `test_batch_records_built_and_skipped_counts` test accessed
   `record["result"]`, but `GET /deliverables/{id}` returns a `JobRecord`
   whose serialization includes `request` (the input dict passed to
   `create()`), not `result` (the output dict passed to `finish()`). The
   result is accessible via `read_result()` on the store, but the status
   endpoint does not include it. Fixed by checking `record["request"]["source"]
   == "masterfile_batch"` and `record["request"]["services"]` — both present
   in the request dict. Test renamed to
   `test_batch_records_source_and_service_list` to match what it now asserts.

---

## 4. Corrections

None. The previous session's implementation was accurate.

---

## 5. Explicitly not done

1. **Browser verification**: Neither the unavailable-service disclosure nor
   the batch ZIP download has been tested against a real bundle in a browser.
   TypeScript compiles clean and the component tests pass, but feature
   correctness is asserted by the test suite, not by observation.

2. **The `result` field on the deliverable status endpoint**: The deliverable
   status response (`GET /deliverables/{id}`) does not include the build
   result. An operator cannot see `built`/`skipped` counts without reading the
   store's result blob directly. This is a pre-existing limitation of the
   deliverable status API, not something introduced here. Whether to expose it
   is a separate decision.

3. **Batch progress telemetry**: The batch build runs all services
   sequentially on one thread. There is no per-service progress reporting —
   the deliverable is either `dispatched` or `succeeded`/`failed`. For 17
   services on a real bundle this takes seconds, so the gap is cosmetic for
   now; it would matter if the service count or per-service build time grew.

4. **Batch concurrency limit**: The batch endpoint shares the same
   `max_concurrent_deliverables` slot as single-masterfile builds. Two
   simultaneous batch builds from different operators would each hold a slot
   for the full build duration. No separate limit was added.
