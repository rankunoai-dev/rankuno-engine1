# Cycle 0107: The masterfile route had never succeeded; the bundle is now read in memory

- **Date**: 2026-09-27
- **Scope**: `POST /jobs/{job_id}/masterfile/{service_slug}` rebuilt on a `MasterfileSource` seam that reads a decrypted Screaming Frog bundle from memory, resolving the id against both job namespaces; all 21 services rewired off `sf_export_dir`.
- **Commit**: uncommitted at time of writing
- **Quality gate**: see §1; the session-wide gate figures are in cycle 0110
- **Session thread**: this is entry 2 of 6 — see [0106 §0](0106-a-pattern-that-never-reaches-the-form.md)
- **ADR**: [0017](../adr/0017-masterfile-input-is-an-in-memory-export-bundle.md)

## 1. Gate results

The operator's full-gate run was in flight while this entry was written and is
reported in cycle 0110. Re-running `pytest` here would have overwritten the
`.coverage` file that run was using, so the numbers below were obtained
statically and each one is reproducible without executing the suite.

| Measurement | Value | How it was obtained |
| :--- | :--- | :--- |
| `tests/api/test_masterfile_endpoints.py` | 14 tests, new file | `grep -c "def test_"` |
| `tests/modules/seo/deliverables/test_masterfile_source.py` | 21 tests, new file | same |
| `tests/modules/seo/deliverables/test_masterfile_bundle_build.py` | 7 tests, new file | same |
| New tests this cycle | **42** | 14 + 21 + 7 |
| `tests/api/` masterfile coverage before this cycle | **0 tests** | no file matched `*masterfile*` under `tests/api/` at `HEAD` |
| Service test files that write CSV bytes at all | **2 of 21** (`meta_description`, `response_codes`) | `grep -c "write_text\|to_csv"` over `tests/modules/seo/deliverables/test_masterfile_*.py` |
| Registry services | 21 | parsed from `masterfile_registry.py` |
| `ISSUE_CATALOGUE` | 110 rows, 95 distinct `sf_sources` filenames | imported and counted |
| Distinct CSV filenames the 21 services ask for | **49** | regex over `src/modules/seo/deliverables/masterfile_*.py` |
| …of those, not in `ALLOWED_BUNDLE_FILENAMES` (95 catalogue names + spine) | **37** | set difference, printed in full in §5 |

## 2. What landed

**`masterfile_source.py`** (new, 222 lines). A `MasterfileSource` `Protocol` — "a
set of Screaming Frog export CSVs addressed by filename" — with two
implementations: `DirectoryMasterfileSource` for a folder of loose CSVs, and
`BundleMasterfileSource` for a zip. Two rules the implementations share, because
a masterfile is a *report* and a missing input must read as neither "no issues
found" nor a crash: **absent is `None`**, and **unreadable is one error type**,
`MasterfileSourceError(ValueError)`, which `build_runner.run_masterfile` already
reports as a failed build without importing it by name.

**`_bundle.open_bundle_bytes(data, display_name)`** (new). Opens an in-memory
zip through the existing `_ZipBundle` pre-flight, so traversal names, symlinks,
duplicate basenames, zip bombs, encrypted and exotically compressed members are
refused by the code that already refuses them for on-disk bundles — not by a
second zip reader. `_ZipBundle.__init__` now takes `Path | IO[bytes]` plus a
display name, and `Bundle` gained `names()` because Screaming Frog's
custom-extraction export is one file *per configured extractor*, so that set is
knowable only from the bundle.

**`MasterfileService.__init__` takes `source: MasterfileSource | Path | str`.** A
`Path` or `str` is wrapped in a `DirectoryMasterfileSource` for the caller, so
`scripts/build_deliverable.py` and all 21 existing service tests keep working
unchanged. Subclasses read through `self._read_csv(filename)` and discover
dynamic names through `self._csv_names()`; neither joins a path, because a
source may be a zip in memory where there is no path to join.

**The route resolves both job namespaces.** `job_id` is looked up in
`state.store` (native engine crawls) first and then, through
`human_owned_job()`, in `state.worker_dispatch_store` (ADR 0015 Screaming Frog
worker jobs). A native crawl id is refused with a `409` that says why — it
produces a page-intelligence result, not CSVs — and names the two routes that do
apply. A worker job's bundle is read, decrypted on a worker thread and handed to
the build as bytes. New statuses: **410** when the retention window has closed
(`read_upload` filters on `expires_at` in SQL, so the blob is simply not
readable; that is *gone*, not missing, and a `404` would send a caller looking
for a job that is right there), and **503** when the dispatch store is
unreachable.

**Nothing is ever written to disk.** The plaintext bundle lives in one closure —
`source_factory=lambda: source_for_bundle_bytes(payload, job_id)` — for as long
as the build runs. Extracting it to a plaintext CSV directory to satisfy the old
path-shaped signature would have undone ADR 0015 condition 11's at-rest
encryption, which is the reason the seam exists at all.

## 3. Design decisions

