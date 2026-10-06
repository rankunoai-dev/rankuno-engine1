# Cycle 0138: A site that runs at home without touching production

- **Date**: 2026-10-06
- **Scope**: A one-command local launcher for the whole site, API and built React UI, on the
  workstation, so large crawls are not bound by the Railway container's memory
  (`scripts/run_local.ps1`, `scripts/local_preflight.py`). The design weight is on the guard: a
  local server must never reach the production database or cache, and the launcher proves that in
  the server's own environment before anything listens
  ([ADR 0032](../adr/0032-a-local-server-never-reaches-a-shared-database.md)).
- **Commit**: `91fe9af` (launcher, "wip: local launcher (pre-merge)"), then merge `93c4ca4` of
  `origin/main` `0e8d0de`. Branch `local-launcher`. This entry and the docs changes in §7 are
  uncommitted at time of writing.
- **Quality gate**: builder's run GREEN (§1). The lead's independent gate on the merged branch was
  running when this entry was written.

**Numbering note**: the highest entry is `0137` in this worktree, on `origin/main` and across every
local branch; the main checkout's `docs/build-log/` stops at `0134`. `0138` was free everywhere.
ADR `0032` was likewise free (highest `0031` in this worktree and on `origin/main`, `0029` in the
main checkout).

## 0. Background

The user asked to run the whole website locally for large crawls, because Railway's memory limit
stops them. Since ADR 0031, a crawl on Railway stops `PARTIAL` at the 3072 MiB memory budget
(about 1,400 pages for a lone crawl of a site with ~1.1 MB pages) instead of being OOM-killed. The
workstation has 32,475 MiB of physical RAM.

The pre-implementation security audit returned **PASS WITH CONDITIONS**. The findings that shaped
the design:

| Finding | Consequence for the design |
| :--- | :--- |
| Nothing in code stops a local `create_app()` from reaching a production database. It picks `PostgresJobStore` whenever `is_configured()` is true, whatever `ENVIRONMENT` says | The guard has to live in the launcher, and has to be proven, not assumed |
| A server on the production database runs `PostgresJobStore.recover_orphans()` at startup, which marks every `QUEUED`/`RUNNING` row of the whole `jobs` table `FAILED`. No scope | The cost of a mistake is every in-flight production crawl |
| `Settings` and `PostgresSettings` load `.env` / `.env.local` (`PostgresSettings` cwd-relative). `postgres_config.py`, `redis_config.py` and `celery_config.py` also call `os.getenv` directly (M1, a CLAUDE.md §1 rule 3 violation) | Dotenv must be scanned, and process values must be set, not merely absent |
| `env -u DATABASE_URL` does not stop a dotenv `DATABASE_URL` (tested with pydantic-settings 2.14.2) | Unsetting is not a guard. Blanking is |
| `DATABASE_URL=""` in the process environment wins over dotenv and counts as unset | The blanking mechanism |
| `PostgresWorkerDispatchStore` is always built | Dispatch routes error locally; expected |

Retrospective: no database or Redis key exists today in any dotenv of the main checkout, of the 22
worktrees, or in the OS environment. Earlier local end-to-end runs therefore very likely did not
touch production (high confidence; the history of those files cannot be seen). `README.md` gives a
Railway SQL check for anyone who ran a server locally before this guard.

User decisions: memory budget 40% of RAM; `MAX_CONCURRENT_CRAWLS` stays 5; a generated bootstrap
password for operator `admin`, shown once; port 8000. Lead decisions: a dotenv
`CRAWL_MEMORY_BUDGET_MIB` is overridden by the launcher with a notice; an `ENVIRONMENT` key is
refused by name with a "comment out or delete" message; no silent venv fallback, so a checkout
without `.venv` must pass `-Python`.

---

## 1. Gate results

LEAD GATE (run by the lead on the merged branch `93c4ca4`, main venv, `import src` resolved to the worktree):

```
ruff format --check .                -> 610 files already formatted
ruff check .                         -> All checks passed!
mypy src                             -> Success: no issues found in 166 source files
mypy scripts/local_preflight.py      -> Success: no issues found in 1 source file
export_ui_contract.py --check        -> UI contract is up to date.
pytest --cov=src                     -> Required test coverage of 85.0% reached. Total coverage: 93.21%
                                        3977 passed, 2 skipped, 1 warning in 401.43s (0:06:41)
```

