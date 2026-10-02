# Cycle 0133: A key every verifier could sign with

- **Date**: 2026-10-01 (entry written 2026-10-02)
- **Scope**: Phase 1 (security) of the plan to ship the Screaming Frog worker as a
  standalone `rankuno-worker.exe`: dispatch claims signed with Ed25519 instead of a shared
  HMAC key ([ADR 0028](../adr/0028-dispatch-claims-are-signed-asymmetrically.md)), and
  worker credentials that can be revoked and rotated
  ([ADR 0029](../adr/0029-a-worker-credential-is-revoked-or-rotated-never-reactivated.md)).
  Two branches, merged with no conflicts.
- **Commits**: `64ad589` (Ed25519 signing), `358b077` (revoke/rotate), merged as `ab7c159`
  (fast-forward of `8afc0b5` on `origin/main`)
- **Quality gate**: **GREEN** on the combined tree — 3,814 passed, 2 skipped, 93.02%;
  UI 51 files / 630 tests (lead's run, pasted below; not re-run by the scribe)

---

## 1. Gate results

All runs by the lead on the combined branch (both commits merged onto `8afc0b5`).
The first full pytest run was killed at the background time limit, not by a failure;
the rerun completed and is the one quoted.

```
ruff format --check .            577 files already formatted
ruff check .                     All checks passed!
mypy src                         Success: no issues found in 159 source files
export_ui_contract.py --check    UI contract is up to date.
drift_check                      PASSED: no drift detected across 223 markdown files.
pytest --cov                     3814 passed, 2 skipped in 448.71s
                                 Required test coverage of 85.0% reached. Total coverage: 93.02%
tsc --noEmit                     exit 0
vitest                           51 passed (51) / 630 passed (630)
npm run build                    ✓ built in 9.40s
```

Targeted run for the revoke/rotate branch (lead):
`tests/api/test_worker_credential_routes.py tests/core/test_worker_store_credentials.py
tests/core/test_postgres_worker_store.py` — 49 passed.

| Measure | 0132 | 0133 |
| :--- | ---: | ---: |
| Python tests passed | 3,714 | 3,814 |
| Coverage | 93% | 93.02% |
| mypy source files | 156 | 159 |
| UI test files / tests | 49 / 621 | 51 / 630 |

---

## 2. What landed

### 2a. Ed25519 dispatch signing (`64ad589`, ADR 0028)

* `src/core/worker_dispatch_keys.py` (new): parses and validates the private and public
  keys (standard base64 of 32 raw bytes) and derives `kid` = first 16 hex of SHA-256 of
  the public key. Error messages name the setting, never the value.
* `src/core/worker_dispatch_signing.py`: `issue_dispatch_assignment` dual-signs while the
  legacy secret is set and `WORKER_DISPATCH_LEGACY_HMAC_ENABLED` is true (the default);
  `verify_dispatch_assignment` picks the algorithm from the worker's configuration, never
  from the token. A worker with `WORKER_DISPATCH_VERIFY_KEY` set never reads the HMAC
  segment.
* Wire model `SignedDispatchAssignment` unchanged (`{token, expires_at}`). Deployed
  workers parse it with `extra="forbid"`, so a new field would have made every
  un-upgraded worker reject every job. The Ed25519 signature rides inside the token
  header instead.
* `src/core/config.py`: `WORKER_DISPATCH_SIGNING_PRIVATE_KEY` (`SecretStr`, cloud),
  `WORKER_DISPATCH_VERIFY_KEY` (public, worker), `WORKER_DISPATCH_LEGACY_HMAC_ENABLED`.
  Production refuses to boot with neither a private key nor (secret + flag).
* `src/api/worker_verify_key_routes.py` (new): `GET /api/v1/workers/dispatch-verify-key`,
  operator session, returns `{algorithm, kid, public_key}`, `503` when the deployment has
  no Ed25519 key.
* `scripts/register_worker.py`: fetches the verify key (before registering, so a failure
  cannot orphan a one-time credential) instead of asking the operator to paste "the same
  secret set in Railway variables"; refuses non-HTTPS except localhost; reports failures
  by status code, never the raw body.
* `scripts/generate_dispatch_keypair.py` (new): prints a keypair, writes nothing to disk.
* `src/integrations/worker_cloud_client.py`: `require_secure_base_url` refuses a
  non-`https://` base URL at construction (localhost, `127.0.0.1`, `::1` exempt).
* `pyproject.toml`: `cryptography>=42.0` declared (previously transitive via `google-auth`).

### 2b. Credential revoke and rotate (`358b077`, ADR 0029)

* `POST /api/v1/workers/{id}/revoke` and `POST /api/v1/workers/{id}/rotate-credential`
  in `src/api/worker_credential_routes.py`, included by the dashboard router.
* `WorkerStore.set_active` / `replace_credential` on `DiskWorkerStore`
  (`src/core/worker_auth.py`) and `PostgresWorkerStore`. No migration — the columns are
  from alembic `0003`.
* Rotation returns the new secret once, stores only the PBKDF2 hash, reactivates, and
  clears `last_seen_at`.
* UI: `WorkerCredentialsPanel.tsx` (Revoke / Rotate token, each behind a confirmation;
  one-time token modal with copy; `REVOKED` tag). The old `DEACTIVATED` tag was renamed
  `REVOKED`. The adapter methods are called on the adapter instance and tested with a real
  `HttpAdapter` (`WorkerCredentialsPanel.httpAdapter.test.tsx`), because a detached method
  is the bug class from [build-log 0131](0131-a-method-called-without-its-object.md).
  `MockAdapter` deliberately does not implement them: its fleet is empty, and a fixture
  that "rotated" a credential would fabricate a secret no machine could use.

---

## 3. Design decisions

| Decision | Alternatives | Reason |
| :--- | :--- | :--- |
| Ed25519, algorithm fixed by worker config | per-worker HMAC; mTLS; JWT RS256/ES256 | ADR 0028 §Alternatives. Per-worker HMAC still lets a worker forge claims for itself and forces the cloud to store keys recoverably |
| No HMAC fallback on a verify-key worker | try Ed25519, then HMAC | A fallback preserves the forgery the change exists to remove |
| Envelope unchanged, signature in header | add a field to `SignedDispatchAssignment` | `extra="forbid"` on deployed workers |
| Dual-sign by default during transition | cut over in one deploy | Existing workers keep running on today's Railway config |
| No reactivate route; rotate is the only way back | `set_active(True)` toggle | Re-trusting a revoked secret undoes the revoke |
| Cross-org revoke/rotate is `404` | `403`, as the read routes use | Does not confirm another org's worker id exists |
| Session + UI confirmation, no `GuardrailEngine` | wrap in a `RiskClass.WRITE` tool | Matches registration and the GSC credential routes; the engine governs tool runs only |

---

## 4. Bugs found and fixed

1. **CRITICAL — any worker could forge dispatches for any worker or org.** ADR 0015 gate
   (b) used one symmetric key, `WORKER_DISPATCH_SIGNING_SECRET`, to sign on the cloud and
   verify on every worker. `register_worker.py` asked operators to paste it and wrote it
   in plaintext to `.env.local`. With a symmetric key every verifier is a signer, so
   anyone holding one worker's config could mint a valid assignment for any worker, org,
   seed URL, template or URL-list digest. Found by the Step-5 audit of the `.exe`
   distribution design, where a shipped or prompted key would become effectively public.
   Fixed by ADR 0028.
2. **HIGH — a worker credential could never be withdrawn.** `verify_worker_credential`
   checked `Worker.is_active`, but nothing in the codebase ever set it. A stolen
   credential was valid for the life of the worker row. Fixed by ADR 0029. Tests: before
   revoke a real worker poll returns 200, after revoke poll and heartbeat return 401;
   after rotate the old secret gets 401 and the new one 200; only a `pbkdf2_` hash is on
   disk; a cross-org revoke returns 404 and the victim still polls 200.
3. **The worker cloud client accepted `http://`.** The bearer credential and the signed
   assignments could travel in clear. Now refused at construction, localhost exempt.
4. **`register_worker.py` echoed raw server error bodies** (`resp.text`) to the terminal.
   Now status code plus a fixed hint.

### How the tests were shown to bite

* **Fail-before (builder A).** 23 tests failed on the pre-change code. Not all of them
  fail by *accepting a forgery*: some fail at `Settings` construction (the new settings do
  not exist), and the core Ed25519 test modules cannot import on the old code at all. So
  "23 failed before" overstates how many tests directly demonstrate the vulnerability.
  Builder A ran this with `git stash`, which is shared with the main checkout; the lead
  checked the stash list afterwards and only the three pre-existing entries remained.
* **Mutation test (lead).** The lead added an HMAC fallback inside
  `verify_dispatch_assignment` (try Ed25519; on failure, verify HMAC if a secret is
  present) and ran the Ed25519 test files. Two tests failed:
  `tests/core/test_worker_dispatch_ed25519.py::test_a_verify_key_worker_rejects_a_claim_carrying_only_a_valid_hmac_signature`
  and `::test_a_forged_claim_with_a_valid_hmac_and_a_broken_ed25519_signature_is_rejected`.
  The file was restored with `git checkout`; the tree was clean. The no-fallback property
  is therefore guarded by tests, not only by code review.

---

## 5. Corrections

1. **ADR 0015 gate (b) is no longer "HMAC-signed".** `README.md` (the ADR 0015 row) said
   the assignment "embeds the job envelope inside the same HMAC signature as the
   approval", and `docs/ARCHITECTURE.md` described `worker_dispatch_signing.py` as
   "HMAC-signed" and the worker's URL-list and claims checks as "HMAC-verified". With a
   verify key configured the worker checks Ed25519 only; HMAC survives as a transition
   path for un-upgraded workers. Both documents updated in this change.
   [ADR 0023](../adr/0023-a-url-list-travels-as-a-digest.md) and
   [build-log 0119](0119-a-list-that-travels-as-a-hash.md) say "the existing HMAC covers"
   the URL-list digest; the digest is still inside the signed claims, so the property
   holds, but the signature is now Ed25519 for upgraded workers. Those documents are left
   as written.
2. **`.env.example` mislabelled `WORKER_BUNDLE_ENCRYPTION_SECRET` as "BOTH SIDES".** It is
   cloud-only: the cloud encrypts uploaded bundles at rest and decrypts them for download;
   no worker needs it. Corrected in `64ad589`. Any worker `.env.local` that holds it
   should have it removed.
3. **"An un-revocable credential" was not a documented gap.** `CLAUDE.md` §8 and the
   README listed the in-process rate limiter and similar gaps, but nothing recorded that
   `is_active` was unreachable. It is closed here, so it was never moved to "Closed since
   the audit".
4. **Index.** Cycle 0131 (`0131-a-method-called-without-its-object.md`) has no row in
   the build-log index. Not backfilled here; recorded so it is not mistaken for a
   missing file.

---

## 6. Explicitly not done

1. **The operator runbook has not been executed.** No `WORKER_DISPATCH_SIGNING_PRIVATE_KEY`
   is set in Railway, no worker has been re-registered, legacy HMAC is still on, and
   `WORKER_DISPATCH_SIGNING_SECRET` has not been rotated or removed. **The shared-key
   exposure on existing worker desktops persists until the ADR 0028 runbook is run.**
   Shipping the code changed nothing about who can forge a dispatch today.
2. **Runbook ordering hazard.** With no private key set, a non-production cloud generates
   a per-process Ed25519 key that changes on every redeploy, so a worker registered
   against it stops verifying after the next deploy. Set
   `WORKER_DISPATCH_SIGNING_PRIVATE_KEY` in Railway **before** re-registering any worker.
   (Production refuses to boot without a private key or the legacy secret, so it falls
   back to HMAC-only rather than a random key; `register_worker.py` then gets `503`.)
3. **Production deploy not verified** by this entry. The lead is checking it separately.
   Verified in code only: `worker_dispatch_legacy_hmac_enabled` defaults to true and the
   cloud emits HMAC iff the secret is set and the flag is true, so today's Railway
   configuration keeps existing workers working after deploy.
4. **No overlapping key rotation.** A worker holds exactly one verify key; a key rotation
   is a cut-over that requires re-running registration on every worker. `kid` exists so
   two keys can be published side by side later; that is not built.
5. **Verify-key endpoint is trust-on-first-use.** The worker trusts whatever key the cloud
   it registered against returns over operator-authenticated HTTPS. `kid` is printed, but
   no fingerprint is pinned or checked out of band.
6. **Queued jobs for a revoked, never-rotated worker are never cleaned up.** `DISPATCHED`
   jobs are swept to `FAILED` after `WORKER_DISPATCH_TIMEOUT_S`; `QUEUED` ones wait forever.
7. **No "register a machine" UI.** Registration is still `scripts/register_worker.py`,
   which requires the engine source.
8. **Postgres SQL** for `set_active` / `replace_credential` is tested only against the
   in-memory fake cursor, like the rest of `PostgresWorkerStore`.
9. **Phase 2 — make the worker packageable — not started.** Cut the two imports that pull
   11 engine modules into the worker (`url_list.py:56`, `upload_manifest.py:50`);
   frozen-aware `%LOCALAPPDATA%` paths; credential in Windows Credential Manager instead
   of `.env.local`; first-run token prompt.
10. **Phase 3 — build and distribute — not started.** PyInstaller onedir build, GitHub
    Actions on a release tag, dashboard download with SHA-256, unsigned pilot first, no
    auto-updater.

---

## 7. Files changed

`64ad589` (26 files, +1,947 / −166): `.env.example`, `pyproject.toml`,
`docs/adr/0028-dispatch-claims-are-signed-asymmetrically.md`,
`scripts/generate_dispatch_keypair.py` (new), `scripts/register_worker.py`,
`scripts/run_worker_daemon.py`, `src/api/server.py`, `src/api/worker_routes.py`,
`src/api/worker_schemas.py`, `src/api/worker_verify_key_routes.py` (new),
`src/core/config.py`, `src/core/worker_dispatch_keys.py` (new),
`src/core/worker_dispatch_signing.py`, `src/integrations/worker_cloud_client.py`,
`src/modules/seo/screaming_frog_control/worker_daemon.py`, `worker_daemon_cli.py`, and
tests: `tests/api/test_worker_verify_key_routes.py`,
`tests/core/test_config_dispatch_signing.py`, `tests/core/test_worker_dispatch_ed25519.py`,
`tests/core/test_worker_dispatch_signing.py`,
`tests/integrations/test_worker_cloud_client.py`,
`tests/modules/seo/screaming_frog_control/test_worker_daemon_cli.py`,
`test_worker_daemon_ed25519.py`, `tests/scripts/` (`__init__.py`,
`test_generate_dispatch_keypair.py`, `test_register_worker.py`).

`358b077` (17 files, +1,284 / −20): `src/api/worker_credential_routes.py` (new),
`src/api/worker_dashboard_routes.py`, `src/api/worker_route_helpers.py`,
`src/api/worker_schemas.py`, `src/core/postgres_worker_store.py`,
`src/core/worker_auth.py`, `rankuno-ui/src/adapters/{adapterInterface,httpAdapter,mockAdapter}.ts`,
`rankuno-ui/src/components/screaming-frog/{ScreamingFrogView.tsx,WorkerCredentialsPanel.tsx,WorkerCredentialsPanel.test.tsx,WorkerCredentialsPanel.httpAdapter.test.tsx,screaming-frog.css}`,
tests: `tests/api/test_worker_credential_routes.py`,
`tests/core/test_worker_store_credentials.py`, `tests/core/test_postgres_worker_store.py`.

This entry: `docs/build-log/0133-a-key-every-verifier-could-sign-with.md`,
`docs/adr/0029-a-worker-credential-is-revoked-or-rotated-never-reactivated.md`,
`docs/build-log/README.md`, `README.md`, `docs/ARCHITECTURE.md`.

---

## 8. Follow-ups

* Execute the ADR 0028 runbook (items 1–2 of §6), then burn the old shared secret.
* Fail or reassign `QUEUED` jobs when their worker is revoked.
* Phases 2 and 3 of the `.exe` plan.