**One route over two namespaces, rather than a second route.** The UI has one id
per crawl and polls one deliverable id. A `/workers/jobs/{id}/masterfile/{slug}`
sibling would have made the caller decide which namespace an id belongs to
before it could ask a question about it, and the dashboard does not know. The
cost is that an unknown id becomes a `503` rather than a `404` when the second
namespace cannot be consulted at all; that is stated in the route's own
docstring.

**Org scoping before refusal.** The native-crawl `409` fires only after
`org_scoped_or_404`, so the route cannot be used to probe which ids exist in
another organization. Same shape as `get_job`/`get_result`.

**`MasterfileSource` as a `Protocol`, not an ABC.** `deliverables/` may not
import `page_classifier` (ADR 0011 d.1) and the services must stay unaware of
where bytes come from. A `Protocol` keeps the dependency direction one-way and
lets a test pass a hand-built stand-in with two methods.

**`read_csv_safe` moved, not copied.** It now lives in `masterfile_source.py` and
is re-exported from `masterfile_base.py`, so no call site changed and there is
exactly one CSV reader.

## 4. Bugs found and fixed

**The route had never succeeded for any input, for two independent reasons.**

1. It computed `state.store.root / job_id / "sf_export"` and returned `409` if
   that directory did not exist. `DiskJobStore` is a **flat** store —
   `_record_path()` is `self._root / f"{job_id}.json"` (`state_store.py:365-366`)
   — so `root/{job_id}/` is never a directory, and nothing anywhere in this
   repository has ever written an `sf_export/` folder. The branch was
   unsatisfiable for every id, on every machine.
2. Before that could even be reached it called
   `state.deliverable_store.read_result(job_id)` — a *crawl* id against the
   *deliverable* store — purely to compose a label. On the only path where the
   directory check could have passed, this would have raised and returned `500`.

Both are now gone: there is no path construction, and the label is built from
`job.envelope.seed_url`.

**`read_csv_safe` opened files as bare `utf-8`.** Screaming Frog writes its CSVs
with a UTF-8 BOM, which bare `utf-8` leaves glued to the first header cell as
`﻿Address`. `gc()` then cannot find `Address`, the service degrades
gracefully, and the operator gets an empty report with no error. The default is
now `utf-8-sig`, which reads BOM-less UTF-8 identically and is therefore strictly
more tolerant than what it replaced. This defect could only ever appear on a
**real export**: every test used hand-written ASCII fixtures, so the suite could
not have caught it no matter how many assertions it made.

**Decryption failure was indistinguishable from a missing bundle.** Now `500`
with the setting named (`WORKER_BUNDLE_ENCRYPTION_SECRET` missing or rotated),
separate from `409` (never uploaded) and `410` (expired).

## 5. Corrections

### 5.1 Commit `0d26e26` — "Complete RAE masterfile parity — all 21 export services + API + UI"

That title is false, and so is build-log `0105-masterfile-milestone2.md`'s "Phase
1 is now feature-complete: all 21 masterfile services shipping and tested" and
its claim of a "Green Gate". Neither is edited here; both are corrected here.
Measured against real Screaming Frog 19.4 exports:

| Claim | Measured |
| :--- | :--- |
| 21 services shipping | 21 classes exist and are registered. **13 of 21 render an empty workbook** against a real export bundle; the 6 that produce data produce partial data |
| "all … tested" | 19 of 21 service test files write **zero CSV bytes**. They point the service at an empty `tempfile.TemporaryDirectory()` and assert `isinstance(result, bytes)` and `len(result) > 0` — which an empty openpyxl workbook satisfies. Independently reproduced here: only `test_masterfile_meta_description.py` and `test_masterfile_response_codes.py` write any CSV content at all |
| "API" | `POST /jobs/{id}/masterfile/{slug}` had never succeeded for any input (§4) |
| Filenames read from a Screaming Frog export | **37 of the 49** distinct CSV names the services request are not in `ALLOWED_BUNDLE_FILENAMES` (the 95 catalogue names plus the spine), and were apparently invented from the service slug: `masterfile_page_titles.py` asks for `title_missing.csv` / `title_duplicate.csv` / `title_too_long.csv` / `title_too_short.csv`, names present in neither Screaming Frog nor RAE. Verified here by set difference, not by memory; the full list is in §5.2 |
| `overview_report` aggregates 36 issue CSVs into 4 sheets | It **crashes** on any real bundle: `masterfile_overview_report.py:235` calls `wb.create_sheet("Notes/Recommendations")`, and openpyxl raises `ValueError: Invalid character / found in sheet title`. Unconditional. `sanitize_sheet_name()` already exists at `masterfile_base.py:164` and is simply never called. **Still unfixed** — see §6 |
| An actionable deliverable | Every multi-file service flattens its inputs into a URL list with **no column naming which issue applied**, so a reader cannot tell why a URL is in the sheet. RAE's equivalent is 18 columns |

There are **three competing filename vocabularies** in this repository and only
one is correct: `src/modules/seo/contracts/catalogue.py` (95 names, the
spelling real exports use). The second is `export_manifest.py`'s CLI-argument
transform (corrected in cycle 0108), and the third is the invented set inside
the masterfile services.

### 5.2 The 37 names, with two caveats stated rather than smoothed

