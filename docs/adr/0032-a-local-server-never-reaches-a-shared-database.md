# ADR 0032: A local server never reaches a shared database, and proves it before it listens

- **Status**: Accepted
- **Date**: 2026-10-06
- **Deciders**: AI Lead, Lead AI Systems Engineer (user approved running the full site locally,
  the 40% memory budget, port 8000 and the generated bootstrap password)

---

## Context

The user wanted to run the whole site, API and UI, on the workstation, because the Railway
container's memory limit stops large crawls (ADR 0031). The crawl itself is not the risk. The risk
is a workstation process that quietly reaches the production database or cache.

The pre-implementation security audit (PASS WITH CONDITIONS) found:

1. **Nothing in code stops a local `create_app()` from using the production database.**
   `create_app()` chooses `PostgresJobStore` whenever `get_postgres_settings().is_configured()` is
   true. `ENVIRONMENT=development` does not change that.
2. **Startup on the production database would fail every production job in flight.**
   `PostgresJobStore.recover_orphans()` runs at startup and marks every `QUEUED`/`RUNNING` row in
   the whole `jobs` table `FAILED` "interrupted by a server restart". It has no scope: it cannot
   tell its own jobs from the Railway container's.
3. **Dotenv files are read implicitly.** `Settings` and `PostgresSettings` both load `.env` and
   `.env.local`; `PostgresSettings` reads them relative to the current directory.
   `is_configured()` and `get_connection_string()` also call `os.getenv("DATABASE_URL")`,
   `POSTGRES_URL` and `DATABASE_PRIVATE_URL` directly, as do `redis_config.py` and
   `celery_config.py` (a CLAUDE.md §1 rule 3 violation, finding M1).
4. **`env -u DATABASE_URL` is not a guard.** Removing a key from the process environment leaves
   the dotenv value in force, and pydantic-settings then reads it. Tested by the auditor with
   pydantic-settings 2.14.2, and again by the scribe for build-log 0138: with a `.env` holding
   `database_url=postgresql://dummy@db.invalid/x`, `env -u DATABASE_URL` gave
   `is_configured() == True`, and `DATABASE_URL=` (empty) gave `False`.
5. **An empty process value wins.** pydantic-settings gives the process environment priority over
   dotenv, an empty string makes the `SecretStr | None` field falsy, and `os.getenv` returns `""`,
   which is also falsy. So `DATABASE_URL=""` in the child's environment counts as unset even when a
   dotenv names a real URL.
6. `PostgresWorkerDispatchStore` is always constructed. It connects lazily, per call.

A retrospective check found no database or Redis key in any dotenv of the main checkout or the 22
worktrees, nor in the OS environment, so earlier local end-to-end runs very likely did not touch
production. That is high confidence, not proof: the history of those files is not visible.

## Decision

**A local server must never reach a shared database or cache. The launcher proves this in the
server's own environment before anything listens.** The rule is enforced by
`scripts/run_local.ps1`, with the testable logic in `scripts/local_preflight.py`:

1. **Refuse by name.** `local_preflight.py scan` refuses a `.env` or `.env.local` that names
   `DATABASE_URL`, `POSTGRES_URL`, `DATABASE_PRIVATE_URL`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`,
   `REDIS_URL`, `REDIS_PRIVATE_URL` or `ENVIRONMENT`, or sets `WORKER_STORE_BACKEND=postgres`.
   Matching is case-insensitive and accepts an `export` prefix, because both settings classes and
   python-dotenv do. A value is never printed. The only value read is `WORKER_STORE_BACKEND`'s.
   Presence alone refuses: the launcher cannot tell a local URL from a Railway one without reading
   it, and an empty `DATABASE_URL=` line is one paste from production.
2. **Blank, do not unset.** The server's environment sets `DATABASE_URL`, `POSTGRES_URL`,
   `DATABASE_PRIVATE_URL`, `POSTGRES_PASSWORD`, `REDIS_URL` and `REDIS_PRIVATE_URL` to `""`, and
   pins `ENVIRONMENT=development` and `WORKER_STORE_BACKEND=disk`.
3. **Prove it in the same environment.** `local_preflight.py verify` runs with exactly the
   environment and working directory uvicorn will get, and refuses unless `is_configured()` is
   false, the environment is development, the worker store is disk, and `Settings` resolved the
   memory budget the launcher exported. A failure reports an exception's type, never its message,
   because a pydantic validation error echoes the input value.
4. **Loopback, one worker.** uvicorn binds `127.0.0.1` with `--workers 1`. The server fetches
   arbitrary URLs on request and would be an open proxy on a routable interface (ADR 0008). The
   rate limiter and cost ledger are in-process (CLAUDE.md §8).
5. **A per-run session secret.** A fresh 32-byte `AUTH_SESSION_SECRET` is generated for each run
   and placed only in the child's environment, so a token minted locally verifies nowhere else even
   if a dotenv carries another key. On an empty operator store only, a generated bootstrap password
   is shown once and never written to disk.

## Alternatives considered

* **`env -u` or `Remove-Item Env:`.** Rejected: it removes the process value and lets the dotenv
  value through (Context 4). This is the main reason this ADR exists.
* **Refuse a non-loopback database host in code when `ENVIRONMENT=development`.** The stronger
  guard, because it covers every way of starting the server. Not done in this cycle; it changes
  `create_app()` for every deployment and is the auditor's follow-up.
* **Run `npm run dev` beside a uvicorn dev server.** Rejected for a long-running crawl station: two
  processes, a hot-reload refresh that can drop the page mid-crawl, and a CORS split between ports
  5173 and 8000. The built UI is served by the API on one origin.
* **Silently fall back to another checkout's venv.** Rejected: the interpreter decides which `src`
  is imported. A worktree without `.venv` must pass `-Python` explicitly.
* **Honour a dotenv `CRAWL_MEMORY_BUDGET_MIB`.** Rejected: the launcher's value wins and a notice
  says so, so the budget reported before launch is the one in force.

## Consequences

* Local jobs, operators, orgs and workers live in `.jobs/`, `.operators/`, `.orgs/` and
  `.workers/` of the checkout the launcher runs from. They are never synced with production.
* Screaming Frog dispatch routes error locally, because `PostgresWorkerDispatchStore` has no
  database to reach. That is expected.
* **The guard is a launcher guard, not a code guard.** A server started any other way, for example
  `uvicorn` by hand from a checkout whose dotenv holds the production URL, is unguarded and would
  run `recover_orphans()` against production.
* `POSTGRES_HOST` is refused in a dotenv but not blanked in the server's environment, and the OS
  environment is not scanned. `is_configured()` does not read the host, so the job store is
  unaffected, but the lazily connecting `PostgresWorkerDispatchStore` would build its connection
  string from an OS-level `POSTGRES_HOST`. No such variable was set on this workstation.
* Anyone who ran a local server before this guard with a dotenv holding the Railway
  `DATABASE_URL` can check the `jobs` table for rows failed by a local startup; `README.md` gives
  the query.
