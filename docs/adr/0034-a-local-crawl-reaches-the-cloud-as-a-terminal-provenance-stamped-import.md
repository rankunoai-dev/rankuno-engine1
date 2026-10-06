# ADR 0034: A local crawl reaches the cloud as a terminal, provenance-stamped import

- **Status**: Accepted
- **Date**: 2026-10-07
- **Deciders**: AI Lead, Lead AI Systems Engineer (user approved the Step 3 plan; security
  audit PASS WITH CONDITIONS 1-10)

---

## Context

Large crawls now run on the workstation (ADR 0032), because the Railway container's memory cannot
hold them. Their results stay in the workstation's `.jobs/` folder, and the user wanted one of them
(groundsguys.com, 8,238 pages) to show up in the cloud org as a normal job.

ADR 0032 rules out the obvious shortcut. A local process must never reach the shared database,
because the local server's startup orphan recovery would mark every in-flight cloud job `FAILED`.
So the copy has to travel the way any client's data does: over the authenticated HTTPS API, into
the caller's own org, and through validation that treats the bundle as hostile.

What was measured before deciding:

- groundsguys `result.json` is 19.2 MB and gzips to 0.70 MB. The largest local result is 93 MB
  (100,687 pages) and gzips to 3.3 MiB.
- On the server path (streamed inflate, `model_validate_json`, URL audit, `model_dump_json`), the
  93 MB result peaked at **~1.1 GiB** working set above baseline in 6.5 to 11.6 s on the
  development workstation. groundsguys peaked at 139 MiB in 0.7 s.
- In all 1,333 local results, every URL the crawler fetched or followed is http(s) with a host.
  10 results carry a `canonical_url` like `www.http://infosys.com/...`. That field is the site's
  own claim and is recorded verbatim.

## Decision

**A CLI, `scripts/push_job_to_cloud.py`, uploads one finished local job as a versioned gzip
bundle to `POST /api/v1/jobs/import`. The server stores it as an already-terminal job in the
caller's org, stamped with where it came from.**

1. **Identity comes from the server.**
   - The org and the `imported_by` operator come from the verified session.
   - The job id comes from the store.
   - `JobImportBundle` is `extra="forbid"` and has no field that could name an org, a job id,
     the `has_*` flags or telemetry. The server rebuilds telemetry from the result.
   - `tool_name` and `facet_id` are fixed to `seo.page_classifier`.
2. **Limits are Settings.**
   - 32 MiB compressed, checked on `Content-Length` and on the stream before buffering.
   - 128 MiB inflated, enforced *while* inflating, so a gzip bomb stops at the cap.
   - One import at a time per process: a busy server answers 429 instead of queueing.
   - 6 imports per operator per hour, burst 2.
   - A 422 lists at most 10 failing locations and never a value.
3. **URLs.**
   - Every field the crawler fetched, followed or was told to use must be http(s) with a host.
     The set is `STRICT_URL_FIELDS`, and a test fails if a new URL-named string field is not
     classified.
   - `canonical_url` is refused only for a real non-http scheme, read the way a browser reads
     it: tabs and newlines are deleted and C0 controls stripped, so `java\tscript:` is still
     `javascript:`.
   - A missing scheme, or a dotted prefix such as `www.http`, is accepted as text. No browser
     executes a dotted scheme, and none of the dangerous ones contains a dot.
   - Any failure refuses the whole bundle. A crawl that was silently rewritten would no longer be
     the crawl that ran.
4. **Persistence is `JobStore.import_terminal`, never `create()`/`finish()`.**
   - One transaction inserts the `jobs` row already `succeeded` or `partial`, with
     `has_result=true`, plus its `job_payloads` row.
   - There is no budget lock and no ledger row: an import spends nothing.
   - There is no disk fallback. A Railway disk write would vanish on the next redeploy after the
     client was told it landed, so an open circuit or a DB error is a 503.
   - The job is never queued or running, so `recover_orphans` cannot touch it.
5. **The import is idempotent within an org.**
   - The key is `(org_id, source_instance_id, source_job_id)`, enforced by migration 0009's
     partial unique index. `bundle_sha256` is taken over the *inflated* bytes, because gzip
     headers carry a timestamp.
   - The CLI encodes deterministically (gzip `mtime=0`), so a retry resends identical bytes.
   - The same key with the same hash returns 200 `duplicate: true`. A different hash returns 409.
6. **Provenance is a typed field.** `JobRecord.provenance: JobProvenance | None` is stored in
   nine nullable columns, not inside `request`. The source instance id is a random
   `li-<24 hex>` kept in `.jobs/.instance-id`, never a hostname. No path appears anywhere.
7. **Imported jobs cannot be re-run in the cloud.** `retry` and `resume` answer 409.
   - Re-running would make the cloud crawl, and spend on, a site whose settings it never
     validated at admission.
   - `reparse` stays allowed: it is offline and goes through `create()`, so it carries the
     usual reparse charge.
8. **The CLI keeps credentials out of everything persistent.**
   - The password is read only by `getpass`, and only when stdin is a terminal.
   - The session token lives in memory and is dropped at exit. It is valid for 12 hours.
   - `--cloud-url` or `CLOUD_IMPORT_BASE_URL` must be https (http only to loopback), and any
     redirect is a hard error.
   - The CLI constructs `DiskJobStore` directly, so no database setting can redirect it.

## Consequences

- An imported job behaves like a native one for the result view, `urls.xlsx`, `urls.pdf`, the
  audit workbook deliverable, URL-list sources, reparse and the Screaming Frog and GSC uploads.
- It has no checkpoint, so `/checkpoint` answers 404. Masterfiles refuse it with 409, exactly as
  they refuse every native crawl.
- The same local job imported into two orgs becomes two jobs. One org can never learn of the
  other's copy.

## Explicitly not done

- **Memory accounting.** Import memory is **not counted** by the ADR 0031 crawl memory budget.
  Concurrency 1 and the 128 MiB cap bound it at roughly 1.1 to 1.5 GiB. The 128 MiB figure is
  extrapolated, not measured.
- **What v1 bundles carry.** No checkpoint, reconciliation or performance report travels in v1.
- **UI work** goes to ui-engineer:
  - a "Copy to cloud" button, deferred because it would need an ADR 0032 amendment;
  - the "Imported from local" badge;
  - hiding Resume and Retry on imported jobs;
  - a shared `safeHref()` at the 8 link sites;
  - a job deep link.

  Until `safeHref()` lands, the URL audit is the only defence for imported data.
- **Spreadsheet formula injection.** Formula neutralisation in workbook and CSV exports is a
  separate known gap (F7), and imports widen who can supply that text.
