# ADR 0036: Cloud GSC credentials are encrypted in Postgres

- **Status**: Accepted
- **Date**: 2026-10-09
- **Deciders**: AI Lead, Lead AI Systems Engineer (user chose "Keep cloud GSC accounts across
  redeploys"; security review PASS WITH CONDITIONS C1–C12; the user approved the design with
  decisions Q1 (invalid names are 422), Q2 (parent org row created with budget 0), Q3 (this
  migration is 010; the in-flight `0010_job_password_hash` renumbers to 011), Q4 (`updated_by`
  column), Q5 (the key is required in every environment once Postgres is selected))
- **Amends**: [ADR 0010](0010-gsc-api-security-and-safety-controls.md) §3, "tokens are saved
  exclusively in local, gitignored files"

---

## Context

An operator adds an org's Google Search Console account (refresh token, optional OAuth client id
and secret) in the UI. The API stored it in `OrgConfig.gsc_accounts` inside
`.orgs/org_configs.json` (`DiskOrgConfigStore`). On Railway that file is on the container disk,
and every redeploy wipes it, so every cloud account disappeared on every deploy.

Swapping the whole `OrgConfigStore` for Postgres would also have moved the org budget, active flag
and facet checks that job admission reads. That is a larger change with its own risks, and nothing
asked for it.

The security review found two defects on the existing path:

- **F1.** `Settings._org_gsc_accounts` swallowed `KeyError`, `OSError` and `ValueError` and returned
  "no org accounts". Resolution then fell through to a same-named `.env.local` profile. A store
  outage could therefore make a crawl read another client's Search Console.
- **F2.** FastAPI's default 422 body echoes each failing item's `input`. For a body missing one
  field, that input is the whole body, so a missing `account_name` returned the refresh token in the
  response.

## Decision

1. **A narrow seam.** `GscAccountStore` (`src/core/gsc_account_store.py`) has five operations,
   each scoped by `org_id`: `list_accounts`, `account_names`, `get_credential`, `upsert` and
   `delete`.
   - `DiskGscAccountStore` wraps the existing `OrgConfig.gsc_accounts`. Local behaviour is
     unchanged, including its fail-soft reads.
   - `PostgresGscAccountStore` (`src/core/postgres_gsc_account_store.py`) is the cloud store.
   - The org budget, active and facet checks still read `OrgConfigStore`, exactly as before.
2. **One selection point.** `Settings.gsc_account_store` picks the store:
   - Postgres when `get_postgres_settings().is_configured()`, the same predicate
     `_default_job_store` uses;
   - otherwise disk.

   The result is cached, so the API (`create_app`) and crawl-time resolution
   (`resolve_gsc_account`, reached through `GscTokenManager`) read the same object. A local server
   still never reaches the database (ADR 0032): `run_local.ps1` blanks the DB keys, so the predicate
   selects disk.
