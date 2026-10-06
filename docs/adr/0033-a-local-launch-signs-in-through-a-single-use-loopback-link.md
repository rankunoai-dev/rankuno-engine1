# ADR 0033: A local launch signs in through a single-use loopback link, never in production

- **Status**: Accepted
- **Date**: 2026-10-06
- **Deciders**: AI Lead, Lead AI Systems Engineer (user chose "auto sign-in on launch" over
  removing login locally; security audit PASS WITH CONDITIONS C1-C18)

---

## Context

`scripts/run_local.ps1` (ADR 0032) runs the full site on the workstation for large crawls. Every
launch still stopped at the login screen. The operator store in a working checkout often holds
only a test artefact (`claude-test-op` in org `test-org`), while the local crawls live in org
`default`. So the user was shown "invalid operator id or password" for an operator that did not
exist. The user asked for the credentials step to go away for local runs, and chose to keep
normal login available.

Facts the design had to respect:

1. The UI keeps its session in `localStorage` and sends it as a `Bearer` header. There are no
   cookies, and CORS is an exact allowlist with `allow_credentials=False`.
2. Before this change there was no Host or Origin check.
3. uvicorn's access log records the method, path and query string, never the body.
4. FastAPI's default 422 response echoes the offending input.

### Threat model

- **Production accident.** The development-only route ends up reachable on Railway. This would be
  a password-free door into a multi-tenant server, so it is the risk the design is built against.
- **Token leakage.** The link's token ends up in a log, the browser history, a bookmark or an
  error body, and is replayed.
- **Another local user or process.** It finds the server on loopback and tries to reach it.
- **DNS rebinding from a web page.** The page sends requests to `127.0.0.1` under a foreign
  Host name.
- **Wrong tenant.** The link signs the browser in as whichever operator happens to exist.

## Decision

**The launcher mints a fresh token on every start and opens the browser at
`http://127.0.0.1:<port>/#autosignin=<token>`. The SPA exchanges it once at
`POST /api/v1/auth/local-signin` for an ordinary session.**

1. **Transport.** The token travels in the URL fragment, which a browser never sends to a server,
   so no access log sees it.
   - The SPA reads `location.hash` once at module load, before any request.
   - It strips the fragment with `history.replaceState` before sending anything.
   - It POSTs the token in a JSON body.
   - The token is never kept in store state, `localStorage`, a URL or a log.
   - Any failure (401, 429 or unreachable) falls back to the normal login screen with a generic
     message.
2. **Server state.** The server keeps only `sha256(token)` and an expiry five minutes after
   startup (`src/core/local_signin.py`).
   - Check, `hmac.compare_digest` and consume run in one `threading.Lock` critical section, so
     two racing requests cannot both succeed.
   - The hash is cleared on success and on expiry.
   - Five mismatches disarm the gate permanently.
   - The route also has a `local-signin` bucket at 10 per minute.
3. **One refusal response.** Wrong, expired, reused, locked-out and non-loopback requests all get
   the same `401 {"detail": "sign-in link is invalid or expired"}`. A rate-limited request gets
   429. With the feature off, the route is not mounted at all, so it is a 404.
4. **Same session as `/auth/login`.** The response is the same `LoginResponse`, issued by
   `issue_session_token` with the same TTL. `/auth/login`, the token format and the TTL are
   unchanged. Normal login keeps working, and `-NoAutoSignIn` turns this feature off.
5. **Loopback only.** The route requires both the peer address (`request.client.host`) and the
   bound socket (`scope["server"]`) to be loopback (`127.0.0.0/8` or `::1`).
6. **Host allowlist.** A new `API_ALLOWED_HOSTS` setting mounts Starlette's
   `TrustedHostMiddleware`. The launcher sets it to `127.0.0.1,localhost`, which closes the DNS
   rebinding path for the whole local site, not just this route. Unset, nothing changes, so
   TestClient's `testserver` and Railway are unaffected.
