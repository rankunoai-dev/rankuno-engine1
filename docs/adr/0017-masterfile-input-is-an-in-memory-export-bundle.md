# ADR 0017: A masterfile is built from an in-memory export bundle, and one route resolves both job namespaces

- **Status**: Accepted
- **Date**: 2026-09-27
- **Deciders**: AI Lead, Lead AI Systems Engineer

---

## Context

The 21 masterfile services (cycles 0104–0105) were written against a directory of
loose Screaming Frog CSVs: each service joined `self.sf_export_dir / filename` and
read it. Nothing in this repository has ever produced such a directory.

- A native engine crawl stores a JSON result and a `JobRecord`. `DiskJobStore` is
  **flat** — `_record_path()` is `root/{job_id}.json` (`state_store.py:365`) — so
  the `root/{job_id}/sf_export/` path the API route computed cannot exist for any
  id.
- A Screaming Frog worker job (ADR 0015) uploads **one zip**, which is validated
  against `ALLOWED_BUNDLE_FILENAMES` and then stored **encrypted at rest** and
  never extracted (ADR 0015 condition 11).

So `POST /jobs/{job_id}/masterfile/{service_slug}` had no reachable input, and in
fact had never succeeded for any request (build-log 0107 §4). Two options were
open: make the directory real by extracting each bundle, or make the services
source-agnostic.

There is also a namespace problem. This platform has two job stores — engine
crawls in `ApiState.store`, Screaming Frog dispatches in
`ApiState.worker_dispatch_store` — and the deliverable the build produces lives in
a third (`ApiState.deliverable_store`). A UI that must decide which namespace an
id belongs to before it can ask a question about it has to know something it does
not know.

## Decision

**1. A masterfile is built from a `MasterfileSource`, and the canonical source is
a zip held in memory.**

`src/modules/seo/deliverables/masterfile_source.py` defines a `MasterfileSource`
`Protocol` — a set of export CSVs addressed by filename — with
`DirectoryMasterfileSource` (a folder, for the CLI and for tests) and
`BundleMasterfileSource` (a zip, for the worker path). `MasterfileService.__init__`
accepts `MasterfileSource | Path | str`, wrapping a path for the caller so every
existing directory call site is unchanged. Services read via `self._read_csv(name)`
and enumerate via `self._csv_names()`; no service joins a path, because a zip in
memory has no path to join.

**2. A decrypted bundle is never written to disk.** `_bundle.open_bundle_bytes()`
opens the plaintext through the same `_ZipBundle` pre-flight and byte metering the
on-disk path uses — traversal names, symlinks, duplicate basenames, zip bombs,
encrypted and exotically compressed members are refused by the code that already
refuses them, not by a second reader. The plaintext lives in one route closure for
the duration of the build.

**3. `POST /jobs/{job_id}/masterfile/{service_slug}` resolves both job
namespaces**, engine store first. A native crawl id is refused `409` with a message
saying why and naming the routes that do apply; a Screaming Frog worker id is
built from its uploaded bundle. The caller has exactly one id to send and one — the
returned deliverable id — to poll.

**4. Three failure modes get three statuses**, because one message to parse is not
an API:

| Status | Meaning |
| :--- | :--- |
| `409` | No bundle was ever uploaded (`bundle_size_bytes is None`, set only by `mark_uploaded`), or the id is a native engine crawl |
| `410` | A bundle existed and its retention window has closed. `read_upload` filters on `expires_at` in SQL, so the blob is not readable; that is *gone*, not missing, and a `404` would send a caller looking for a job that is right there |
| `503` | The dispatch store is unreachable — which is also what an unknown id becomes when the second namespace cannot be consulted at all |
| `500` | The blob is present and cannot be decrypted, naming `WORKER_BUNDLE_ENCRYPTION_SECRET`, exactly as `GET /workers/jobs/{id}/bundle` already does |

**5. This supersedes the implicit `sf_export/` directory convention.** No code
should create, look for, or document such a directory. It was never written by
anything.

## Alternatives considered

1. **Extract each bundle to `sf_export/` on demand and keep the path-shaped
   service signature.** Rejected: it writes decrypted client data to disk, which is
   precisely what ADR 0015 condition 11 encrypts it to prevent, and it adds a
   temporary-directory lifecycle (cleanup on crash, on cancellation, on Windows
   file locks) to every build. The seam is cheaper than the cleanup.
2. **A second route over the dispatch store,
   `POST /workers/jobs/{id}/masterfile/{slug}`.** Rejected: it pushes namespace
   resolution to the caller, and the dashboard does not know which store an id came
   from. The cost of the decision taken is that an unreachable dispatch store turns
   an unknown id into a `503` rather than a `404`; that is documented in the route's
   docstring.
3. **Make the services read `AuditDataset` instead of CSVs**, reusing
   `screaming_frog_adapter.py`. Rejected for now, not on principle: `AuditDataset`
   deliberately retains only a page spine, `{IssueId → URL set}` and coverage (ADR
   0011 D4), and a masterfile needs per-row export columns the dataset discards.
   Revisit if the masterfile output contract narrows.
4. **Build masterfiles only from the `POST /deliverables/from-screaming-frog`
   upload path** and drop the per-job route. Rejected: it requires the operator to
   still hold the zip a worker has already uploaded.

## Consequences

**Positive**

- The route works at all, for the first time.
- At-rest encryption is preserved; no plaintext export ever reaches the filesystem.
- One archive reader, so every zip defence applies to both sources by construction.
- The CLI and all 21 existing service tests kept working without edits, because a
  `Path` is still accepted.

**Negative**

- A whole bundle is held in memory for the duration of a build, bounded only by
  `worker_upload_max_bytes`. This is consistent with the existing "a crawl holds
  its graph in RAM" posture (CLAUDE.md §8) and is not an improvement on it.
- Two stores are consulted on every masterfile request, so the route's failure
  surface is the union of both.
- `410` is a new status for this API family; a client that treats any non-2xx as
  "retry" will retry an expired bundle forever.

**What this ADR does not decide**

It says nothing about *which* CSVs a service should ask for. 37 of the 49 filenames
the services currently request do not exist in a real export (build-log 0107 §5), 13
of 21 services render an empty workbook, and `masterfile_overview_report.py:235`
crashes on any real bundle. Those are open defects, not consequences of this
decision, and they are tracked in build-log 0107 §6 and §8.

**Follow-up**

- Correcting the service filenames against `contracts/catalogue.py`, service by
  service, each proved by a bundle-backed test.
- A masterfile UI. `/masterfiles/available` is served and nothing consumes it.