3. **Encryption at rest.** The refresh token and the client secret are encrypted with AES-256-GCM
   (`cryptography`'s `AESGCM`), in `src/core/gsc_credential_crypto.py`.
   - Each encryption uses a fresh 12-byte nonce. The stored value is `nonce || ciphertext+tag`.
   - The AAD is `rankuno-gsc-cred-v1|key_id|org_id|account_name|field`. A ciphertext moved to
     another org, another account or the other column fails authentication instead of decrypting.
   - `key_id` is the first 8 hex characters of `HMAC-SHA256(key, fixed label)`. Each row records the
     key that wrote it.
   - Reads select the key by `key_id` (current, or previous during a rotation). Writes always use
     the current key.
   - A row whose key is gone, or whose bytes do not authenticate, raises
     `GscCredentialDecryptionError(account_name)`. The message is "re-add the account" and never
     includes ciphertext, key or plaintext. Other accounts are unaffected.
   - Listing never decrypts: `has_secret_override` comes from `client_secret_ct IS NOT NULL`.
4. **Key configuration.** `GSC_CREDENTIAL_ENCRYPTION_KEY` (base64url of exactly 32 bytes), plus
   `GSC_CREDENTIAL_ENCRYPTION_KEY_PREVIOUS` during a rotation.
   - A malformed key is refused at boot in every environment. The message names the variable and
     never the value.
   - When Postgres is selected, a missing key stops `create_app()` in every environment.
   - There is no random per-process key: one would make every stored account unreadable after a
     restart.
5. **Fail closed (fixes F1).** `GscAccountStoreUnavailableError` subclasses `RankunoError` and
   deliberately none of `OSError`, `ValueError` or `KeyError`.
   - The Postgres store raises it on an open breaker or on any database or connection error. There
     is no disk fallback for credentials.
   - Resolution lets it, and `GscCredentialDecryptionError`, propagate. Only `get_credential(...)
     is None`, a genuine not-found, falls through to `.env.local`.
   - The account routes, `GET /gsc/accounts` and job intake return 503 through one app-wide handler.
   - GSC enrichment records `failed` with the exception class name as the reason.
   - Database errors are logged by class name and SQLSTATE only, because a psycopg DETAIL can quote
     the row.
6. **Lazy resolution is revocation.** Credentials are resolved when enrichment starts and are never
   snapshotted into the job. Deleting an account therefore revokes it for every crawl not yet
   enriched. Refreshed access tokens stay in memory, as before (no write-back).
7. **Org isolation.**
   - Every SQL statement binds `org_id` from the verified principal. Single-row statements add
     `account_name`.
   - The upsert's `DO UPDATE` also carries `WHERE org_gsc_accounts.org_id = %s`.
   - A cross-org request is refused with an identical 403 before any lookup, whether or not the
     target exists.
   - An unknown account in the caller's own org is 404.
8. **Input bounds and the 422 handler (fixes F2).**
   - Account names are full-matched against `[a-z0-9_-]{1,64}`, so a trailing newline is refused.
     The delete route's path name is checked the same way.
   - `client_id` is at most 256 characters of `[A-Za-z0-9._-]`. `client_secret` is at most 512 and
     `refresh_token` at most 2048 printable non-space characters.
   - An app-wide `RequestValidationError` handler strips `input` and `ctx` from every 422 item.
   - Invalid names are now 422, not 400.
9. **Writes are rate-limited and audited.** Create and delete consume the caller's shared
   `principal:<operator_id>` bucket (429 when exhausted). The audit events are
   `org_gsc_account_created`, `_replaced` and `_deleted`, and they carry org, account and
   operator id only.
10. **Schema.** Migration 010 creates `org_gsc_accounts`:
    - columns `client_secret_ct`/`refresh_token_ct` (BYTEA), `key_id`, `created_by`, `updated_by`,
      `created_at` and `updated_at`;
    - PK `(org_id, account_name)`;
    - FK to `org_configs` with `ON DELETE CASCADE`;
    - a CHECK on the name and a CHECK on the length of `client_id`;
    - no index on either ciphertext column.

    An upsert creates the parent `org_configs` row if it is absent, with budget **0**. A positive
    budget would let `PostgresJobStore.create` admit jobs for an org that only saved a GSC account.
    Existing rows are untouched.

    The downgrade drops the table, destroying every stored credential. There is no data migration:
    the disk copies were already lost to redeploys, and operators re-add their accounts.

## Consequences

- Cloud GSC accounts survive redeploys. A database dump or backup holds no usable token without
  the key.
- **The key is now a recovery-critical secret.** Lose it and every stored account must be re-added.
  Keep it in a password manager as well as in Railway.
- Rotation keeps old rows readable through `..._PREVIOUS`, but nothing re-encrypts them. PREVIOUS
  can be removed only after every account has been saved again.
- During a Postgres outage, intake requests that name a GSC account, and the account picker, return
  503 instead of degrading silently. This is intended.
- The shared per-principal bucket couples account edits and job creation for one operator.
- Changing the 422 body shape is app-wide. No UI code read `input` or `ctx`.

## Explicitly not done

- No re-encryption or rotation tool. No automatic migration of the old disk accounts.
- No KMS or envelope encryption. The key is a Railway service variable.
- `OrgConfigStore` itself is still disk on Railway. Org budget, active and facet settings are not
  made durable by this ADR.
- The rate limiter and circuit breaker are per process (CLAUDE.md §8). This is acceptable at
  `numReplicas = 1`.
