# Cycle 0135: A worker that carried the engine

- **Date**: 2026-10-02
- **Scope**: Phase 2 of the plan to ship the Screaming Frog worker as a standalone
  `rankuno-worker.exe`: the worker becomes packageable. Engine-free import closure, frozen-aware
  data paths, the worker credential in Windows Credential Manager, a one-time
  `rankuno-worker setup`, and a server/worker process role
  ([ADR 0030](../adr/0030-the-worker-ships-as-a-standalone-client.md)). No executable is built
  in this cycle; that is Phase 3.
- **Commits**: `302f1d1` (feature), `2b5f1cd` (merge of `origin/main` `36fe70b`), `90b59a3`
  (flaky-test fix). Branch `worker-packageable`, pushed to `origin/main` as `90b59a3`.
- **Quality gate**: **GREEN** on the merged branch (lead's run, pasted below) — 3,895 passed,
  2 skipped, 93.14%; mypy 165 files. UI not run (no UI change).

**Numbering note**: the highest committed entry is `0134`, and the main checkout's
`docs/build-log/` held nothing above `0134` uncommitted, so `0135` was free in both places.

## 0. Background

The user asked for a standalone `rankuno-worker.exe` so teammates can run the Screaming Frog
worker without a git clone or the engine source. Decisions taken by the user across the plan:

| Question | Decision |
| :--- | :--- |
| Order | Phase 1 security first (shipped as [0133](0133-a-key-every-verifier-could-sign-with.md)), then packageability, then the build |
| Packaging | PyInstaller folder (onedir) build |
| Signing | Unsigned pilot first |
| Build trigger | GitHub Actions on a release tag |
| Credential entry | Sign in once inside the worker, not a pasted token |

Phase 2 was built by `feature-builder` in an isolated worktree and approved at the Step-3 review
(ADR 0030 status line). The lead independently re-measured the import closure, re-ran the
fail-before, merged `origin/main` and re-ran the full gate.

---

## 1. Gate results

All runs by the lead on the merged branch (`302f1d1` + `origin/main` `36fe70b` + `90b59a3`).
Not re-run by the scribe except where stated below.

```
ruff format --check .            599 files already formatted
ruff check .                     All checks passed!
mypy src                         Success: no issues found in 165 source files
drift_check                      PASSED: no drift detected across 229 markdown files
export_ui_contract.py --check    UI contract is up to date
pytest --cov=src                 exit 0
                                 Required test coverage of 85.0% reached. Total coverage: 93.14%
                                 3895 passed, 2 skipped, 0 failed
```

The pass count was counted from the progress output: the project's pytest configuration
suppresses the summary line. UI `vitest` was not run in this cycle; no file under `rankuno-ui/`
changed.

Scribe's own check (not the gate): the ten new or touched test files
(`test_worker_import_boundary.py`, `test_bundle_filenames.py`, `test_worker_setup.py`,
`test_worker_daemon_cli.py`, `test_app_paths.py`, `test_credential_vault.py`,
`test_url_hosts.py`, `test_worker_registration_client.py`, `test_server_process_role.py`,
`test_rulebook_store.py`) ran with `--no-cov` from this worktree: 96 dots, no failures.
`import src` resolved to the worktree's `src/` with the main checkout's venv.

Scribe's drift check after the documentation changes in this entry. `drift_check.py` reads only
git-tracked markdown, so this entry was marked intent-to-add (`git add -N`) for the run and
unmarked afterwards; 230 = the lead's 229 plus this file:

```
Running Architecture & Documentation Drift Audit...

--- Drift Audit Results ---
PASSED: no drift detected across 230 markdown files.
  - all relative links resolve
  - all domain modules documented
  - all skill directories populated
```

| Measure | 0134 | 0135 |
| :--- | ---: | ---: |
| Python tests passed | 3,821 | 3,895 |
| Coverage | 93.03% | 93.14% |
| mypy source files | 160 | 165 |
| ruff-formatted files | not recorded | 599 |
| Markdown files under drift check | not recorded | 229 |

### Import closure of the worker CLI

Measured by importing `src.modules.seo.screaming_frog_control.worker_daemon_cli` in a fresh
interpreter and listing loaded `src` modules.

| Measure | Before (`ea43a01`) | After |
| :--- | ---: | ---: |
| `src` modules loaded | 49 | 43 (lead's probe) / 44 (builder's probe) |
| Engine modules (`page_classifier` x6, `contracts` x5) | 11 | 0 |
| `src.api` (server) modules | not measured | 0 |

The two probes differ by one module. The scribe re-ran a probe that counts the top-level `src`
package itself as well as `src.*`, and got 44 with 0 engine or `src.api` modules, so the
difference is most likely whether the `src` package is counted. ADR 0030 states 44.

### Fail-before

Restoring `ea43a01`'s `url_list.py` and `upload_manifest.py` makes
`tests/modules/seo/screaming_frog_control/test_worker_import_boundary.py::test_the_worker_loads_no_engine_or_server_module`
fail with `AssertionError` at line 71. With the new code it passes (lead's run).

---

## 2. What landed

### 2a. Engine-free import boundary

* `src/core/url_hosts.py` (new): `safe_split`, `site_host`, `registrable_domain`, moved out of
  `page_classifier/url_rules.py`. They are stdlib-only URL facts; importing them from
  `url_rules` executed `page_classifier/__init__.py`, which eagerly imports the cascade.
  `url_rules` re-exports the same function objects, so no caller changed.
* `src/modules/seo/screaming_frog_control/bundle_filenames.py` (new): the issue-source CSV
  filenames as a literal `frozenset`. `upload_manifest.py` previously imported
  `ISSUE_CATALOGUE` only to compute that set. `test_bundle_filenames.py` (tests ship in no
  executable, so it may import the catalogue) asserts set equality in both directions.
* `url_list.py` and `upload_manifest.py` now import from those two modules: one line each.
* `test_worker_import_boundary.py` (new): imports the worker CLI and setup module in a **fresh
  subprocess** (in-process `sys.modules` is shared across the pytest session) and fails on any
  `src` module outside an allowlist: `src.core`, the three worker integration clients, and
  `screaming_frog_control`.

### 2b. Frozen-aware paths

* `src/core/app_paths.py` (new): not frozen, `REPO_ROOT` exactly as before, and no environment
  variable can change it; frozen (`sys.frozen`), `%LOCALAPPDATA%\Rankuno\Worker`, or
  `RANKUNO_WORKER_HOME` (honoured only when frozen). The module takes the environment as an
  argument; `config.user_data_root()` is the one place that reads it.
* `src/core/config.py`: `settings_customise_sources` loads `worker.env` from the user data root
  when frozen; `ProcessRole` (`server` | `worker`) and `WorkerCredentialStore` (`env` |
  `credential_manager`) settings.
* Layout under the root: `worker.env`, `logs/audit.jsonl`, `deliverables/output/`,
  `templates/screaming_frog/`, `.process_ledger.json`, `.worker_consumed_jobs.json`.

### 2c. Credential in Windows Credential Manager

* `src/core/credential_vault.py` (new): `CredentialVault` protocol, `WindowsCredentialVault`
  (the only `win32cred` caller; target `Rankuno Worker/<worker_id>`,
  `CRED_PERSIST_LOCAL_MACHINE`), and `resolve_worker_credential`, which holds the precedence
  in one place: frozen = vault only, a `WORKER_CREDENTIAL` in any env file ignored with a
  warning, an error off Windows; checkout with `WORKER_CREDENTIAL_STORE=credential_manager` =
  vault then env; checkout default = env, unchanged.
* `pyproject.toml`: `win32cred` added to the mypy ignore-missing-imports list.

### 2d. `rankuno-worker setup`

* `src/modules/seo/screaming_frog_control/worker_setup.py` (new) and a `setup` subcommand in
  `worker_daemon_cli.py`. Also runs on the first interactive launch of a frozen build with no
  `worker.env`; a non-interactive first launch exits with "Run: rankuno-worker setup". In a
  checkout `setup` is refused and points at `scripts/register_worker.py`.
* `src/integrations/worker_registration_client.py` (new): `WorkerRegistrationClient
  (BaseAPIClient)` for login, verify key and registration. `scripts/register_worker.py` now
  takes `DEFAULT_CLOUD_URL` and `VERIFY_KEY_PATH` from it; otherwise unchanged.

### 2e. Process role

* `create_app` raises `ConfigurationError` when `RANKUNO_PROCESS_ROLE=worker`.

---

## 3. Design decisions

| Decision | Alternatives | Reason |
| :--- | :--- | :--- |
| Move three URL helpers to `core` | Lazy import in `url_list.py`; slim `page_classifier/__init__` | They carry no classification knowledge; a lazy import still lands in the PyInstaller closure |
| Literal filename set, pinned by a two-way test | Keep the catalogue import and exclude `contracts` at freeze time | An exclusion lives in PyInstaller config where no test sees it, and the worker would fail at import |
| Allowlist boundary test, in a subprocess | Denylist; in-process `sys.modules` check | A denylist misses the next engine package; in-process the check sees every module the session loaded |
| `win32cred` behind a protocol | `keyring` | New dependency, runtime-selected backend that can silently degrade, awkward to freeze. pywin32 is already a worker dependency |
| Frozen worker: vault only, never plaintext | Fall back to `WORKER_CREDENTIAL` | A plaintext copy would quietly win and defeat the move |
| `RANKUNO_WORKER_HOME` only when frozen | Honour it always | It must not be able to redirect a server's paths into a user profile |
| Cloud-secret checks for `server` role only; `create_app` refuses `worker` | Separate settings classes; drop the checks | A worker must hold no cloud secret, and a misconfigured server fails closed instead of starting unchecked |
| Registration never retried | `BaseAPIClient` default retry | A retried `POST /workers` whose response was lost mints a worker nobody holds the secret for |
| `rulebook_store._now` monkeypatched in the test | Change the store's ordering or tie-break | The defect was in the test's assumption, not the store; see §4.2 |

### Security reasoning reviewed by the lead

* `ProcessRole` defaults to `worker` when frozen, `server` otherwise. Production guardrail checks
  apply to both roles; the cloud-secret checks (`AUTH_SESSION_SECRET`,
  `WORKER_BUNDLE_ENCRYPTION_SECRET`) apply to `server` only. The secret properties remain
  fail-closed at use time in production regardless of role.
* Setup order: credential store probed before any network call; `https://` enforced (loopback
  exempt) **before** the password prompt; password via `getpass`, held as `SecretStr`, never
  logged or written; verify key fetched and kid-checked before registration; credential stored,
  then `worker.env` written atomically.

---

## 4. Bugs found and fixed

1. **The worker's import closure contained the engine.** 11 engine modules
   (`page_classifier` x6, `contracts` x5) loaded with the worker CLI, so PyInstaller would have
   bundled the classification cascade and the issue catalogue into every teammate's
   executable. Two incidental imports were responsible: `url_list.py` (three stdlib URL helpers
   from `url_rules`, whose package `__init__` imports the cascade) and `upload_manifest.py`
   (`ISSUE_CATALOGUE`, used only to compute a filename set). Shown to bite by the fail-before in
   §1. Build-log 0133 §6.9 located these two imports correctly.
2. **Flaky test: `tests/modules/seo/deliverables/test_rulebook_store.py::TestGetListDelete::test_list_all_is_unfiltered_and_newest_first`**
   (`90b59a3`). Two back-to-back `create()` calls can share one Windows clock tick; equal
   `created_at` values have no defined order, so "newest first" was not guaranteed. Measured
   5 failures in 30 standalone runs before; the test now monkeypatches `rulebook_store._now`
   with strictly increasing times; 0 in 30 after. Application code unchanged. It was the single
   failure in the builder's first gate run and again in the lead's first full run. The test was
   wrong, not the store: the store never promised an order for equal timestamps.
3. **Durable worker state would have reset on every launch of a frozen build.** Every path was
   `REPO_ROOT`-relative, which inside a bundle is read-only or a temp directory. The
   consumed-jobs ledger (ADR 0015's single-use protection across restarts) and the
   orphan-process ledger would have been lost silently. Fixed by `app_paths.py`; not observed in
   a real frozen build because none exists yet.
4. **A worker with `ENVIRONMENT=production` refused to boot without cloud-only secrets**
   (`AUTH_SESSION_SECRET`, `WORKER_BUNDLE_ENCRYPTION_SECRET`), which a worker must never hold.
   Fixed by the process role.

---

## 5. Corrections

1. **`docs/ARCHITECTURE.md` described `upload_manifest.ALLOWED_BUNDLE_FILENAMES` as "derived
   from `contracts/catalogue.py`'s `sf_sources`".** The set is still equal to that derivation,
   but it is now held as literals in `bundle_filenames.py` and pinned by a test, not computed
   from an import. Updated in this change.
2. **`docs/ARCHITECTURE.md` said `worker_daemon_cli.py` reads "the cloud URL/worker id/secret
   from Settings".** True for a checkout's default path only. A frozen worker reads the
   credential from Windows Credential Manager and ignores `WORKER_CREDENTIAL`. Updated.
3. **`docs/ARCHITECTURE.md`'s gap row "A UI to register a worker machine, and a packaged worker"
   said Phase 2 was "not started".** Phase 2 is done; the row now says so and keeps Phase 3 and
   the register-a-machine UI as open.
4. **Build-log 0133 §6.9 listed "first-run token prompt"** as the Phase 2 credential step. What
   shipped is an operator sign-in (URL, operator id, password, PC name) that registers the
   machine; no token is pasted. 0133 is left as written.

---

## 6. Explicitly not done

1. **No explicit Windows ACL on the worker data directory.** It inherits `%LOCALAPPDATA%`'s ACL
   (user, SYSTEM, Administrators). `ensure_private_dir`'s mode `0o700` is ignored on Windows.
   Accepted because nothing secret is stored there.
2. **No uninstall or sign-out command.** Removing the Credential Manager entry and the data
   directory is manual.
3. **No template delivery to a frozen worker.** The operator still places `.seospiderconfig`
   files in `templates/screaming_frog/` under the data root.
4. **Setup does not revoke the worker it replaces.** Re-running setup deletes the old local
   credential and tells the operator to revoke the old worker in the dashboard (ADR 0029); the
   old registration stays valid server-side until they do.
5. **Phase 3 not started**: no PyInstaller onedir spec, no GitHub Actions Windows build on a
   release tag, no dashboard download with SHA-256, unsigned pilot, no auto-updater. **HITL is
   required before any CI workflow or release** is added.
6. **The real `win32cred` path** is exercised by one integration test on Windows; everything else
   uses an in-memory fake vault. Non-Windows frozen builds are unsupported by design.
7. **Rulebook ordering on equal `created_at`** remains undefined in `RulebookStore.list_all()`.
   Only the test was fixed; two rulebooks created within one clock tick can still list in either
   order. Not observed as a user-facing problem.
8. **Still open from earlier cycles**: `DiskWorkerStore` wipes other registrations after loading
   a corrupt file ([build-log 0134 §4](0134-a-tutor-that-explains-every-decision.md)); the
   ADR 0028 key runbook has not been run by the operator, so existing desktops still hold the
   HMAC secret ([build-log 0133 §6.1](0133-a-key-every-verifier-could-sign-with.md)).

### Handoff: pre-existing mypy error outside the gate

`mypy src scripts` reports:

```
scripts\export_ui_contract.py:241: error: Need type annotation for "member"  [var-annotated]
```

The file was not touched by this branch. The official gate (`verify.ps1`) runs `mypy src` only,
which is why it is green. Not fixed here; recorded for a `bug-fixer` pass.

---

## 7. Files changed

`302f1d1` (25 files, +2,390 / −123): `.env.example`,
`docs/adr/0030-the-worker-ships-as-a-standalone-client.md` (new), `pyproject.toml`,
`scripts/register_worker.py`, `src/api/server.py`, `src/core/app_paths.py` (new),
`src/core/config.py`, `src/core/credential_vault.py` (new), `src/core/url_hosts.py` (new),
`src/integrations/worker_registration_client.py` (new),
`src/modules/seo/page_classifier/url_rules.py`,
`src/modules/seo/screaming_frog_control/{bundle_filenames.py (new), upload_manifest.py, url_list.py, worker_daemon_cli.py, worker_setup.py (new)}`,
and tests: `tests/api/test_server_process_role.py`, `tests/core/test_app_paths.py`,
`tests/core/test_credential_vault.py`, `tests/core/test_url_hosts.py`,
`tests/integrations/test_worker_registration_client.py`,
`tests/modules/seo/screaming_frog_control/{test_bundle_filenames.py, test_worker_daemon_cli.py, test_worker_import_boundary.py, test_worker_setup.py}`.

`2b5f1cd`: merge of `origin/main` `36fe70b` (cycle 0134's tutor tooling); it touched none of this
cycle's files.

`90b59a3` (1 file, +12 / −2): `tests/modules/seo/deliverables/test_rulebook_store.py`.

This entry: `docs/build-log/0135-a-worker-that-carried-the-engine.md`,
`docs/build-log/README.md`, `README.md`, `docs/ARCHITECTURE.md`.

---

## 8. Follow-ups

* Phase 3, after a HITL review: PyInstaller onedir spec, release-tag Windows build, dashboard
  download with SHA-256.
* Run the ADR 0028 runbook before handing any packaged worker to a teammate; a fresh setup
  stores an Ed25519 verify key, but the cloud must have a stable private key first.
* Fix `scripts/export_ui_contract.py:241` and consider adding `scripts` to the gate's mypy run.
* `DiskWorkerStore` corrupt-file wipe (0134 §4).
