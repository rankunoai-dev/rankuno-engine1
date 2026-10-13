# Cycle 0154: Keep cloud GSC accounts across redeploys

- **Date**: 2026-10-09
- **Scope**: Org GSC accounts move off the Railway container disk into an encrypted Postgres table when `DATABASE_URL` is configured. Local behaviour (disk, ADR 0032) unchanged. Decision recorded in [ADR 0037](../adr/0037-cloud-gsc-credentials-are-encrypted-in-postgres.md), amending ADR 0010 §3.
- **Commits**: `98dad0f` and merge `5c5ebf5` on branch `gsc-accounts-postgres`; merged to `main` as `81186d8` and deployed. The merge to `main` was done by someone other than the lead (the user or another session); see §5.
- **Quality gate**: implementer's pre-merge run 4471 passed, 2 skipped, 93.43%. On the merged tree 10 failed, all pre-existing golden-snapshot failures from `main` (cycle 0155). Not re-run by the scribe.

## 1. Gate results

Implementer's runs (reported, not re-executed by the scribe):

| Stage | Pre-merge (`98dad0f`) | Merged tree (`5c5ebf5`) |
| :--- | :--- | :--- |
| ruff format / check | clean | clean |
| mypy --strict | clean | 181 source files, clean |
| pytest | 4471 passed, 2 skipped | 4476 passed, 10 failed, 2 skipped |
| coverage | 93.43% | 93.59% |
| drift_check / contract check | clean | clean |

The 10 failures on the merged tree are 8 in `test_golden_extract_at_fetch.py` and 2 in `test_fetch_time_extraction.py`. They were already failing on `main` before this branch merged; cause and fix are in cycle 0155.

Offline migration render (`alembic upgrade 010:011 --sql`, implementer): creates `org_gsc_accounts` with `pk_org_gsc_accounts (org_id, account_name)`, `fk_org_gsc_accounts_org` → `org_configs.org_id ON DELETE CASCADE`, `ck_org_gsc_accounts_name` (`account_name ~ '^[a-z0-9_-]{1,64}$'`) and `ck_org_gsc_accounts_client_id_len` (`length(client_id) <= 256`). Constraint names confirmed against `alembic/versions/0011_org_gsc_accounts.py` by the scribe.

Lead verification on production: a `POST /api/v1/auth/login` with body `{}` returned 422 `detail` items without an `input` key. The app-wide handler from this cycle is therefore serving, and since `create_app` refuses to boot with Postgres selected and no key, `GSC_CREDENTIAL_ENCRYPTION_KEY` is set. That inference was not checked directly.

## 2. What landed

### Why this cycle exists

The user reported that GSC accounts disappear from the cloud GSC Accounts page "everytime". The investigation found org GSC accounts were stored by `DiskOrgConfigStore` at `Settings.org_config_path`, used by `server.py`, on the Railway container disk; `railway.toml` already noted a redeploy wipes `/app/.orgs`, and build-log 0118 line 240 had deferred the `.orgs` store. Build-log 0153 §6.6 listed the same gap.

### Security audit (before coding)

PASS WITH CONDITIONS, C1–C12. Findings:

| # | Severity | Finding | Outcome |
| :--- | :--- | :--- | :--- |
| F1 | HIGH | `_org_gsc_accounts` caught `KeyError`/`OSError`/`ValueError` and returned `{}`; an org miss then fell through to a same-named `.env.local` profile, so during a store outage a crawl could use the wrong Google account | Fixed (§4.1) |
| F2 | MEDIUM | A missing-field 422 echoed the submitted refresh token and client secret (no `RequestValidationError` handler) | Fixed (§4.2) |
| F3 | — | Migration number collided with another session's `0010` | Renumbered to 011 (§3) |
| F4 | — | Account names accepted a trailing newline (`re.match` with `$`) | Fixed: `fullmatch` |
| F5 | — | Create silently replaced an existing account | Now audited as `replaced` |
| F6 | out of scope | Token refresh uses raw `requests.post` outside `BaseAPIClient` | Not done (§6) |

### Design as built

