# ADR 0030: The worker ships as a standalone client

**Status**: APPROVED — Phase 2 of the worker distribution plan, approved by the operator
at the Step-3 review, 2026-10-02.

**Date**: 2026-10-02

**Amends**: [ADR 0015](0015-cloud-local-desktop-worker-architecture.md) (how a worker is
installed and where it keeps its state). Builds on
[ADR 0028](0028-dispatch-claims-are-signed-asymmetrically.md) (a worker holds only a
public verify key) and [ADR 0029](0029-a-worker-credential-is-revoked-or-rotated-never-reactivated.md)
(a worker credential can be withdrawn). Packaging itself is Phase 3 and is not decided here.

---

## Context

The Screaming Frog worker (`rankuno-worker`, entry point
`src/modules/seo/screaming_frog_control/worker_daemon_cli.py`) is going to non-technical
teammates as a Windows executable: no git clone, no Python, no `.env` file to edit. Three
things in the code made that unsafe or impossible.

1. **The worker's import closure held the engine.** Importing the CLI loaded 49 `src`
   modules, 11 of them engine code (`page_classifier.{__init__, cascading_pipeline,
   schemas, signal_parsers, url_rules, weights}`, `contracts.{__init__, audit, catalogue,
   issue_ids, url_normalizer}`). PyInstaller bundles exactly that closure, so the
   classification cascade and the issue catalogue would have shipped to every
   teammate's PC. Two imports were responsible: `url_list.py` took three pure-stdlib URL
   helpers from `page_classifier.url_rules` (whose package `__init__` eagerly imports the
   cascade), and `upload_manifest.py` imported `ISSUE_CATALOGUE` only to build a filename
   allow-list.
2. **Every durable path was `REPO_ROOT`-relative.** In a frozen build that is the bundle:
   read-only under Program Files, or a temp directory deleted on exit. The consumed-jobs
   ledger (ADR 0015's single-use protection across restarts) and the orphan-process
   ledger would have reset on every launch, silently.
3. **The credential lived in a plaintext file**, and installing meant running
   `scripts/register_worker.py` from a checkout. Separately, a worker that happened to
   set `ENVIRONMENT=production` refused to boot without `AUTH_SESSION_SECRET` and
   `WORKER_BUNDLE_ENCRYPTION_SECRET` — cloud secrets a worker must never hold.

## Decision

### 1. An engine-free import boundary, enforced by a test

- `safe_split`, `site_host` and `registrable_domain` move to `src/core/url_hosts.py`. They
  are domain-agnostic URL facts with no classification knowledge, so `core` is their
  correct home. `url_rules` re-exports the same function objects; no caller changes.
- The upload allow-list's catalogue filenames are written out as literals in
  `screaming_frog_control/bundle_filenames.py`. A test (which may import the catalogue —
  tests ship in no executable) asserts the literal set equals the catalogue-derived set
  in both directions, so adding a catalogue source fails CI until the allow-list is
  reviewed.
- `tests/modules/seo/screaming_frog_control/test_worker_import_boundary.py` imports the
  worker CLI and setup module **in a fresh subprocess** (in-process, `sys.modules` is
  shared by the whole pytest session and the check would be meaningless) and fails if
  any loaded `src` module is outside an **allowlist**: `src.core`, the three worker
  integration clients, and `screaming_frog_control`. An allowlist rather than a denylist
  so a new engine package is refused without anyone naming it.

Result: 49 modules / 11 engine → 44 modules / 0 engine.

### 2. Frozen-aware paths

`src/core/app_paths.py` holds one rule. Not frozen (a checkout, the tests, the cloud
server): `REPO_ROOT`, byte-for-byte as before, and nothing in the environment can change
that — so the server can never write into a user profile. Frozen (`sys.frozen`):
`%LOCALAPPDATA%\Rankuno\Worker`, or `RANKUNO_WORKER_HOME` (honoured only when frozen).
The environment read happens in `config.user_data_root()`, the one module allowed to
read it, and it has to happen before `Settings` exists because it decides which file
`Settings` loads.

Layout under the root: `worker.env` (non-secret config, the only env file a frozen build
reads), `logs/audit.jsonl`, `deliverables/output/`, `templates/screaming_frog/`,
`.process_ledger.json`, `.worker_consumed_jobs.json`. Server-only paths (`.orgs`,
`.operators`, `.workers`) are untouched. `trace.txt` was already home-relative.

**Permissions.** Directories are created with mode `0o700`, which POSIX enforces and
Windows ignores. On Windows they inherit `%LOCALAPPDATA%`'s ACL (user, SYSTEM,
Administrators); no explicit DACL is written. This is acceptable because nothing in the
directory is secret.

