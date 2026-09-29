# ADR 0022: Crawl job records, results, checkpoints, and homepage snapshots move to Postgres

- **Status**: Accepted
- **Date**: 2026-09-29
- **Deciders**: AI Lead, Lead AI Systems Engineer

---

## Context

Every crawl job in production runs through `DiskJobStore`
(`src/core/state_store.py`), which writes one JSON file per job — the record
itself, plus `.result.json`, `.checkpoint.json`, and `.homepage.html`
sidecars — under `.jobs/` on the API container's own filesystem. Railway
wipes that filesystem on every redeploy and every restart; `railway.toml`
has documented this as a known, unfixed gap since it was written. In
practice: a crawl in progress when a deploy lands is not merely
interrupted, it is *gone* — no record that it ever ran, no partial result,
nothing for an operator to recover.

A `PostgresJobStore` already existed (`src/core/postgres_store.py`) and was
already wired for `create()`/`get()`/`list_jobs()` against the real `jobs`
table, with a circuit breaker (`src/core/circuit_breaker.py`) and disk
fallback for resilience. But every other method — `mark_running`,
`update_telemetry`, `mark_failed`, `finish`, `read_result`,
`write_checkpoint`, `read_checkpoint`, `write_homepage`, `read_homepage` —
unconditionally delegated to the disk fallback regardless of circuit state.
So even where this store *was* used, a job's creation would survive a
redeploy and nothing else about it would. It was also never the default in
`create_app()` (`src/api/server.py`), so nothing used it at all.

Two further bugs surfaced while completing it, both worth recording because
they would have shipped invisibly:

1. `get()`/`list_jobs()`'s `SELECT` omitted the `label` column and never
   passed `label=` when constructing `JobRecord`, so a job's label was
   silently dropped on every read, even though `create()`'s `INSERT` never
   wrote it either.
2. `get()`/`list_jobs()` caught bare `Exception`, not the two psycopg error
   types the rest of the class narrows to. Once a `JobNotFoundError` for a
   genuinely missing job became a real code path (it wasn't, before — the
   method just built a plain `KeyError` that no route's
   `except JobNotFoundError:` would catch), that broad `except` would have
   swallowed it, recorded a spurious circuit-breaker failure, and — worse —
   silently produced a *different* answer from the disk fallback instead of
   a clean 404.

## Decision

1. **Postgres, not a Railway volume, for the large payloads too.** A
   volume would solve the redeploy problem for job data but leaves budgets
   and job state in two different failure domains, and the user's own
   framing for this cycle was explicit: no new infrastructure. `jobs`
   already lives in the same database as `org_configs` and `cost_ledger`;
   extending it costs a migration, not a new operational surface.

