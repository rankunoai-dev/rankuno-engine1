# ADR 0029: A worker credential is revoked or rotated, never reactivated

**Status**: APPROVED — part of the Phase 1 security plan the operator approved after the
Step-5 audit of the worker distribution design, 2026-10-01.

**Date**: 2026-10-01

**Amends**: [ADR 0015](0015-cloud-local-desktop-worker-architecture.md) condition 2
(worker identity). Adds the withdrawal half that condition 2 implied and nothing
implemented. Companion to [ADR 0028](0028-dispatch-claims-are-signed-asymmetrically.md),
which removed signing authority from worker configuration; this ADR makes the one secret
left in that configuration withdrawable.

---

## Context

`verify_worker_credential` (`src/core/worker_auth.py`) has always refused a worker whose
`is_active` is false. Nothing anywhere set it to false: there was no route, no store
method and no script. A worker credential, once issued, was valid for the life of the
worker row. The audit rated this **HIGH**, because the worker is about to be handed to
non-technical operators as a downloadable build, and a copied `.env.local`, a stolen
laptop or a leaver's machine would otherwise keep pulling jobs and uploading bundles for
the org indefinitely.

The columns needed already exist in both stores (`alembic/versions/0003_worker_identity_table.py`
for Postgres, the JSON record for `DiskWorkerStore`), so no migration is involved.

## Decision

1. **Two actions.** `POST /api/v1/workers/{id}/revoke` sets `is_active = False`;
   `POST /api/v1/workers/{id}/rotate-credential` mints a new secret, stores only its
   PBKDF2 hash, sets `is_active = True` and clears `last_seen_at`, in one store write.
   Both are on `src/api/worker_credential_routes.py`, backed by
   `WorkerStore.set_active` and `WorkerStore.replace_credential` on `DiskWorkerStore`
   and `PostgresWorkerStore`. Revoke is idempotent.
2. **No reactivate route.** Re-enabling a revoked worker under its *old* secret would undo
   the revoke in exactly the case it exists for — a credential that may have been copied.
   Rotation is the only way back to active, so a worker can only return under a secret
   minted after the revoke.
3. **The new secret is shown once.** The rotate response is the only place it exists in
   clear. It is not logged, not stored, and cannot be fetched again; losing it means
   rotating again.
4. **Rotate clears `last_seen_at`.** The machine that last polled did so with the old
   secret. Leaving the timestamp would show the worker "online" in `GET /workers` for up
   to `offline_after_s` on the strength of a credential that no longer works, and a
   dispatch confirm would queue a job for it instead of answering the offline `409`.
   Cleared, the worker reads offline until the new secret actually polls.
5. **Cross-org is `404`, the same answer as an unknown id.** The read routes use `403`
   for another org's worker (`owned_worker` in `src/api/worker_route_helpers.py`). These
   routes do not: the store already refuses to tell the two apart, and on the route family
   most useful to someone holding a stolen operator session, confirming that a worker id
   exists in some other org is information worth withholding. The inconsistency with the
   read routes is deliberate.
6. **Approval model.** These follow `POST /workers` (registration) and the GSC account
   routes in `src/api/server.py`, the existing precedent for operator-initiated credential
   changes: an authenticated, org-scoped operator session (`require_principal`) is the
   authorization, and the UI confirmation dialog is the human confirmation.
   `GuardrailEngine` is not involved — it governs `BaseTool.run()` executions that declare
   a `RiskClass`, and no dashboard credential route goes through it. Revoke only reduces
   what a credential can do.
7. **In-flight behaviour.** Nothing is cancelled by the revoke itself.
   * The revoked worker's next poll, heartbeat, progress, upload or failure report gets the
     same `401` an unknown worker gets. The daemon treats `401` as "credential rejected"
     and exits with code 3 (`worker_daemon_cli.EXIT_CREDENTIAL_REJECTED`), not a restart
     loop.
   * A job already `DISPATCHED` to it can no longer be progressed, uploaded or failed, and
     `expire_stale_dispatched` moves it to `FAILED` after `WORKER_DISPATCH_TIMEOUT_S`.
   * A job still `QUEUED` for it waits. A rotated worker claims it under the new secret on
     its next poll. A revoked worker that is never rotated never claims it, and nothing
     cleans it up (see below).

## Alternatives considered

* **A reactivate toggle (`set_active(True)`).** Cheapest, and what `is_active` suggests.
  Rejected for the reason in decision 2.
* **Delete the worker row.** Leaves `worker_jobs` rows naming a worker id that no longer
  resolves, gives the UI nothing to show as "REVOKED", and makes recovery a fresh
  registration rather than a rotation. Rejected.
* **Route the actions through `GuardrailEngine` as `RiskClass.WRITE`.** Would require a
  `BaseTool` wrapper around a single store write and an approval provider the dashboard
  does not have; registration, which *creates* a credential, already does not. Rejected
  for consistency with the existing credential routes.
* **`403` for another org's worker, matching the reads.** Rejected for the reason in
  decision 5.

## Consequences

* A leaked worker credential is now bounded by how quickly an operator notices and clicks
  Revoke, not by the life of the worker row.
* An operator who rotates must get the new secret onto the machine by hand; until then the
  worker is offline. There is no in-band delivery, by design — the old secret cannot be
  trusted to receive the new one.
* The rotate route returns a secret in a response body. The UI shows it once in a modal
  with a copy button and does not persist it.

## Explicitly not done

* Queued jobs pinned to a revoked, never-rotated worker are never failed or cleaned up.
* No reason, actor or timestamp is recorded on the worker row for a revoke; the structured
  log line is the only record.
* No "register a machine" UI; registration is still `scripts/register_worker.py`.
* `PostgresWorkerStore.set_active` / `replace_credential` SQL is covered only by the
  in-memory fake cursor, like the rest of that store.