The figures below are the builder's and the lead's earlier partial checks.

The builder's full gate, as reported by the builder. Not re-run by the scribe:

```
ruff format --check .            608 files already formatted
ruff check .                     All checks passed!
mypy src                         Success: no issues found in 166 source files
mypy scripts/local_preflight.py  Success
drift_check                      PASSED (232 markdown files)
export_ui_contract.py --check    UI contract is up to date
pytest --cov=src                 3972 passed, 2 skipped; Total coverage: 93.19%
                                 (the builder counted the pass total from progress dots)
rankuno-ui npm test              Test Files 51 passed, Tests 632 passed
```

The lead's checks, as reported by the lead:

```
pytest tests/scripts/test_local_preflight.py   exit 0
run_local.ps1 -CheckOnly                        exit 0
  postgres configured : False
  environment         : development
  worker store        : disk
  memory budget       : 12990 MiB (40% of 32475 MiB physical RAM)
  concurrent crawls   : 5 (fair share 2598 MiB each)
  operator store empty: True
  UI                  : would build (dist is missing)
  would serve         : http://127.0.0.1:8000/
```

Refusal test, run by the lead: a throwaway `.env` in the worktree holding
`database_url=postgresql://dummy@db.invalid/x` produced, with exit 1 and the value not printed:

```
REFUSED: ...\.env defines DATABASE_URL: a local server must never reach a shared database or
cache. Comment out or delete the DATABASE_URL line in ...\.env.
```

The file was deleted afterwards.

Re-run by the scribe in this worktree with the main venv (`import src` resolved to
`...\.claude\worktrees\local-launcher\src\__init__.py`):

```
python -m pytest tests/scripts/test_local_preflight.py --no-cov
39 passed in 0.36s

ruff check scripts/local_preflight.py tests/scripts/test_local_preflight.py
All checks passed!
ruff format --check (same two files)
2 files already formatted
mypy --strict scripts/local_preflight.py
Success: no issues found in 1 source file

run_local.ps1 -CheckOnly -Python <main venv>      exit=0
Pre-flight passed:
  postgres configured : False
  environment         : development
  worker store        : disk
  memory budget       : 12990 MiB (40% of 32475 MiB physical RAM)
  concurrent crawls   : 5 (fair share 2598 MiB each)
  job store           : C:\Users\RankUno\Desktop\rankuno-engine1\.claude\worktrees\local-launcher\.jobs
  operator store empty: True
  UI                  : would build (dist is missing)
  would serve         : http://127.0.0.1:8000/
CheckOnly: nothing built, nothing started.
```

The scribe also reproduced the two facts the design rests on, in a scratch directory whose `.env`
held `database_url=postgresql://dummy@db.invalid/x` (pydantic-settings 2.14.2):

```
env -u DATABASE_URL  ->  PostgresSettings().is_configured() == True
DATABASE_URL=        ->  PostgresSettings().is_configured() == False
```

**Fail-before.** `test_control_without_blanks_the_dotenv_database_is_configured` asserts that a
dotenv `DATABASE_URL` with no blanks makes `is_configured()` true and `verify` exit 1. Its sibling
`test_empty_process_values_override_the_dotenv_database` asserts the blanks turn it false and
`verify` exit 0. The pair shows the guard, not the test setup, is what changes the answer.

**Smoke test** (builder, port 8899): `npm ci` and `vite build` ran; the log showed
`bootstrap_operator_created` for `admin`; `GET /api/v1/health` 200; `GET /` 200 with `index.html`;
login 200 and a wrong password 401; `GET /api/v1/jobs` 200 with a token and 401 without; no secret
string in the server log. The server was stopped by its own PID and the smoke-test data deleted.

---

## 2. What landed

**`scripts/local_preflight.py`** (new, 254 lines). The guard logic, in Python so the gate tests
it; the PowerShell script only orchestrates. Three subcommands:

