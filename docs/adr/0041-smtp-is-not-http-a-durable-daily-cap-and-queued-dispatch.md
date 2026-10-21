# ADR 0041: SMTP is not HTTP: a durable daily cap, queued dispatch, and no addresses in logs

- **Status**: Proposed (draft; not in force until a human accepts it). No SMTP code exists yet.
- **Date**: 2026-10-20
- **Deciders**: Lead AI Systems Engineer. The user approved the multi-user auth plan and chose to
  open sign-up later, with email verification and abuse caps (answer 2).
- **Amends**: CLAUDE.md §1 rule 5 ("No external API call outside a `BaseAPIClient` subclass"),
  for one class of outbound traffic only. CLAUDE.md is **not** edited by this draft. The amendment
  takes effect only when this ADR is accepted and CLAUDE.md is changed by a human.
- **Relates to**: [ADR 0040](0040-user-sessions-check-session-version-and-active-per-request.md)
  (the users table that verification mail will address).

## Context

Sign-up with email verification needs to send mail. CLAUDE.md §1 rule 5 requires every external
call to live in a `BaseAPIClient` subclass. `BaseAPIClient` (`src/integrations/base_client.py`)
is an HTTP client: it carries a base URL, retry on HTTP status, and rate limiting keyed to an API.
SMTP is a TCP protocol with a `HELO`/`AUTH`/`DATA` exchange and no HTTP status codes, so forcing
it through that class would either fail to fit or fill it with protocol special cases.

The concern rule 5 protects against is unmetered spend and untracked outbound calls. SMTP has the
same concern in another form: a sign-up form can be used to send unlimited mail through the
platform's sender, which damages the sending domain's reputation and can be billed by the provider.

## Decision

1. **One SMTP sender, in one module, is the sanctioned exception.** It is not a `BaseAPIClient`
   subclass, and it is the only module allowed to open an SMTP connection. The exception is
   narrow: it covers SMTP and no other protocol. Any other external call still needs a
   `BaseAPIClient` subclass.
2. **A durable daily cap in Postgres, not in process.** The send count per UTC day is a row in
   Postgres, incremented before the message is queued. An in-process counter would multiply the
   cap by the worker count, the same defect ADR 0004 records for the rate limiter and cost ledger.
3. **Dispatch is queued.** A request that needs mail writes a row and returns. A separate worker
   drains the queue and sends. The request path never waits on an SMTP server, so a slow relay
   cannot hold a worker thread or a connection.
4. **No addresses in logs.** Log lines name an event and an outcome, never the recipient. The
   same rule as the user store (ADR 0040): a log line outlives the account.
5. **Sending failures are retried with a bound, then parked.** The queue row records an attempt
   count and a fixed error class. A message is not retried forever, and its body is not logged.

Phase 1 ships none of this. The decision is recorded now so that the first SMTP change cannot land
as an unreviewed exception.

## Consequences

- CLAUDE.md §1 rule 5 has a documented, narrow exception. Reviewers must check that new code
  stays inside it: SMTP only, in the one sender module.
- The daily cap is a hard ceiling that survives restarts and works across workers. It is a count,
  not a spend figure. Converting it to a spend cap needs a per-message price that the provider
  publishes, and none is assumed here.
- Queued dispatch adds a table and a worker loop. That cost is accepted to keep the request path
  independent of the mail relay.

## Step 5 audit

1. **Hosts and volume**: one configured SMTP relay. Volume bounded by the daily cap.
2. **Rate limit**: the daily cap is the limit. It does not share a `rate_limit_key` with any tool.
3. **Spend**: the provider may charge per message. The cap bounds it. No `CostLedger` charge is
   specified yet; this is an open item for the SMTP change.
4. **Idempotency**: a queued message carries a row id. A retry must not send a second copy: the row
   is marked sent in the same transaction that records the outcome. Not yet implemented.
5. **Circuit breaker**: required on the database path, and on the SMTP connection once the sender
   exists. Not yet implemented.
6. **PII**: recipient addresses are personal data. They are stored only in the queue row, and never
   logged. Retention of sent rows is not yet specified.
7. **Input validation**: recipient and body are validated before enqueue. Not yet implemented.
8. **Credentials**: the SMTP password is a `SecretStr` read through `get_settings()`.

## Alternatives rejected

- **Send inline from the request.** A slow relay would hold a request, and a flood of sign-ups
  would hold connections.
- **Route SMTP through `BaseAPIClient`.** It would force protocol logic into an HTTP base class.
  The exception is narrower than that.
- **Cap in memory.** Multiplies by worker count, the defect ADR 0004 already names.
- **Use a third-party transactional-mail HTTP API.** That would stay inside rule 5 and is the
  preferred option if the user agrees. It is not chosen here, because the provider is not yet
  chosen and it needs a live credential.

## Open questions

- Which SMTP relay or transactional provider. Not decided.
- The daily cap value. Not decided.
- Whether the sender should prefer a transactional HTTP API so that this exception is not needed
  at all. Recommended for review before the SMTP change begins.