The reported figure was "37 of 49 CSV filenames the services request cannot
exist in a real export". The set difference reproduces 37 of 49 exactly. Two
honest qualifications:

- `search_console_all.csv` and `analytics_all.csv` **are** real Screaming Frog
  export names when the crawl was configured with Search Console / GA4 API
  access. They are still unreachable here, because `ALLOWED_BUNDLE_FILENAMES`
  does not admit them and the worker's zip therefore cannot carry them — so the
  enrichment those two feed is silently absent rather than misnamed. That is a
  different defect with the same symptom.
- `internal_all.csv` is the spine and is correctly named; it is not in the 37.

The other 34 are slug-derived inventions (`title_*.csv`, `security_ssl.csv`,
`pagination_missing.csv`, `content_issues_thin.csv`, and so on).

### 5.3 What was *not* wrong

`0105`'s description of the registry pattern (lazy import paths, no
service-to-service imports) is accurate, and so is its account of the
formula-injection guards (`safe_cell` / `truncate_cell`). The defect is not that
nothing was built; it is that "complete" was claimed for something that had never
been run against its actual input.

## 6. Explicitly not done

- **13 services still render an empty workbook against a real bundle, and 1 still
  crashes.** This cycle fixed how a service *gets* its CSVs; it did not fix
  *which* CSVs a service asks for. The `overview_report` crash at
  `masterfile_overview_report.py:235` is one unconditional call to an existing
  helper away from being fixed and was deliberately left for its own cycle, with
  its own test against a real bundle, rather than patched blind during a gate run.
- **No service reads a rulebook.** `rulebook_path` is accepted and held.
- **No issue-provenance column.** The output of a multi-file service still cannot
  say which issue put a URL in the sheet, so it is not yet an actionable
  deliverable regardless of whether the workbook is populated.
- **The 19 empty-assertion test files were not rewritten.** Two new test files
  (`test_masterfile_source.py`, `test_masterfile_bundle_build.py`) do read real
  CSV content, and `test_masterfile_endpoints.py` covers the route. The other 19
  still assert `len(result) > 0` against an empty directory and will still pass
  when their service is broken.
- **No UI calls this route.** There is no masterfile screen; `/masterfiles/available`
  is served and nothing consumes it.
- **`PostgresWorkerDispatchStore.read_upload` is still only exercised against an
  in-memory fake cursor** (unchanged from build-log 0098); `psycopg` is not
  installed in the local venv, so the `410` path's SQL `expires_at` filter is
  covered by a fake, not by a database.

## 7. Files changed

| File | Change |
| :--- | :--- |
| `src/modules/seo/deliverables/masterfile_source.py` | new, 222 lines — `MasterfileSource`, `DirectoryMasterfileSource`, `BundleMasterfileSource`, `MasterfileSourceError`, `read_csv_safe` (now `utf-8-sig`) |
| `src/modules/seo/deliverables/_bundle.py` | +55/-6 — `open_bundle_bytes`, `Bundle.names()`, `_ZipBundle` from `Path | IO[bytes]` |
| `src/modules/seo/deliverables/masterfile_base.py` | +44/-39 — `source` replaces `sf_export_dir`; `_read_csv`/`_csv_names`; `read_csv_safe` re-exported |
| `src/modules/seo/deliverables/masterfile_*.py` (21 services) | rewired off path joins onto `self._read_csv()` |
| `src/modules/seo/deliverables/masterfile_registry.py` | +34/-13 — construction takes a source |
| `src/modules/seo/deliverables/build_runner.py` | +25/-9 — `run_masterfile` takes a source factory and closes the source |
| `src/api/deliverables_routes.py` | +186/-67 — dual-namespace resolution, `_start_masterfile`, `_reject_engine_job`, `_screaming_frog_bundle_bytes` (409/410/500/503) |
| `tests/api/test_masterfile_endpoints.py` | new, 14 tests |
| `tests/modules/seo/deliverables/test_masterfile_source.py` | new, 21 tests |
| `tests/modules/seo/deliverables/test_masterfile_bundle_build.py` | new, 7 tests — the first masterfile test that builds from a bundle with real CSV content |
| `docs/adr/0017-masterfile-input-is-an-in-memory-export-bundle.md` | new |

## 8. Follow-ups

1. Call `sanitize_sheet_name()` at `masterfile_overview_report.py:235` and pin it
   with a test that builds from a real bundle. One line; currently every
   `overview_report` request against a real bundle is a `500`.
2. Replace the 37 invented filenames with catalogue names, service by service,
   each change proved by a bundle-backed test. Until then "21 services" means 21
   classes, not 21 working reports.
3. Add an issue-provenance column to every multi-file service.
4. Rewrite the 19 empty-directory test files to assert on content. A test that
   cannot fail is worse than a missing test, because it is counted.
5. Admit `search_console_all.csv` and `analytics_all.csv` to the bundle
   allow-list and the export manifest, or stop reading them in the services.
6. Four code comments cite this work as "cycle 0104" / "build-log 0104", which is
   an existing committed entry. See the numbering note in the index and
   §8 of cycle 0110.