- `scan` refuses a `.env` or `.env.local` naming `DATABASE_URL`, `POSTGRES_URL`,
  `DATABASE_PRIVATE_URL`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `REDIS_URL`, `REDIS_PRIVATE_URL` or
  `ENVIRONMENT`, or setting `WORKER_STORE_BACKEND=postgres`. The line pattern is case-insensitive
  and accepts an `export` prefix, because both settings classes are `case_sensitive=False` and
  python-dotenv accepts `export`. A bare `^KEY=` check would let `export database_url = x`
  through. Presence refuses, whatever the value. A dotenv `CRAWL_MEMORY_BUDGET_MIB` is a notice,
  not a refusal.
- `budget` returns `floor(RAM MiB × 0.40)` clamped to 256–65536 (the `Settings` bounds), or
  validates an explicit override as a whole number in range.
- `verify` builds the same settings objects `create_app()` will, from the same cwd and
  environment, and refuses unless Postgres is not configured, the environment is development, the
  worker store is disk, and the budget `Settings` resolved equals the one exported. It prints
  non-secret facts as JSON. Any non-`RuntimeError` is reported by type only, because a pydantic
  validation error echoes the offending input.

**`scripts/run_local.ps1`** (new, 297 lines). In order: interpreter (default
`<repo>\.venv\Scripts\python.exe`, or explicit `-Python`; no fallback) → `scan` → `budget` → child
environment (`DATABASE_URL`, `POSTGRES_URL`, `DATABASE_PRIVATE_URL`, `POSTGRES_PASSWORD`,
`REDIS_URL`, `REDIS_PRIVATE_URL` set to `""`; `WORKER_STORE_BACKEND=disk`;
`ENVIRONMENT=development`; `CRAWL_MEMORY_BUDGET_MIB`) → `verify` in that exact environment → UI
build if stale, with `VITE_API_BASE=/api/v1` and `npm ci` when `node_modules` is missing or older
than `package-lock.json`, then a scan of `dist` for secret names → a per-run 32-byte hex
`AUTH_SESSION_SECRET`, and a bootstrap password only when the operator store is empty → port check
on 127.0.0.1 → `uvicorn --factory src.api.server:create_app --host 127.0.0.1 --workers 1`. Child
processes are started through `ProcessStartInfo` rather than `$env:`, so the launcher's own
environment never holds a generated secret; its copies are removed after the server starts.
`-CheckOnly` runs every guard and starts nothing.

**`tests/scripts/test_local_preflight.py`** (new, 236 lines, 39 tests counting parametrised
cases). Covers every forbidden key, every spelling the settings accept, comments, the
`WORKER_STORE_BACKEND` value check, that no value reaches stdout or stderr, the budget arithmetic
and override validation, the `verify` fail-before / pass pair, a budget mismatch, a production
`ENVIRONMENT`, a postgres worker store in the process environment, and a PowerShell parse of
`run_local.ps1` (Windows only).

**`README.md`**: a new section "Running the full site locally for large crawls", a pointer to it
from the crawl section, and a status-table row.

---

## 3. Design decisions

ADR 0032 records the full reasoning. The points a later reader most needs:

**Blank, not unset.** `env -u` and `Remove-Item Env:` remove the process value and let the dotenv
value through. Setting the key to `""` wins over dotenv and is falsy both to pydantic and to the
direct `os.getenv` calls. This is the non-obvious part and the reason for an ADR.

**Proven, not assumed.** `verify` runs in the exact environment and cwd uvicorn gets, so a pass is
a statement about the server and not about the launcher. `PostgresSettings` reads a cwd-relative
dotenv; the launcher `Set-Location`s to the repo root and passes it as the working directory to
every child.

**Refuse by name.** Reading a database URL to decide whether it is "local" would put the value in
the launcher's memory and output. Presence is enough to refuse.

**Built UI, one origin.** One process on 127.0.0.1 serving `/api/v1` and `dist`, rather than
`npm run dev` beside uvicorn: nothing to die overnight, no hot-reload refresh mid-crawl, no CORS
split.

