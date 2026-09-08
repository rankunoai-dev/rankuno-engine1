# ADR 0012: Named Search Console Account Profiles Selected per Crawl

**Status**: APPROVED
**Date**: 2026-09-08

**Scope**: How more than one authorised Google account is configured for the Search Console connector, how a crawl selects one, and where the credentials are allowed to exist. Extends ADR 0010.

---

## Context

ADR 0010 fixed the connector's safety controls for **one** Google account: read-only
scope, `SecretStr` everywhere, credentials in gitignored `.env.local`, client-side
rate limiting. Cycle 0064 wired that single account through `GOOGLE_OAUTH_CLIENT_ID`,
`GOOGLE_OAUTH_CLIENT_SECRET` and `GOOGLE_OAUTH_REFRESH_TOKEN`.

An agency reads Search Console for many clients, each of whom has granted access to
a different Google account. A crawl therefore has to say *which* account reads for
it. Two designs were put to the security audit (build-log 0075 §3.1): a settings
form in the UI that posts credentials to the local API (Option B), and profiles in
`.env.local` with only their names exposed (Option A). Option B was rejected as a
HIGH finding: the local API is unauthenticated by design (ADR 0008), so it is the
wrong ingress for a refresh token.

## Decision

1. **Profiles are nested environment variables.** A profile named `acme` is
   `GSC_ACCOUNTS__ACME__REFRESH_TOKEN`, optionally `GSC_ACCOUNTS__ACME__CLIENT_ID`
   and `GSC_ACCOUNTS__ACME__CLIENT_SECRET`, in `.env.local`. `Settings` parses them
   with `env_nested_delimiter="__"` into `gsc_accounts: dict[str, GscAccountProfile]`.
   No second loader, no JSON blob, no extra secrets file.

2. **Names are lowercase and restricted to `[a-z0-9_-]`, 1–64 characters.**
   pydantic-settings lowercases nested keys, so `ACME` in the file is `acme` in
   settings, and a request naming `Acme` is refused at the boundary rather than
   matched case-insensitively. A `Settings` validator rejects any configured key
   outside the pattern at boot.

3. **The refresh token is per profile; the OAuth client is shared unless overridden.**
   `resolve_gsc_account(name)` returns the profile's token with `client_id` and
   `client_secret` inherited from `GOOGLE_OAUTH_*`, unless the profile sets its own.
   This is the only place the inheritance rule lives.

4. **An unknown name is an error, never a fallback.** `resolve_gsc_account` raises
   `ConfigurationError`; the API refuses the job at admission with 400 and creates
   no record, on create, retry and resume alike. Reading the wrong client's
   property is worse than a failed crawl. `None` means the flat default triple.

5. **The API publishes names only.** `GET /api/v1/gsc/accounts` returns a sorted
   `list[str]` through a fixed-shape `GscAccountsView`. No endpoint reads, writes,
   or echoes a credential. `PageClassificationInput.gsc_account` carries the name
   and nothing else.

6. **Credentials never enter the API, a job record, React state, or a log line.**
   Audit logs identify a named account as `oauth2://profile/<name>`. Enrichment
   failure logs record the exception type, not its message.

## Consequences

- Adding a client is editing `.env.local` and restarting the server. There is no UI
  for it, and none should be added without superseding this ADR.
- The single-account configuration from cycle 0064 keeps working unchanged: a
  crawl that names no profile uses it.
- One in-process `gsc_quota` bucket is shared by all profiles. That is correct while
  every profile authorises the same OAuth app (Google's quota is per project). A
  profile that supplies its own `client_id` breaks that assumption and needs a
  per-app bucket before it is used in earnest.
- The token refresh is one `requests.post` to a fixed Google URL outside
  `BaseAPIClient`, so that an `invalid_grant` fails once rather than once per retry.
  This is an accepted, documented deviation from CLAUDE.md rule 5 for that one
  call; it is not a precedent.
- The React crawl modal shows an account picker only when the engine lists at
  least one profile; fixture mode never shows one.

## Alternatives rejected

- **A settings form posting credentials to the local API (Option B).** The API has
  no authentication; anything on the workstation that can reach loopback could read
  or replace a client's credential, and the credential would transit browser state.
- **One JSON variable holding all profiles.** Every client's token on one line; a
  bespoke parser outside `Settings`.
- **A separate YAML/TOML secrets file.** A second secret store to gitignore,
  document and audit, for no gain over the file that already holds the default.
- **Silently falling back to the default account on an unknown name.** Produces a
  report from the wrong property with no error.
- **Case-insensitive name matching.** Two spellings of one profile in job records
  and logs; the boundary refuses uppercase instead.
