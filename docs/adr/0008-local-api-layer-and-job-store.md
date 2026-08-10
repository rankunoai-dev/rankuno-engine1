# ADR 0008 — A local API layer and a domain-agnostic job store

* **Status**: Accepted
* **Date**: 2026-08-10
* **Supersedes**: nothing
* **Related**: ADR 0003 (job-level governance), ADR 0004 (local-first deployment)

## Context

The React UI (`rankuno-ui/`) read crawl results from JSON files bundled at build
time. The engine and the interface agreed on *shape* — `schema.ts` is generated
from the Pydantic models and the quality gate fails if it goes stale — but there
was no runtime connection between them. Producing a new view of a site meant
running a script by hand, re-running the fixture exporter, and reloading.

Three constraints shaped the design:

1. A 20k-page crawl takes minutes to hours. It cannot complete inside an HTTP
   request, so the request that starts a crawl and the request that reads its
   result must be different requests.
2. `core/` may not import from `modules/` (CLAUDE.md §1). A job store typed
   against `PageClassificationOutput` would be a `core -> modules` import.
3. `PageClassificationTool.execute()` is synchronous and calls `asyncio.run()`
   internally. It cannot be awaited.

## Decision

**Add a fourth layer, `src/api/`, outermost.** Dependencies remain inward-only:
`api -> modules -> integrations -> core`. Nothing below imports from it.

**The API implements no safety control of its own.** SSRF validation, robots
compliance, per-host throttling, guardrails and audit logging are all inherited
by calling `BaseTool.run()`. The URL check on `POST /jobs` is not a second guard
but the same `UrlSafetyPolicy` run *early*, so a bad URL is a `400` the operator
sees rather than a job that fails a moment later.

**`src/core/state_store.py` is domain-agnostic.** A job carries an opaque
`request` mapping in and an opaque `result` mapping out. The API layer owns the
domain types and validates at its own boundary. This satisfies the dependency
rule, and it means the same store will hold PPC and research jobs unmodified.

**Storage is one JSON file per job, written atomically**, with metadata and
result blob in separate files. Metadata must be listable without reading a 16 MB
result. Writes go to a temporary file in the destination directory and are moved
into place with `os.replace`, so a killed process leaves either the old record or
the new one, never a half-written one.

**Crawls run on a worker thread** via `asyncio.to_thread`, not FastAPI's
`BackgroundTasks`. `BackgroundTasks` runs on the event loop; a crawl there would
block every other request for its whole duration — including the `GET /jobs/{id}`
polls the UI depends on.

**At most three concurrent crawls**, then `429`. The bound is memory, not CPU:
each in-flight crawl holds its whole graph including page HTML.

**`serve()` binds `127.0.0.1`.** There is no authentication and the server
fetches arbitrary URLs on request; on a routable interface it is an open proxy.

**Orphan recovery runs at startup.** A job left `RUNNING` by a killed process has
no worker any more and nothing will ever move it. It is marked `FAILED`, which is
honest — there is no crawl checkpointing to resume from (CLAUDE.md §8).

## Consequences

**Positive**

* The UI reaches live crawls. `App.tsx` selects `HttpAdapter` or `MockAdapter`
  behind the `CrawlDataAdapter` interface that already existed for this purpose.
* Jobs survive a server restart.
* `fastapi`/`uvicorn` are an `api` extra, not core dependencies — importing this
  package as a library does not drag in a web server. `bootstrap.ps1` installs
  the extra by default so `mypy --strict` over the whole tree still passes on a
  fresh clone.

**Negative / accepted**

* **Single process only.** The concurrency counter is in-process and the store's
  lock is a `threading.Lock`; two servers sharing a job directory would
  interleave writes. This is the same limitation the rate limiter and cost ledger
  already carry, accepted for the same reason (ADR 0004).
* **No progress fraction.** One `BaseTool.run()` is one atomic crawl job (ADR
  0003) and there is no progress hook, so the API reports `queued`/`running`/
  terminal and the UI shows an indeterminate indicator. A percentage would be
  invented. Adding real progress means threading a callback through discovery,
  which is deliberately deferred rather than faked.
* **No authentication.** Acceptable only because of the loopback bind. This
  becomes blocking before any hosted deployment.