**Memory budget at 40% of RAM.** 12,990 MiB on this 32,475 MiB machine, a 2,598 MiB fair share
across 5 crawls. At the 2.2 MiB per page ADR 0031 measured for ~1.1 MB pages with any non-ASCII
character, that is about 5,900 pages across all running crawls, against about 1,400 for a lone
crawl on Railway. About 11,800 if every page is pure ASCII.

---

## 4. Bugs found and fixed

### 4.1 Errors in the builder's README section, fixed by the scribe

The README section was reviewed line by line against the two scripts. Four statements were wrong:

| README said | Fact | Fix |
| :--- | :--- | :--- |
| The server binds 127.0.0.1 "with one worker and no proxy headers" | The launcher passes no `--no-proxy-headers`. uvicorn 0.52.1 defaults to `proxy_headers=True` with `forwarded_allow_ips="127.0.0.1"`, checked with `uvicorn.config.Config`. No route in `src/api` reads `request.client`, so this has no effect today | Clause removed |
| "Values are never read or printed" | `scan` reads `WORKER_STORE_BACKEND`'s value to test for `postgres` | "No value is printed, and the only value read is `WORKER_STORE_BACKEND`'s" |
| "sets the four database keys to empty strings" | Six keys are blanked: four database, two Redis. `POSTGRES_HOST` is not among them | The six named |
| "On sites with ~1 MB pages it holds roughly 10–13k pages" | 12,990 MiB / 2.2 MiB = ~5,900. 10–13k holds only for pure-ASCII pages of 1.0–1.3 MiB. ADR 0031 and build-log 0136 put a ~1.1 MB page at 2.2 MiB once it contains one non-ASCII character | ~5,900 at 2.2 MiB/page, ~11,800 pure ASCII |

The README's other statements checked out: the storage paths (`.operators`, `.orgs`, `.workers`
anchored at `REPO_ROOT` in `config.py`; `.jobs` cwd-relative in `server.py`, and the launcher runs
from the repo root), the staleness rules, the `npm ci` rule, `scripts/create_operator.py`, the
`jobs` columns used by the SQL check (`id`, `status`, `finished_at`, `error`), and the
`recover_orphans` wording "interrupted by a server restart".

No defects were reported by the builder in the scripts themselves.

---

## 5. Corrections

### 5.1 The audit overstated what `POSTGRES_HOST` does

The security audit stated that `POSTGRES_PASSWORD` or `POSTGRES_HOST` also makes `is_configured()`
true. For `POSTGRES_PASSWORD` that is right. For `POSTGRES_HOST` it is not:
`PostgresSettings.is_configured()` (`src/core/postgres_config.py:84-90`) reads `database_url`, the
three URL environment variables and `postgres_password`, never the host. The scribe confirmed it: a
`.env` holding only `POSTGRES_HOST=db.invalid` gave `is_configured() == False` with
`postgres_host == "db.invalid"`.

`POSTGRES_HOST` still matters, through a different path: `get_connection_string()` builds a URL
from the host when no URL is set, and `PostgresWorkerDispatchStore`, always constructed, connects
with it lazily. Refusing it in a dotenv is therefore still right. It is **not** blanked in the
server's environment, and the OS environment is not scanned, so an OS-level `POSTGRES_HOST` would
reach the dispatch store, with an empty password. No such variable is set on this workstation.

### 5.2 The CLAUDE.md §1 rule 3 violation is wider than build-log 0110 recorded

[Build-log 0110](0110-what-the-gate-had-not-been-run-on.md) recorded that
`src/core/celery_config.py` reads `REDIS_URL` / `REDIS_PRIVATE_URL` through `os.getenv`, against
CLAUDE.md §1 rule 3. The same pattern is in `src/core/postgres_config.py` (`is_configured()` lines
86-88 and `get_connection_string()` lines 104-106: `DATABASE_URL`, `POSTGRES_URL`,
`DATABASE_PRIVATE_URL`) and `src/core/redis_config.py` (line 86). These direct reads are why
blanking the process value, not only the dotenv, is required. Not fixed in this cycle (§6).

---

## 6. Explicitly not done