7. **A dedicated operator.** The link signs in as `local` in org `default`, overridable by
   `-AutoSignInOperatorId` / `-AutoSignInOrgId` (validated `^[a-z0-9_-]{1,64}$`).
   - If the operator is absent, `create_app()` creates it with the password hash of 32 random
     bytes that are then discarded, so it can never log in by password.
   - If it exists, it must be active and in the configured org, or the server refuses to start.
   - The link never borrows the first existing operator.
   - At redemption, the operator is read again and must still be active and in that org.
8. **Logging.** The server logs `local_signin_armed`, `local_signin_succeeded` (operator id and
   org), `local_signin_rejected` (a reason category: `mismatch`, `expired`, `consumed`, `locked`,
   `not_loopback`, `operator_unavailable`) and `local_signin_rate_limited`. Never the token or its
   hash.
9. **No `RiskClass`.** Like `/auth/login`, the route issues a session for an operator that
   already exists and changes nothing else. It is not a `BaseTool`.

### Departure from the empty-store-only rule

Bootstrap seeding (ADR 0016) creates an operator only in an empty store. The local operator is
created alongside whatever operators exist. The alternative would be signing in as whatever
operator is there, which is exactly the wrong-tenant risk above.

Bootstrap still runs first. On an empty store, the launcher's printed `admin` password is still
created, and `local` joins it. From then on the store is never empty, so bootstrap never fires
again in that checkout. Both operators persist in `.operators/`.

### Production-accident layering

Each layer below would stop the route on its own:

1. **`ENVIRONMENT` not `development`.** `Settings.model_post_init` raises `ConfigurationError`
   whenever the token is set and the environment is anything other than `development`. This is
   checked first, before the production secret checks.
2. **`ENVIRONMENT` unset on Railway.** If `ENVIRONMENT` were unset there, it would default to
   development and layer 1 would not fire. But Postgres is configured on Railway, and
   `create_app()` refuses the token whenever `get_postgres_settings().is_configured()` is true.
3. **Behind the proxy.** The route answers only a loopback peer on a loopback-bound socket.
   Behind Railway's proxy the peer is the proxy and the bind is `0.0.0.0`, so this fails closed.
4. **The token itself.** It is single-use, lasts five minutes, and is generated per launch. It is
   never in a dotenv file: `scripts/local_preflight.py scan` refuses `AUTH_LOCAL_AUTOSIGNIN_TOKEN`
   by name, and it is not in `.env.example`.

**Operator action required:** confirm that Railway sets `ENVIRONMENT=production`. Layer 1 depends
on it; layers 2-4 hold without it.

## Alternatives considered

- **Remove login when `ENVIRONMENT=development`.** One mistaken environment variable away from a
  password-free production server. Rejected.
- **Print a generated password at every launch.** Still a credential step, and a printed secret
  sits in scrollback. Rejected.
- **Token in the query string.** uvicorn's access log, browser history and any proxy would record
  it. Rejected in favour of the fragment.
- **Sign in as the first existing operator.** Wrong tenant in the main checkout today. Rejected.
- **`Start-Process <url>` in the launcher.** PowerShell module logging (event 4103) records cmdlet
  parameter values. The launcher calls `[System.Diagnostics.Process]::Start` with
  `UseShellExecute = $true` instead, which also opens the default browser.

## Consequences

- One command now opens a signed-in browser. Normal login and `scripts/create_operator.py` are
  unchanged.
- **Residual: process command line.** The browser is started with the URL, fragment included, on
  its command line. While it runs, that command line is visible to same-user processes and to
  process-creation auditing (Windows event 4688 with command-line logging, or Sysmon). Single use
  and the five-minute TTL neutralise it: by the time anyone reads it, the browser has spent the
  token or it has expired.
- **Residual: same-machine reverse proxy.** A reverse proxy on the same machine forwards requests
  from loopback, so it would pass the peer check. The Host allowlist and single use still apply.
  Do not front the local server with a proxy.
- **Residual: 422 echo.** A malformed body (an extra field, a non-string, or over 256 characters)
  gets FastAPI's default 422, which echoes the input. A well-formed request never triggers it.
- A launch with no default browser, or a server that never becomes healthy, prints only the plain
  address and points to normal login. It never prints the link.
- `API_ALLOWED_HOSTS` is a general setting. Production could adopt it later; nothing sets it
  there today.