### 3. The credential lives in Windows Credential Manager

Target `Rankuno Worker/<worker_id>`, generic credential, `CRED_PERSIST_LOCAL_MACHINE`
(DPAPI-encrypted, per user, never roams). Every `win32cred` call is in
`WindowsCredentialVault` (`src/core/credential_vault.py`); everything else uses the
`CredentialVault` protocol. Precedence, implemented once in `resolve_worker_credential`:

1. **Frozen**: Credential Manager only. A `WORKER_CREDENTIAL` in any env file is ignored
   with a warning. Off Windows this is an error, never a plaintext fallback.
2. **Checkout with `WORKER_CREDENTIAL_STORE=credential_manager`**: vault first, then
   `WORKER_CREDENTIAL`.
3. **Checkout default**: `WORKER_CREDENTIAL`, unchanged.

### 4. Sign in once

`rankuno-worker setup` (and the first interactive launch of a frozen build with no
`worker.env`) asks for the Rankuno URL (default production; `https://` required except
loopback, checked *before* the password prompt), operator id, password (`getpass`), and
a name for the PC. It checks the vault is usable before any network call, signs in,
fetches and kid-checks the verify key **before** registering (so a cloud that cannot sign
with Ed25519 stops setup before a one-time credential is minted), registers, stores the
credential, then writes `worker.env` atomically. All HTTP goes through
`WorkerRegistrationClient(BaseAPIClient)`; registration is never retried, because a
retried `POST /workers` whose response was lost mints a worker nobody holds the secret
for. The password is never logged or written. Re-running setup asks before replacing,
deletes the old local credential, and tells the operator to revoke the old worker
(ADR 0029) — the client cannot. In a checkout `setup` is refused;
`scripts/register_worker.py` is unchanged apart from sharing two constants.

### 5. Cloud-only checks apply to the server only

`Settings.rankuno_process_role` (`server` | `worker`, env `RANKUNO_PROCESS_ROLE`) defaults
to `worker` when frozen, `server` otherwise. Production's guardrail checks apply to both;
the cloud-secret checks apply to `server` only. `create_app` refuses to start under the
`worker` role, so the relaxation cannot reach the API. The secret properties remain
fail-closed at use time in production regardless.

## Alternatives considered

- **`keyring` instead of `win32cred`.** A new dependency whose backend is chosen at
  runtime through entry points: awkward to freeze, and on a misconfigured machine able to
  select a weaker backend without saying so. pywin32 is already the worker's Windows
  dependency.
- **A denylist boundary test.** Misses the next engine package by construction.
- **Keeping the catalogue import and excluding `contracts` at freeze time.** Moves the
  boundary into PyInstaller config where no test sees it, and the worker would then fail
  at import.
- **Reading `LOCALAPPDATA` inside `app_paths`.** Violates CLAUDE.md §1.3; the read is
  confined to `config.py` and passed in.

## What decompiling the executable reveals

The worker protocol (endpoint paths, request shapes, the dispatch-claim format and its
verification), the Screaming Frog CLI arguments and the bundle filename allow-list, and —
from a configured machine — the cloud's Ed25519 **public** key. None of that authorises
anything: the public key verifies but cannot sign (ADR 0028), and the worker credential
is in Credential Manager, not the bundle. No engine code, no catalogue logic, no cloud
secret is inside.

## Consequences

- A checkout, the test suite and the cloud server behave exactly as before; the only new
  server behaviour is refusing `RANKUNO_PROCESS_ROLE=worker`.
- A frozen worker's state survives restarts and upgrades in `%LOCALAPPDATA%`.
- `bundle_filenames.py` must be edited by hand when the catalogue gains a source; the
  drift test makes that impossible to forget.

## Explicitly not done

- **Packaging, CI and code signing** — no PyInstaller spec, no workflow, no signed build.
  Phase 3.
- **No explicit Windows DACL** on the data directory (inherited profile ACL only).
- **No uninstall or "sign out"** command; removing the Credential Manager entry and the
  data directory is manual.
- **No server-side revoke from the client** when setup replaces a registration.
- **Templates are not delivered** to a frozen worker's `templates/screaming_frog/`; the
  operator still places `.seospiderconfig` files there.
- The real `win32cred` path is exercised by one integration test on Windows; non-Windows
  frozen builds are unsupported by design.
