# Cycle 0139: A browser that opens already signed in

- **Date**: 2026-10-06
- **Scope**: `scripts/run_local.ps1` (cycle 0138) now opens the default browser already signed in,
  through a single-use, five-minute, loopback-only link, instead of stopping at the login screen.
  Server half in `src/core/local_signin.py` and `src/api/local_signin.py`; settings, a Postgres
  refusal and an opt-in Host allowlist in `config.py` / `server.py`; the SPA exchange in
  `useAuthStore.ts` / `App.tsx`. Also fixes a launcher defect that emptied another checkout's
  `node_modules` through a junction (§4.1).
  ([ADR 0033](../adr/0033-a-local-launch-signs-in-through-a-single-use-loopback-link.md))
- **Commit**: `0cf3d07` on `origin/main` `f8d0152`, branch `local-autosignin`. This entry and the
  docs changes in §7 are uncommitted at time of writing.
- **Quality gate**: GREEN — lead's run and builder's run (§1).

**Numbering note**: the highest build-log entry is `0138` in this worktree, on `origin/main`, on
every local branch and in every worktree under `.claude/worktrees/`, and in the main checkout.
`0139` was free everywhere. ADR `0033` was added by the builder in `0cf3d07`; the highest ADR on
`origin/main` is `0032`.

## 0. Background

The user's words: "do one thing for local crawling remove this creds things", with a screenshot
of the local login refusing `admin`.

Cause, found by the lead: the main checkout's only local operator was `claude-test-op` in org
`test-org`, a test artefact from 2026-09-16. The launcher seeds `admin` only on an empty operator
store (ADR 0016 bootstrap), so `admin` was never created there. The user's ~3,800 local crawls are
in org `default`. The lead gave an immediate workaround
(`scripts/create_operator.py --operator-id admin --org-id default`).

The lead explained that removing authentication from a loopback server would let any web page in
the same browser drive it: cross-site requests, DNS rebinding into a fetch proxy, and reading crawl
data. The user chose "auto sign-in on launch", approved the plan, and chose to keep bootstrap
`admin` seeding on empty stores.

The pre-implementation security audit returned **PASS WITH CONDITIONS** (C1-C18; C17, the Host
allowlist, was recommended and the lead put it in scope). The findings that shaped the design:

| Finding | Consequence for the design |
| :--- | :--- |
| `Settings.environment` defaults to `DEVELOPMENT` | A development-only validator alone would not protect a Railway service whose `ENVIRONMENT` was unset. Hence a second, independent refusal on Postgres, plus the loopback and single-use layers |
| The session is a bearer token in `localStorage`; no cookies; CORS is an exact allowlist | No ambient credential a cross-site page could ride; the new route must not add one |
| No Host or Origin check existed | DNS rebinding could reach the local server under a foreign Host. C17: `TrustedHostMiddleware` |
| uvicorn's access log records the query string | The token cannot travel in a query string. It travels in the fragment |
| FastAPI's 422 echoes the input | No `pattern=` on the request field or the `Settings` field; shape checks raise messages that carry no value |
| `Start-Process` / `Process.Start` put the URL, fragment included, on the browser's command line | Residual, accepted: neutralised by single use and the 5-minute TTL |

---

## 1. Gate results

LEAD GATE (run by the lead on commit `0cf3d07` in this worktree, main venv, `import src` resolved to the worktree):

```
ruff format --check .                -> 620 files already formatted
ruff check .                         -> All checks passed!
mypy src                             -> Success: no issues found in 168 source files
mypy scripts/local_preflight.py      -> Success: no issues found in 1 source file
export_ui_contract.py --check        -> UI contract is up to date.
pytest --cov=src                     -> Required test coverage of 85.0% reached. Total coverage: 93.28%
                                        4064 passed, 2 skipped, 1 warning in 1044.46s (0:17:24)
```