- `src/core/gsc_credential_crypto.py`: AES-256-GCM (`cryptography` `AESGCM`), fresh 12-byte nonce per encryption. AAD binds `label|key_id|org|account|field`, so a ciphertext copied to another row or field does not decrypt. Key from `GSC_CREDENTIAL_ENCRYPTION_KEY` (base64url, 32 bytes) plus optional `GSC_CREDENTIAL_ENCRYPTION_KEY_PREVIOUS` for rotation. `key_id` is the first 8 hex characters of an HMAC-SHA256 of the key; decrypt selects the key by the row's `key_id`.
- `alembic/versions/0011_org_gsc_accounts.py`: table `org_gsc_accounts`, PK `(org_id, account_name)`, FK to `org_configs` with `ON DELETE CASCADE`, CHECKs as in §1, `BYTEA` ciphertexts, `key_id`, `created_by`, `updated_by`, timestamps. No index on any ciphertext column.
- `src/core/gsc_account_store.py`: `GscAccountStore` protocol with `DiskGscAccountStore` (local, unchanged). `Settings.gsc_account_store` is the one selection point, shared by the API and crawl-time resolution.
- `src/core/postgres_gsc_account_store.py`: `PostgresGscAccountStore`. No disk fallback. A circuit breaker opens to an error, not to an empty list. Logs exception class and SQLSTATE only.
- `src/api/gsc_account_routes.py` (routes moved out of `server.py`): `fullmatch` name validation (invalid name now 422, was 400), field length bounds, rate limit on the principal bucket, audit events `created` / `replaced` / `deleted` carrying names only.
- `src/api/error_handlers.py`: app-wide 422 handler strips `input` and `ctx`; `GscAccountStoreUnavailableError` → 503.
- Fail closed: store errors propagate (503 on account routes, picker and job intake; `failed` enrichment). Only a genuine not-found falls through to `.env.local`.

## 3. Design decisions

- **D1 — key selected by row `key_id`, not by trial decryption.** Rotation keeps old rows readable via `_PREVIOUS` without trying every key.
- **D2 — the parent `org_configs` row is inserted with budget 0.** The FK needs a parent; a budget of 0 means saving a GSC account can never by itself let an org run paid jobs.
- **D3 — a missing key refuses boot at `create_app` in every environment once Postgres is selected.** Not only in production: a dev server against a real database would otherwise write accounts it cannot later read.
- **Numbering resolved by merge, not rebase.** Another session's `0010_job_password_hash` landed on `main` first, so this migration became `011` with `down_revision = "010"`. ADR 0036 was taken by the theme ADR, so this became ADR 0037. A single-head test guards the chain.

## 4. Bugs found and fixed

1. **F1, wrong-account fallthrough.** Fail-before on the original `config.py`: `Failed: fell through to .env.local: token='rt-env-acme'`. Now raises `GscAccountStoreUnavailableError`.
2. **F2, secrets echoed in 422.** Fail-before: without the handler, the missing-field response contained the canary refresh token and client secret.
3. **F4, trailing newline in names.** `re.match(...$)` accepts `"name\n"`; replaced with `fullmatch`.
4. **AAD binding is load-bearing.** Removing it made 3 AAD tests fail, confirming the tests detect a swapped ciphertext.

## 5. Corrections

- **Build-log 0153 §6.6** stated cloud GSC accounts are wiped on every redeploy and that this cycle was planned as 0144 / ADR 0036. With `DATABASE_URL` set, GSC accounts now persist; the numbers used are 0154 / ADR 0037.
- **Build-log 0118 line 240** grouped `.orgs` and `.operators` as deferred. The GSC-account part of `.orgs` is now in Postgres; the rest is still deferred (§6).
- **Process.** The lead did not run its own full gate on the merged result before it reached `main`. The branches were merged and pushed by someone else while `main` was red (cycle 0155). The implementer's merged-tree run above is the only gate on `5c5ebf5`.

## 6. Explicitly not done

1. **No live-Postgres test.** The SQL is covered by a recording fake DB and the offline migration render only.
2. **No re-encryption or key-rotation tool.** `_PREVIOUS` keeps old rows readable; nothing rewrites them under the new key.
3. **No KMS.** The key is an environment variable.
4. **Other org settings and operator logins are still on container disk** (`/app/.orgs`, `.operators`) and are still wiped by a redeploy.
5. **Existing cloud accounts were not migrated.** They were already lost to redeploys; users re-add them once.
6. **UI not updated** for 422 list-shaped `detail`, 429 or 503. Handoff to ui-engineer: `GscAccountForm.tsx` should mirror the server's field bounds and render 422 `loc`/`msg`, and the 429 and 503 `detail` strings.
7. **F6**: token refresh still uses raw `requests.post` outside `BaseAPIClient`.
8. **No new `CLAUDE.md` §8 entry moved.** The disk-stored GSC accounts gap was never listed there; it lived in `railway.toml` and build-log 0118.

## 7. Files changed

`98dad0f`: 25 files, 2,885 insertions, 251 deletions. New: `src/api/error_handlers.py`, `src/api/gsc_account_routes.py`, `src/core/gsc_account_store.py`, `src/core/gsc_credential_crypto.py`, `src/core/postgres_gsc_account_store.py`, the migration, ADR 0037 and five test files. Modified: `server.py`, `config.py`, `errors.py`, `gsc_token_manager.py`, `.env.example`, `railway.toml`, `README.md`, `docs/ARCHITECTURE.md`, ADR 0010. `5c5ebf5` renumbered the migration (010 → 011) and the ADR (0036 → 0037) while merging `origin/main`.