- **No code-level guard.** `create_app()` still chooses `PostgresJobStore` whenever Postgres looks
  configured, in any `ENVIRONMENT`, and `recover_orphans()` still has no scope. A server started any
  way other than `run_local.ps1` is unguarded. Refusing a non-loopback database host when
  `ENVIRONMENT=development` is the auditor's follow-up.
- **M1 not refactored.** The `os.getenv` reads in `postgres_config.py`, `redis_config.py` and
  `celery_config.py` stay, and `PostgresSettings`' dotenv path stays cwd-relative rather than
  anchored at `REPO_ROOT`.
- **`POSTGRES_HOST` is not blanked, and the OS environment is not scanned** (§5.1).
- **`.env.local` in the main checkout still holds `WORKER_DISPATCH_SIGNING_SECRET`.** Only the
  name was checked. It may be a stale production HMAC secret; the ADR 0028 runbook applies. Not a
  database key, so the launcher does not refuse it.
- **The server does not log the effective memory budget at startup.** Only the launcher prints
  what `Settings` resolved, via `verify`.
- **SPA routes.** `create_app()` serves `index.html` at `/` and `/login` only. A browser refresh on
  a deep link was not tested.
- **`verify.ps1` cannot gate a worktree.** It assumes `.venv` in its own checkout; worktree gates
  are run with the main venv by hand.
- **The launcher has no behavioural test.** It is parse-checked on Windows; its behaviour rests on
  the lead's `-CheckOnly` and refusal runs and the builder's smoke test.
- **Local crawls are still bounded.** By the memory budget and the machine's RAM. Step 2 of the
  crawl memory work (not retaining page HTML until the job ends, ADR 0031) is not done; a large
  enough site will still stop `PARTIAL` locally.
- **Local and production data are never synced.** Jobs crawled locally do not appear on Railway,
  and the reverse. Screaming Frog dispatch errors locally because `PostgresWorkerDispatchStore` has
  no database.
- **No Dockerfile or hosted change.** ADR 0004 stands.

---

## 7. Files changed

From `git show --stat 91fe9af`:

| File | Change |
| :--- | :--- |
| `scripts/local_preflight.py` | new, 254 lines |
| `scripts/run_local.ps1` | new, 297 lines |
| `tests/scripts/test_local_preflight.py` | new, 236 lines |
| `README.md` | +94 (new section and crawl-section pointer) |

This cycle (docs, uncommitted):

| File | Change |
| :--- | :--- |
| `docs/build-log/0138-a-site-that-runs-at-home-without-touching-production.md` | this entry |
| `docs/build-log/README.md` | index row |
| `docs/adr/0032-a-local-server-never-reaches-a-shared-database.md` | new |
| `README.md` | four corrections (§4.1), ADR 0032 link, status-table row |
| `docs/ARCHITECTURE.md` | `server.py` note on the launcher, two planned-table rows (code-level guard, M1), ADR 0032 row |

`docs/ARCHITECTURE.md` has no `scripts/` listing; the launcher is described under `server.py`.
CLAUDE.md is unchanged.

---

## 8. Follow-ups

| Owner | Item |
| :--- | :--- |
| `security-auditor` / `bug-fixer` | Refuse a non-loopback database host in code when `ENVIRONMENT=development`, so the guard does not depend on the launcher |
| `refactorer` | M1: move the `os.getenv` reads in `postgres_config.py`, `redis_config.py`, `celery_config.py` into `Settings`; anchor `PostgresSettings`' dotenv at `REPO_ROOT` |
| `bug-fixer` | Blank `POSTGRES_HOST` (and consider `POSTGRES_USER` / `POSTGRES_PORT` / `POSTGRES_DATABASE`) in the launcher's child environment (§5.1) |
| operator | Check whether the main checkout's `.env.local` `WORKER_DISPATCH_SIGNING_SECRET` is the production HMAC key; follow the ADR 0028 runbook |
| `api-data-engineer` | Log the effective `crawl_memory_budget_mib` at server startup |
| `ui-engineer` / `api-data-engineer` | Serve `index.html` for SPA deep links, or confirm the UI never needs it |
| `refactorer` | Let `verify.ps1` take a `-Python` like the launcher, so a worktree can be gated |
| next crawl-memory cycle | Step 2: stop retaining page HTML (ADR 0031) |