(The builder reported 93.30% on its run; the lead's run measured 93.28%.)

The builder's final gate, as reported by the builder. Not re-run by the scribe:

```
ruff format --check .            620 files already formatted
ruff check .                     All checks passed!
mypy src                         Success: no issues found in 168 source files
mypy scripts/local_preflight.py  Success
pytest --cov=src                 4064 passed, 2 skipped; Total coverage: 93.30%
drift_check                      PASSED (235 markdown files)
export_ui_contract.py --check    UI contract is up to date
rankuno-ui tsc                   0 errors
rankuno-ui vitest                Test Files 51 passed, Tests 642 passed
```

Against cycle 0138's lead gate (3977 passed, 93.21%), +87 Python tests. That matches the new tests
counted below (25 + 11 + 26 + 8 + 17).

Re-run by the scribe in this worktree with the main venv (`import src` resolved to
`...\.claude\worktrees\local-autosignin\src\__init__.py`):

```
pytest tests/core/test_local_signin.py tests/core/test_config_local_signin.py
       tests/api/test_local_signin.py tests/api/test_local_signin_operator.py
       tests/scripts/test_local_preflight.py --no-cov
126 passed, 1 warning in 25.56s

--collect-only -qq
tests/api/test_local_signin.py: 25
tests/api/test_local_signin_operator.py: 11
tests/core/test_config_local_signin.py: 26
tests/core/test_local_signin.py: 8
tests/scripts/test_local_preflight.py: 56        (39 at cycle 0138, so +17)

ruff check (the 11 changed Python files)          All checks passed!
ruff format --check (same)                        11 files already formatted
mypy --strict src/core/local_signin.py src/api/local_signin.py scripts/local_preflight.py
                                                  Success: no issues found in 3 source files
git ls-files --eol (same)                         11 w/lf
```

The one warning is the pre-existing Starlette `httpx` deprecation from `fastapi.testclient`.

**Fail-before** (builder, against unmodified `HEAD` via `git archive`):

| Probe | Result on `HEAD` |
| :--- | :--- |
| Route off/on | `assert 404 == 200` |
| Host allowlist, foreign Host | `assert 200 == 400` |
| Config tests | `AttributeError`, `DID NOT RAISE`, and a production token raising the `AUTH_SESSION_SECRET` message instead of the token message |
| C14, no token in any log | Cannot run on `HEAD` (module absent). Equivalent: mutating the success log to include the token makes the test fail |
| SPA store tests on the `HEAD` store | 8 failed, 10 passed; all 8 sign-in-link tests fail |

**Smoke test** (builder, scratch uvicorn on port 8898 with an in-process token): 15 of 15 checks
passed, including: SPA served; wrong token 401; right token 200 with org `default`; the session
works on `/jobs`; reuse 401; `Host: evil.example` 400; password login as `local` 401;
`local_signin_succeeded` logged; the token absent from stdout, stderr, the access log and the
audit log.

**Real launcher run** (builder, port 8898): the console showed no fragment (0 matches for
`autosignin=`, no run of 64 or more hex characters). `local_signin_succeeded` appeared exactly
once: the default browser opened and signed in. The access log showed
`POST /api/v1/auth/local-signin 200` then `GET /api/v1/jobs 200`, with no query strings. The server
was stopped by its own PID. This run is also where the §4.1 incident happened.

---

## 2. What landed

From `git show --stat 0cf3d07`: 17 files, +1,821 / -28.

**`src/core/local_signin.py`** (new, 107 lines). `LocalSigninGate` holds `sha256(token)`, never
the token. `redeem()` runs check, `hmac.compare_digest` and consume in one `threading.Lock`
critical section and returns a `SigninOutcome` (`ok`, `mismatch`, `expired`, `consumed`,
`locked`), whose values double as log categories. TTL 300 s from construction, which is app
construction. `MAX_FAILURES = 5` disarms it for the life of the process. Injectable monotonic
clock, so the tests do not sleep.

**`src/api/local_signin.py`** (new, 192 lines). `POST /auth/local-signin`, built by
`build_local_signin_router()`. Order: loopback peer (`request.client.host`) **and** loopback-bound
socket (`scope["server"]`), else 401 `not_loopback` → rate-limit bucket `local-signin`, 10 per
minute, else 429 → `gate.redeem()` → re-read the operator; it must still exist, be active and be in
the configured org, else 401 `operator_unavailable` → `issue_session_token()` with the same TTL as
`/auth/login`, returning the same `LoginResponse`. Every refusal is
`401 {"detail": "sign-in link is invalid or expired"}`. Because the loopback check runs before the
rate limiter and the gate, a refused remote request does not spend the link (tested).
`LocalSigninRequest.token` has `max_length=256` and no pattern. `ensure_local_operator()` creates
`local` with `hash_password` of 32 random bytes that are then discarded, or raises
`ConfigurationError` if the operator exists but is inactive or in another org. It never picks an
existing operator.

**`src/core/config.py`** (+86). `auth_local_autosignin_token` (`SecretStr | None`; empty string
reads as unset), `auth_local_autosignin_operator_id` (default `local`),
`auth_local_autosignin_org_id` (default `default`), both `^[a-z0-9_-]{1,64}$`, and
`api_allowed_hosts` with an `api_allowed_host_list` property. `_check_local_autosignin()` runs
first in `model_post_init`: a token outside `ENVIRONMENT=development` raises, and so does one that
is not 64-256 hex characters. Neither message carries the value.

**`src/api/server.py`** (+47 / -2). `create_app()` refuses a token while
`get_postgres_settings().is_configured()` is true, after the existing `WORKER` role refusal (a
test pins that order). After `_seed_bootstrap_operator`, so an empty store still gets `admin`
first, it calls `ensure_local_operator`, arms the gate and logs `local_signin_armed`. It mounts
`TrustedHostMiddleware` only when `API_ALLOWED_HOSTS` is set, so TestClient's `testserver` and
Railway are unaffected, and includes the router only when the gate exists, so the path is a 404
otherwise.

**`rankuno-ui/src/store/useAuthStore.ts`** (+95 / -17, now 261 lines) and **`App.tsx`** (+4).
`captureSignInLink()` runs at module load: it reads `#autosignin=`, strips the fragment with
`history.replaceState` whatever its value, and keeps a token matching `^[0-9a-f]{64,256}$/i` in a
module-local variable only. `signInWithLink()` posts it once in a JSON body and stores the session
through the same `storeSession()` path `login()` now uses. Any failure (401, 429, network, bad
body) sets one generic message and falls through to the normal `LoginScreen`. `App` awaits
`signInWithLink()` before `chooseAdapter()`, so the first authenticated request already has a
session.

**`scripts/run_local.ps1`** (+97 / -5, now 389 lines). `-NoAutoSignIn`, `-AutoSignInOperatorId`,
`-AutoSignInOrgId` (validated `^[a-z0-9_-]{1,64}$`). The child environment always gets
`API_ALLOWED_HOSTS=127.0.0.1,localhost` and `AUTH_LOCAL_AUTOSIGNIN_TOKEN=""`, so a token inherited
from the shell cannot switch the route on. Unless `-NoAutoSignIn`, `New-HexSecret 32` fills it in.
The token is removed from `$psi` and `$childEnv` once the server starts. The launcher polls
`/api/v1/health` (60 s), opens the URL through `[System.Diagnostics.Process]::Start` with
`UseShellExecute = $true`, which keeps the URL out of PowerShell module logging (event 4103), then
clears its own variable. It prints only `http://127.0.0.1:<port>/`. `-CheckOnly` reports
`auto sign-in : on, as '<id>' in org '<org>'` or `off (-NoAutoSignIn)`.
`AUTH_LOCAL_AUTOSIGNIN_TOKEN` was added to the names `dist` is scanned for.

**`scripts/local_preflight.py`** (+89 / -3, now 340 lines). `scan` refuses a dotenv naming
`AUTH_LOCAL_AUTOSIGNIN_TOKEN`, with its own message. New subcommand `ui-deps` (§4.1).

**Tests** (new): `tests/core/test_local_signin.py` (8, including a racing-threads test that
asserts exactly one success), `tests/core/test_config_local_signin.py` (26),
`tests/api/test_local_signin.py` (25), `tests/api/test_local_signin_operator.py` (11),
`tests/api/local_signin_support.py` (82-line helper module), +17 in
`tests/scripts/test_local_preflight.py`, and additions to `App.test.tsx` and
`useAuthStore.test.ts`.

---

## 3. Design decisions

ADR 0033 records the reasoning. The points a later reader most needs:

**A link, not no login.** Removing authentication when `ENVIRONMENT=development` is one wrong
environment variable away from a password-free production server, and on loopback it still lets a
web page drive the server. The link keeps authentication and removes only the typing.

**Fragment, not query string.** A browser never sends a fragment, so no access log, proxy or
`Referer` sees it. The SPA strips it before its first request.

**Layers that do not depend on each other.** `Settings` refuses the token outside development;
`create_app()` refuses it whenever Postgres is configured; the route answers only a loopback peer
on a loopback-bound socket; the token is per-launch, single use and 5 minutes. The second layer
exists because `ENVIRONMENT` defaults to development. The socket check exists because a peer
address alone can be rewritten (see §5.1).

**A dedicated operator, created alongside others.** This departs from bootstrap's
empty-store-only rule (ADR 0016). The alternative, signing in as whichever operator exists, would
have signed the user into `test-org` as `claude-test-op` in the very checkout that prompted this
cycle.

**One 401.** The response does not say whether the token was wrong, spent, expired, locked out or
from the wrong address. The log does, by category.

---

## 4. Bugs found and fixed

### 4.1 The launcher emptied the main checkout's `node_modules` through a junction

During the builder's real launcher run, the worktree's `rankuno-ui\node_modules` was a junction to
the main checkout's. Cycle 0138's step 5 decided `node_modules` was stale, because the worktree's
`package-lock.json` was newer by mtime than the main checkout's `node_modules\.package-lock.json`,
and ran `npm ci`. `npm ci` deletes `node_modules` first, and the deletion went **through the
junction**: the main checkout's `node_modules` was emptied. It is gitignored; no tracked file was
touched.

The lead restored it by moving the worktree's freshly installed copy into the main checkout. The
two lockfiles were the same blob (`25e6121`), so the installed tree was the one main expected.

Fix in this change: the staleness decision moved out of PowerShell into a tested
`local_preflight.py ui-deps --ui-dir <dir>`, which prints `current` or `install`, or exits 1 with:

```
REFUSED: node_modules is a link to another folder; refusing to reinstall through it. Run npm ci in the link target, or remove the link.
```

A link is a symlink or any Windows reparse point (`FILE_ATTRIBUTE_REPARSE_POINT`). A link that is
current is allowed, because `vite build` only reads it. The staleness rule itself is unchanged.
The tests create real junctions in `tmp_path`. `-CheckOnly` now reports
`would REFUSE (node_modules is a link that needs reinstalling)` when it applies.

### 4.2 CRLF written into LF files

The builder's Python edits briefly wrote CRLF line endings into LF files. Caught and normalised
before the gate. All 11 changed Python files are `w/lf` (§1).

### 4.3 vitest wrote a cache through the same kind of junction

Running vitest in the worktree wrote a `.vite` cache into the main checkout's `node_modules`
through the junction. Harmless and gitignored, but the same mechanism as §4.1: anything that writes
under a linked `node_modules` writes into the other checkout.

### 4.4 Not a code bug: the login refusal that started this cycle

The refusal of `admin` was correct behaviour. `admin` did not exist in that store, because
bootstrap seeds only an empty store and the store held a test operator. It is recorded because it
explains why the sign-in link uses a named operator rather than the first one it finds.

---

## 5. Corrections

### 5.1 Cycle 0138's "no route reads `request.client`" is no longer true

[Build-log 0138 §4.1](0138-a-site-that-runs-at-home-without-touching-production.md) removed a
README clause about proxy headers on the grounds that uvicorn 0.52.1 defaults to
`proxy_headers=True` with `forwarded_allow_ips="127.0.0.1"`, and that "No route in `src/api` reads
`request.client`, so this has no effect today." `src/api/local_signin.py` now reads it.

The scribe checked the effect in uvicorn 0.52.1's `ProxyHeadersMiddleware`: when the peer is in
`forwarded_allow_ips`, `X-Forwarded-For` replaces `scope["client"]`. Locally, the peer is
`127.0.0.1`, so a local client sending `X-Forwarded-For: <remote address>` turns itself into a
non-loopback client and is refused: it fails closed. A remote peer's header is ignored. On
Railway the bind is `0.0.0.0`, so even if `FORWARDED_ALLOW_IPS` were widened and a client spoofed
`X-Forwarded-For: 127.0.0.1`, the bound-socket check still refuses. This is the reason the route
checks the socket as well as the peer. No test drives uvicorn's proxy middleware; TestClient does
not run it (§6).

### 5.2 ADR 0033's "not verifiable from the repo" is partly verifiable

ADR 0033 asks the operator to confirm that Railway sets `ENVIRONMENT=production`, and the lead's
brief called it not verifiable from the repo. Part of it is: `railway.toml` builds with
`builder = "dockerfile"`, and the `Dockerfile` (line 52) sets `ENV ENVIRONMENT=production` before
its `CMD`. The image default is therefore production. What the repo cannot show is whether a
Railway service variable overrides it, which is the narrower thing the operator must check. The
ADR was not edited.

---

## 6. Explicitly not done

- **Railway's `ENVIRONMENT` not confirmed by the operator.** The image sets it (§5.2); a service
  variable could override it. ADR 0033 layer 1 assumes production; layers 2-4 hold without it.
- **Same-machine reverse proxy.** A proxy on the workstation forwards from loopback and would pass
  the peer and socket checks. The Host allowlist and single use still apply. Documented limit; do
  not front the local server with a proxy.
- **The browser's command line holds the spent URL**, fragment included, while it runs; visible to
  same-user processes and to process-creation auditing (event 4688 with command lines, Sysmon).
  Residual, accepted.
- **422 echo.** A malformed body (extra field, non-string, over 256 characters) gets FastAPI's
  default 422, which echoes the input. A well-formed request never triggers it.
- **No test drives uvicorn's proxy-header middleware** against the loopback check (§5.1). The
  analysis is from uvicorn's source, not a test.
- **A malformed `#autosignin=` value shows no message.** The SPA strips it, but a value that is not
  64-256 hex is dropped before any request, so the operator sees the plain login screen without the
  "link has expired" message. ADR 0033 §1 says every failure gets the generic message; this case
  does not.
- **The `claude-test-op` operator remains** in the main checkout's `.operators/`. It is user data;
  not removed.
- **`config.py` (1,241 lines) and `server.py` (4,022 lines) remain far over the 400-line target.**
  Pre-existing; this cycle added to both.
- **`verify.ps1` still cannot gate a worktree.** Worktree gates are run with the main venv by hand
  (cycle 0138 follow-up).
- **SPA deep-link refresh** not covered. Pre-existing (cycle 0138 §6).
- **`API_ALLOWED_HOSTS` is not set in production.** It is a general setting; nothing sets it on
  Railway.
- **The launcher still has no behavioural test.** Its sign-in step rests on the builder's real run.

---

## 7. Files changed

From `git show --numstat 0cf3d07`:

| File | Change |
| :--- | :--- |
| `docs/adr/0033-a-local-launch-signs-in-through-a-single-use-loopback-link.md` | new, 144 lines |
| `src/core/local_signin.py` | new, 107 lines |
| `src/api/local_signin.py` | new, 192 lines |
| `src/core/config.py` | +86 |
| `src/api/server.py` | +47 / -2 |
| `scripts/run_local.ps1` | +97 / -5 |
| `scripts/local_preflight.py` | +89 / -3 |
| `rankuno-ui/src/store/useAuthStore.ts` | +95 / -17 |
| `rankuno-ui/src/App.tsx` | +4 |
| `rankuno-ui/src/App.test.tsx` | +54 / -1 |
| `rankuno-ui/src/store/useAuthStore.test.ts` | +129 |
| `tests/api/local_signin_support.py` | new, 82 lines |
| `tests/api/test_local_signin.py` | new, 239 lines |
| `tests/api/test_local_signin_operator.py` | new, 138 lines |
| `tests/core/test_config_local_signin.py` | new, 98 lines |
| `tests/core/test_local_signin.py` | new, 93 lines |
| `tests/scripts/test_local_preflight.py` | +127 |

This cycle (docs, uncommitted):

| File | Change |
| :--- | :--- |
| `docs/build-log/0139-a-browser-that-opens-already-signed-in.md` | this entry |
| `docs/build-log/README.md` | index row |
| `README.md` | local-site section: auto sign-in, `-NoAutoSignIn`, `-AutoSignInOperatorId` / `-AutoSignInOrgId`, `API_ALLOWED_HOSTS`, the dotenv token refusal, the linked-`node_modules` refusal, bootstrap interaction; status-table row |
| `docs/ARCHITECTURE.md` | `core/local_signin.py` and `api/local_signin.py` entries, `server.py` note, ADR 0033 row |

CLAUDE.md is unchanged.

---

## 8. Follow-ups

| Owner | Item |
| :--- | :--- |
| operator | Confirm no Railway service variable overrides the image's `ENVIRONMENT=production` (§5.2) |
| `test-engineer` | A test that runs the route behind uvicorn's `ProxyHeadersMiddleware` with `X-Forwarded-For`, local and spoofed (§5.1) |
| `ui-engineer` | Show the generic message when a malformed `#autosignin=` value is dropped, or amend ADR 0033 §1 (§6) |
| operator | Decide whether to remove `claude-test-op` / `test-org` from the main checkout's `.operators/` |
| `refactorer` | `verify.ps1 -Python`, so a worktree can be gated (carried from 0138) |
| `refactorer` | Split `config.py` and `server.py` toward the 400-line target |