2. **A companion table, `job_payloads`, not three new columns on `jobs`.**
   `DiskJobStore` keeps the result/checkpoint/homepage blobs in separate
   sidecar files from the job record for one explicit reason
   (`state_store.py`'s own module docstring): `list_jobs()` must stay cheap,
   and it was cheap because listing jobs never had to skip past a 16 MB
   result. A companion table preserves that shape in Postgres — `get()`/
   `list_jobs()` never join it, and `SELECT` never has to name-and-skip
   columns it does not want. `job_payloads.job_id` is both primary key and
   foreign key (`ON DELETE CASCADE`, matching `jobs`'s existing children
   `cost_ledger` and `idempotency_keys`): a 1:1 row, nullable in all three
   payload columns, because most jobs carry only a subset of them.

3. **`finish()` is one Postgres transaction, not two ordered writes.**
   `DiskJobStore.finish()` writes the result blob *before* the metadata flag,
   specifically so a crash between the two writes leaves a job that looks
   unfinished (recoverable) rather than one that advertises a result that
   is not there. Postgres does not need that ordering trick: the
   `job_payloads` upsert and the `jobs` update happen inside one
   transaction, so they either both land or neither does. Real ACID
   guarantees replace the write-ordering convention, not just imitate it.

4. **`recover_orphans()` follows the circuit breaker, and that split is an
   accepted, not solved, gap.** With the circuit closed, it recovers
   `jobs` rows left `queued`/`running` in Postgres. With it open, it
   recovers whatever is on disk. A job created while the circuit was open
   and left running when the process died is picked up by the *next*
   disk-side call, not this one — the same store-selection split `create()`
   already makes for every write. A dual-store scan on every startup would
   close that gap completely, but at the cost of every restart paying for
   two full table/directory scans instead of one; deferred rather than
   built speculatively.

5. **`reconciliation` and `performance` sidecars stay disk-only. `.orgs`/
   `.operators` are untouched.** Neither is in scope for this cycle. The
   one thing this decision *does* fix for them: `PostgresJobStore` now
   overrides all four methods to delegate unconditionally to
   `fallback_store`, rather than leaving them unimplemented on the
   `JobStore` `Protocol`. A `Protocol`'s own method bodies are `...`, which
   is valid Python and returns `None` — so before this fix, wiring
   `PostgresJobStore` in as the default (this cycle's other change) would
   have made every reconciliation/performance write silently vanish, a
   regression this cycle would otherwise have introduced on data nobody
   asked it to touch.

6. **`create_app()` picks the store by whether Postgres looks configured,
   not by trying it and letting the circuit breaker learn.** A workstation
   with no Postgres installed (every local dev setup, this test suite's own
   default) would otherwise see `PostgresJobStore.create()` raise on every
   call until `CircuitBreaker.failure_threshold` (5) is reached before
   falling back — five real, visible failures on first boot for a store
   nobody configured. `PostgresSettings.is_configured()` short-circuits
   that: no `DATABASE_URL`/`POSTGRES_URL`/`DATABASE_PRIVATE_URL` and no
   explicit password means `_default_job_store()` returns a `DiskJobStore`
   outright, exactly as it did before this cycle. Once Postgres *is*
   configured, `PostgresJobStore`'s own circuit breaker still covers a
   transient outage by falling back to the same disk store.

## Alternatives considered

- **A Railway volume**, mounted at `.jobs/`. Rejected per the user's explicit
  "no new infrastructure" framing for this cycle, and it does not solve the
  multi-replica case the way a shared database does — ADR 0004's
  single-workstation posture for local dev is unaffected either way, but a
  future multi-replica cloud deployment would need Postgres (or something
  like it) regardless.
- **Three new columns directly on `jobs`** instead of a companion table.
  Rejected for the `list_jobs()` cost reason above — Postgres's own TOAST
  storage would keep a `SELECT` that names only the metadata columns cheap
  even with large values in the same row, but a companion table makes that
  cheapness a property of the schema, not an implementation detail a future
  `SELECT *` could quietly undo.
- **A dual-store scan in `recover_orphans()`** (both Postgres and disk, every
  startup, regardless of circuit state). Rejected for this cycle as
  disproportionate to the gap it closes — see decision 4 — and flagged as a
  residual limitation rather than solved speculatively.

## Consequences

- A crawl job's full lifecycle — creation, status, telemetry, its result,
  any checkpoint, its homepage snapshot — survives a Railway redeploy for
  the first time. `railway.toml`'s "known gap" comment about job loss on
  redeploy is now stale and should be removed in a follow-up cycle, once
  this is verified against a real Railway Postgres in production —
  intentionally not touched in this cycle, per the brief that spawned it.
- Backup size and cost for the shared Postgres database grow with crawl
  volume: a finished 20k-page result can be ~16 MB, and it now lives beside
  `org_configs`/`cost_ledger` rather than on a container disk nobody backs
  up anyway. Not solved here; noted as a residual consideration for
  whoever owns the Postgres instance's backup policy.
- `.orgs`/`.operators` remain disk-backed, single-workstation-only stores.
  Unaffected by this decision, and still a documented follow-up of their
  own.
- `docs-scribe` still needs to add this ADR to the summary table in
  `CLAUDE.md` §6 and write the cycle's build-log entry; neither is done by
  this change.

---

## Amendment (follow-up cycle): decision 5 reversed — reconciliation and
performance are now in Postgres too

Decision 5 above scoped `reconciliation`/`performance` out and left them
delegating to `fallback_store` unconditionally. That framing understated
what the choice actually did: `create()` (circuit closed) writes a job's row
to Postgres only, while `DiskJobStore.write_reconciliation`/
`write_performance` both require the job to exist *on disk* before writing
the sidecar file. For any job created while Postgres was healthy — which is
every job, in production, once this store became the default — the
unconditional disk delegation meant the write silently no-oped and every
later read returned `None`. `POST /jobs/{id}/reconcile/screaming-frog`
returned 200 with a correctly computed `ReconciliationSummary`, but nothing
durable was ever written, and every subsequent GET (including the download
buttons) 404'd. This was not a deferred feature; it was a production bug
introduced by this ADR's own decision 5, for every job since build-log 0118.

**Fix**: migration 0008 adds `reconciliation` and `performance` JSON columns
to `job_payloads` — same table, same nullable-column shape `result`/
`checkpoint`/`homepage_html` already have, for the same reason (decision 2's
`list_jobs()` cost argument applies identically to these two payloads).
`PostgresJobStore.write_reconciliation`/`read_reconciliation`/
`write_performance`/`read_performance` now follow the exact circuit-breaker
pattern every other method in this class uses: attempt Postgres, record
success/failure, fall back to disk only once the breaker opens. `DiskJobStore`
itself is unchanged — it remains correct for local/no-Postgres development,
and its existence-check semantics (a write to a job that does not exist on
disk logs a warning rather than raising) are untouched.

No new ADR: this is the same table, the same upsert/read pattern already
established by `finish()`/`write_checkpoint()`, closing a gap decision 5
itself flagged rather than introducing a new architectural choice.

The `.orgs`/`.operators` stores mentioned in decision 5 and the Consequences
section remain untouched and out of scope — this amendment is reconciliation
and performance only.
