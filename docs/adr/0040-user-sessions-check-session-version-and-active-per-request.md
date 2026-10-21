# ADR 0040: User sessions check `session_version` and `is_active` on every request

- **Status**: Proposed (draft; not in force until a human accepts it)
- **Date**: 2026-10-20
- **Deciders**: Lead AI Systems Engineer. The user approved the multi-user auth plan in three
  answers: (1) approve these ADR amendments; (2) open sign-up later, with email verification and
  abuse caps; (3) first-boot admin created atomically, with a forced password change on first login.
- **Amends**: [ADR 0016](0016-cloud-api-authentication.md). Only for **user sessions**. ADR 0016
  is not edited. Operator sessions keep the behaviour ADR 0016 describes.
- **Relates to**: [ADR 0029](0029-a-worker-credential-is-revoked-or-rotated-never-reactivated.md)
  (revoke, never reactivate), [ADR 0033](0033-a-local-launch-signs-in-through-a-single-use-loopback-link.md)
  (the loopback sign-in that must not reach a shared database).

## Context

ADR 0016 chose a self-contained session token. Its condition 6 prefers a format that is verified
locally, so each request needs no lookup. The consequence is stated in
`src/core/config.py` (`auth_session_ttl_s`): deactivating an operator "takes effect on a human
timescale", because the token is not checked against the store again before it expires. That was
acceptable for a small set of operators created by an operator.

Multi-user sign-in changes the cost of that gap. A user may be disabled, may lose access to an
organisation, or may have a password reset after a compromise. A 12-hour window in which a
disabled account keeps working is no longer a tolerable default for a user who can sign up.

## Decision

1. **A `users` table (migration 0014)** holds one row per user with `role` (`admin` or `user`),
   `is_active`, and a `session_version` integer that starts at 0. Email is stored lower-cased and
   unique. Partial unique index `ux_users_single_admin` allows at most one admin row.
2. **User session tokens carry the `session_version` they were issued under, and the user's
   `user_id`.** The token is still HMAC-signed and locally verifiable, so the signature check is
   unchanged.
3. **On every request that presents a user session, the server reads the user row by id and
   refuses the request unless `is_active` is true and the row's `session_version` equals the
   token's.** This is the one deliberate departure from ADR 0016 condition 6. It adds one indexed
   primary-key read per authenticated request, and it is the only way a deactivation or a password
   reset takes effect immediately.
4. **Revocation is a counter, not a deleted token.** Deactivating a user, resetting a password, or
   signing out everywhere increments `session_version`. Every outstanding token for that user then
   fails the check. Nothing is reactivated: an inactive user is made active again only by an
   explicit operator action, and a previous token never regains validity (the rule ADR 0029 set for
   worker credentials, applied here).
5. **The bootstrap admin** is created by one guarded `INSERT ... WHERE NOT EXISTS ... ON CONFLICT
   DO NOTHING`, only when the table has no admin row and `ADMIN_EMAIL` and
   `ADMIN_INITIAL_PASSWORD` are both set. The password is hashed with `hash_password`, stored with
   `must_change_password = true`, and the env value is never applied to an existing row. It is
   refused when shorter than 12 characters or on a short known-weak list. A startup warning is logged
   while the variable is still set. It names the fact only, never the password or the address.

Phase 1 (this change) ships items 1 and 5 and the store behind them. **Items 2 to 4 are not
implemented yet.** Request auth, the login routes and the token path are unchanged, and the
per-request check is a Phase 2 change that needs its own review.

## Consequences

- A user session costs one primary-key read per request. Acceptable at the scale this platform
  targets (ADR 0001), and it is the price of immediate revocation.
- The read goes through the same circuit breaker as the other Postgres stores. If the breaker
  opens, user sessions fail closed. Operator sessions are unaffected.
- A `session_version` that is rolled back, or a row that is deleted, invalidates the session. That
  is the intended failure direction.
- The 12-hour TTL in ADR 0016 stays as the outer bound. The counter makes it a ceiling, not the
  revocation mechanism.
- **Downgrade of migration 0014 destroys every user account.** Recovery is the bootstrap, and only
  while `ADMIN_EMAIL` and `ADMIN_INITIAL_PASSWORD` are still set.

## Step 5 audit

1. **Hosts and volume**: none external. One Postgres read per authenticated user request, once
   item 3 ships.
2. **Rate limit**: no external quota shared.
3. **Spend**: $0. No `CostLedger` charge.
4. **Idempotency**: the bootstrap INSERT is idempotent by construction (`ON CONFLICT DO NOTHING` plus
   the single-admin index). No UUID idempotency key exists, and none is claimed (ruling 2).
5. **Circuit breaker**: `PostgresUserStore` is wrapped in `CircuitBreaker`. The per-request read
   fails closed when the breaker is open.
6. **PII**: stores an email address and a password hash. Neither is logged. The admin bootstrap
   log lines carry fixed event names and no values.
7. **Input validation**: email is normalised and regex-checked, and the password length and weak-list
   checks run before any SQL.
8. **Credentials**: `ADMIN_INITIAL_PASSWORD` is a `SecretStr` read through `get_settings()`. Only
   the PBKDF2 hash is persisted.

## Alternatives rejected

- **Keep the stateless token and shorten the TTL.** Shortening the TTL to minutes only narrows the
  window. It does not make a deactivation immediate, and it forces frequent sign-ins.
- **Store sessions server-side with a deleted-on-logout row.** This is the cleanest revocation, but
  it moves the session into a second table and a second breaker for every request. The counter
  reuses the `users` row that the request already reads.
- **Check `is_active` only, with no counter.** A password reset would then leave every old token
  valid for as long as the account stays active, so reset would not cut off an attacker's session.

## Open questions

- Whether `session_version` should also be bumped on a successful password change by the user
  themselves. Leaning yes; not decided in Phase 1.
