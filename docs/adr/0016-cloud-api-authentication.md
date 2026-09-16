# ADR 0016: Cloud API Authentication & Authorization for `src/api/server.py`

**Status**: APPROVED — the operator recorded explicit written approval ("We can approve
these blueprints and schedule their implementation") on 2026-09-16, the way ADR 0013
records its own approval. Implementation begins with this ADR first — ADR 0015's worker
identity design depends on this ADR's authentication mechanism existing in code, not only
on paper.

**Date**: 2026-09-16

**Scope**: Whether, and under what binding conditions, `src/api/server.py` gains
authentication (verifying *who* is calling) and the minimum authorization retrofit
needed so an authenticated caller cannot act on another organization's data. This is
the "Cloud API Authentication & Authorization" ADR that ADR 0015 (`docs/adr/0015-cloud-
local-desktop-worker-architecture.md`) names in its own binding condition 1 as a
blocking precondition for the Screaming Frog worker-dispatch feature, and that ADR 0015
condition 2 explicitly builds worker identity "on top of" rather than substitutes for.
This ADR exists independently of whether ADR 0015 ever ships — see Context below.

---

## Context

### What exists today

`src/api/server.py`'s own module docstring states the current design plainly: *"`serve()`
binds `127.0.0.1` deliberately. This server has no authentication, and it will fetch
arbitrary URLs on request — on a routable interface that is an open proxy. Local-only is
the security boundary (ADR 0004)."* That has been an accurate, deliberate design choice
since ADR 0004. It stops being sufficient the moment this server is reachable from
anywhere but the operator's own loopback interface — which ADR 0015 wants, and which the
pre-existing, undocumented `Dockerfile` / `railway.toml` / Celery / Postgres / Redis
stack already flagged by ADR 0015's own Context section makes plausible today,
independent of whether ADR 0015 itself is ever approved.

### A live vulnerability in currently-shipped code — independent of ADR 0015

A pre-step `security-auditor` audit against this exact scope found a **critical,
currently-exploitable** issue that exists in the codebase today, not a risk introduced by
a future feature. It must be understood on its own terms before the rest of this
document, because it is true right now, whether or not ADR 0015 or this ADR is ever
approved:

`src/api/server.py`'s three `/orgs/{org_id}/gsc-accounts` routes —
`list_org_gsc_accounts` (~line 2976), `create_org_gsc_account` (~line 3006), and
`delete_org_gsc_account` (~line 3060) — accept `org_id` as a raw URL path parameter with
**zero verification that the caller is affiliated with that org**. The create and delete
routes write and delete a `refresh_token: SecretStr` (and an optional `client_secret`)
in `OrgConfigStore` for whatever `org_id` string is supplied in the URL. The only gates
are that the org must already exist (`OrgConfigStore.get`) and, for create, that
`account_name` matches `^[a-z0-9_-]{1,64}$` — no auth check, no ownership check, and
these three routes do not even read an org-identity header the way most of the rest of
the file does. This is full read/write access to third-party Google OAuth credential
storage for **every** organization on the server, gated only by guessing an `org_id`
string — and `org_id` values in this codebase are short, human-chosen strings (`OrgConfig
.org_id` pattern `^[a-z0-9_-]{1,64}$`; the seeded default is literally `"default"`), not
random identifiers. This becomes remotely exploitable the instant this server is
reachable outside `127.0.0.1`.

### Direct inspection for this ADR

Beyond the pre-step audit, direct reading of the current working tree for this ADR
surfaced findings material to the design, some of which correct the audit's own phrasing
(recorded as corrections, not silent overrides, per CLAUDE.md §2's build-log discipline):

1. **The "already correct" IDOR checks elsewhere in `server.py` currently protect
   nothing, because nothing authenticates the header they trust.** `get_job` (~line
   1596), `list_jobs` (~line 1582), `get_result` (~line 1624), `list_gsc_accounts`
   (~line 1316), `preview_screaming_frog_job` (~line 1347),
   `create_screaming_frog_job` (~line 1396), and `create_job` (~line 1490) all derive
   `org_id` from an `X-Org-Id` request header (`org_id = x_org_id or "default"`) and, for
   the job-record routes, compare it against `record.org_id` before allowing access —
   a correctly *shaped* IDOR check. But `X-Org-Id` is a bare client-asserted header with
   no verification anywhere in this codebase today: any caller can set
   `X-Org-Id: <victim-org>` and the check passes trivially. This is true of every route
   that creates a record under an org today, including `create_job` — the primary crawl
   endpoint, which attributes `CostLedger`-adjacent budget (`OrgConfig
   .llm_credit_limit_usd`) purely by self-asserted header — and
   `create_screaming_frog_job`, the `RiskClass.WRITE` Screaming Frog dispatch path ADR
   0013 governs. This is not a new finding distinct from the audit's Finding #1/#2; it is
   the reason those findings matter even for routes whose *shape* already looks correct:
   authentication is the missing ingredient that turns a correctly-shaped check into a
   real one, for every route in this file, not only the ones with a missing or
   inconsistent check.
2. **The pre-step audit's "eight more routes accept an org header but never check it"
   framing does not match the code as it exists today, though the required fix is
   identical.** Direct inspection of `get_reconciliation` (~2127), `download_
   reconciliation` (~2146), `get_performance` (~2346), `download_opportunities`
   (~2364), `download_opportunities_workbook` (~2435), `download_matched` (~2526),
   `download_unmatched` (~2584), and `download_reconciliation_workbook` (~2668) — eight
   routes, matching the audit's count — shows none of them declare an `x_org_id`
   parameter or read an org header at all; they are in the same category as the six
   routes the audit separately named as having "no org-identity parameter at all"
   (`get_checkpoint` ~1666, `retry_job` ~1903, `reparse_job` ~1934, `reconcile_
   screaming_frog` ~2002, `cancel_job` ~2827, `resume_job` ~2874). This is a correction
   to the audit's phrasing, not its severity: **fourteen job-family routes total**
   currently perform zero org-ownership check before reading, mutating, or serving a
   job record by id. The fix (condition 2 below) is the same regardless of which of the
   two subgroups a route was originally filed under.
3. **`src/core/guardrails.py`'s `policy_for()` currently always returns the base
   (non-loosened) policy** — direct reading shows the development-environment branch is
   a documented no-op ("currently development doesn't loosen policy, so this is a
   no-op safeguard"). This appears to contradict CLAUDE.md §7 ruling 10, which names
   `policy_for()` loosening policy as a known, unresolved defect. This ADR does **not**
   resolve that discrepancy — it needs a git-history check to determine whether the
   defect was already fixed elsewhere and CLAUDE.md's register is stale, which is
   `docs-scribe`'s job, not this ADR's. Recorded here only so it is not lost.
4. **`src/core/facet_router.py`'s `validate_org_access()` is confirmed a no-op beyond
   checking the facet exists** — its own docstring says "In Phase 1, all orgs have
   access to all facets," and the method body has no other logic. Every
   `except PermissionError` reading its result in `server.py` (~1366, ~1425, ~1788) is
   dead code today. `OrgConfig.allowed_facets` (`src/core/schemas.py` ~line 193) already
   exists as a field on the model and is simply never read for this purpose — the same
   "anticipates but has not built" shape ADR 0015's Context section found in the
   idempotency registry and Celery wiring.
5. **No operator, user, or principal identity concept exists anywhere in this codebase
   today.** A repository-wide search for a `User`, `Operator`, `Principal`, or `ApiKey`
   class returns nothing; `org_id: str` (`OrgConfig`, `src/core/schemas.py` ~line 191)
   is the only identity-shaped concept that exists, and it identifies a *tenant*, not a
   *caller*. This ADR is the first design of caller identity in this codebase, not a
   wiring exercise against something that already exists — the same framing ADR 0015
   used for worker identity.

### Relationship to ADR 0015

ADR 0015 condition 1 states cloud-facing authentication is "a precondition, not
something this ADR designs" and blocks its own worker-dispatch feature on "a separate,
not-yet-written 'Cloud API Authentication & Authorization' ADR." This document is that
ADR. ADR 0015 condition 2 additionally requires that worker identity be "a distinct
credential, layered on top of whatever the precondition ADR builds — not a substitute
for it." Binding condition 5 below is written to satisfy that requirement directly: it
commits this ADR to a two-credential-type design so ADR 0015's per-worker secret has a
defined place to attach without redesigning this document later. This ADR does not
design, and does not attempt to design, the worker daemon side of ADR 0015 — that
remains entirely ADR 0015's scope, contingent on its own separate approval.

This ADR's value is not contingent on ADR 0015 shipping. The critical finding above is
real today, in currently-shipped code, regardless of whether any worker daemon is ever
built.

---

## Decision

Restating the pre-step audit's three numbered findings as this ADR's first three binding
conditions, then the audit's remaining binding requirements, mirroring how ADR 0013 §2
and ADR 0015 §Decision §3 restated their own findings as numbered conditions rather than
re-deriving them:

1. **[Finding #1 — CRITICAL] The three `/orgs/{org_id}/gsc-accounts` routes must gate on
   the caller's verified org affiliation, not a client-asserted or path-supplied
   `org_id`.** `list_org_gsc_accounts`, `create_org_gsc_account`, and `delete_org_
   gsc_account` must each derive the org they operate on from the authenticated
   principal (condition 4), never from the `org_id` path parameter alone. A caller
   authenticated as Org A must not be able to read, create, or delete Org B's GSC OAuth
   credentials by changing the URL. This closes the audit's critical finding and must
   ship in the same change as the authentication mechanism itself — an authentication
   layer added without this fix leaves the exact same exposure, only now requiring a
   valid login instead of nothing.
2. **[Finding #2 — HIGH] Every job-family route in `server.py` that lacks a correct
   org-ownership check must be retrofitted with one, in this ADR's implementation, not
   deferred as cleanup.** This is fourteen routes by direct inspection (see Context,
   item 2 above): `get_checkpoint`, `retry_job`, `reparse_job`,
   `reconcile_screaming_frog`, `cancel_job`, `resume_job`, `get_reconciliation`,
   `download_reconciliation`, `get_performance`, `download_opportunities`,
   `download_opportunities_workbook`, `download_matched`, `download_unmatched`, and
   `download_reconciliation_workbook`. The pattern to apply is the one that already
   exists and is already correct in shape: `src/api/deliverables_routes.py`'s
   `_org_scoped_or_404` helper (~lines 219-228), which `server.py`'s own `get_job` and
   `get_result` already replicate inline. The implementation must apply one shared
   helper consistently to all fourteen routes rather than re-deriving the check
   fourteen times — the inconsistency being fixed here is exactly what comes from not
   sharing it. Authentication alone does not close this finding: an authenticated Org B
   caller must still be prevented from cancelling, retrying, or reading Org A's jobs,
   which is an authorization concern this ADR's implementation must ship alongside
   authentication, not after it.
3. **[Finding #3 — MEDIUM] `resume_job` (~line 2967) must pass `org_id=record.org_id`
   to `_start`, matching `retry_job`'s existing correct call (~line 1930).** Today
   `resume_job` omits it, silently misattributing every resumed crawl to the "default"
   org regardless of the original job's owner. A small, mechanical fix; bundled into
   this ADR's implementation so it is not lost.
4. **`org_id` becomes a value derived from the verified principal for every route that
   currently trusts either a client-asserted header or a raw path parameter — including
   the routes whose check is already shaped correctly.** This applies to all fourteen
   routes in condition 2, the three routes in condition 1, and also to `get_job`,
   `list_jobs`, `get_result`, `list_gsc_accounts`, `preview_screaming_frog_job`,
   `create_screaming_frog_job`, and `create_job` — because, per Context item 1, those
   routes' existing `X-Org-Id`-header-based checks currently enforce nothing real. No
   route may read `org_id` from `X-Org-Id`, from any other client-supplied header, or
   from a URL path segment as ground truth after this ADR ships. The derivation is
   either a claim inside a verified token (condition 6) or a server-side lookup keyed by
   a verified credential (e.g., resolving a verified API key to its owning org) — never
   a value the request merely asserts.
5. **Two distinct credential types for two distinct principals — never a single
   one-size-fits-all mechanism.** (a) A short-lived, server-verified token (session JWT
   or opaque token validated against server state) for the human operator's browser/UI
   traffic. (b) A long-lived, per-worker secret for ADR 0015's worker daemon, satisfying
   ADR 0015 condition 2 exactly: `SecretStr`, read via `get_settings()`, unique per
   worker, never one platform-wide shared secret, and if the server stores anything
   about it, a hash/verifier only — never the recoverable secret at rest (the same
   posture ADR 0010 already takes toward GSC OAuth secrets). This ADR commits to the
   two-credential-type split; it does not itself mint or manage a worker credential,
   since no worker daemon exists to hold one until ADR 0015 is separately approved.
6. **A self-contained, locally-verifiable token/key format is preferred over one
   requiring a network call per request** (e.g., remote IdP introspection), so
   authentication does not add a new external dependency — and the circuit-breaker
   requirement that dependency would create — to every request's critical path. Per ADR
   0015's own correction, `src/core/circuit_breaker.py` exists but is scoped to Postgres
   connection resilience and is wired to nothing on any HTTP path; adding a
   per-request external auth dependency would immediately need coverage this codebase
   does not have anywhere. This is a preference this ADR records, not a mechanism it
   selects — see Open Questions.
7. **A new per-principal rate-limit key is required**, distinct from the existing
   `web.crawl` key (`src/core/rate_limiter.py`, shared today by `page_classifier`,
   `health_engine`, and `theme_classification` tools) and distinct from `ApiState.
   _active` / `ApiState._facet_active`, which are process-global concurrency caps with
   no per-org or per-principal subdivision today. One authenticated actor must not be
   able to starve every other org's capacity, which is possible today because both caps
   are global. A per-org concurrency sub-cap inside `ApiState` (alongside the existing
   global cap, not replacing it) is named as at least a should-have for this ADR's
   implementation, even if it is ultimately deferred — it must be named, not silently
   dropped, the same discipline ADR 0015 condition 2 applied to rate-limit-key design
   for the worker channel.
8. **This ADR governs who is calling, not what a crawl may fetch — `UrlSafetyPolicy`'s
   SSRF guard is unchanged and unweakened.** Whether an authenticated Org B should be
   permitted to point a crawl at Org A's staging environment, or at any target outside
   an org's own approved list, is a distinct, per-org target-allowlisting policy
   question. It is explicitly **deferred and out of scope** for this ADR — named here so
   it is not silently assumed solved, not silently ignored.
9. **This ADR does not touch, weaken, or become a substitute for `GuardrailEngine`,
   `_BASE_POLICY`, `policy_for()`, or the deny-by-default `MANDATORY_HITL` posture**
   (`src/core/guardrails.py`). Being an authenticated principal is never, by itself,
   sufficient approval for a `RiskClass.WRITE` or `RiskClass.FINANCIAL` action.
   Authentication and HITL approval remain separate concerns after this ADR ships, the
   same way ADR 0015 condition 3 keeps its dual-gate approval separate from worker
   identity verification. No design under this ADR may treat "the caller is logged in"
   as equivalent to "the caller approved this write."
10. **Credential and key material for this mechanism itself is `SecretStr`, read via
    `get_settings()`, never a raw `os.environ` read** — matching ADR 0010's posture
    toward GSC OAuth secrets exactly, and CLAUDE.md §1's non-negotiable rule 3. This
    applies to whatever signing key, verifier secret, or session secret the chosen
    mechanism needs, and to any per-worker secret condition 5(b) eventually mints.
11. **`src/core/facet_router.py`'s `validate_org_access()` is named explicitly as the
    authorization layer this new authentication sits in front of, not assumed to
    already enforce anything.** It is confirmed a no-op today beyond checking the facet
    exists (Context item 4). Full facet-level org authorization — "which facets can this
    org use at all," backed by the already-present but unread `OrgConfig.allowed_facets`
    field — is a distinct, broader question from condition 1/2's "does the caller own
    this specific existing record" problem. Condition 1/2 are in scope for this ADR;
    making `validate_org_access()` enforce anything real is **out of scope** and is not
    silently assumed to be solved by this ADR shipping.
12. **This ADR is the precondition ADR 0015 condition 1 names, and satisfies it once
    approved and implemented — but does not itself implement ADR 0015's worker-dispatch
    feature or change `server.py`'s `127.0.0.1`-only bind.** ADR 0015's worker-identity
    layer (its own condition 2) attaches to condition 5(b) above once ADR 0015 is
    separately approved; nothing in this ADR authorizes moving the API server off
    loopback, and nothing in this ADR should be read as sanctioning the undocumented
    cloud infrastructure ADR 0015's Context section flagged (`Dockerfile`,
    `railway.toml`, Celery, Postgres, Redis) — that remains exactly as undocumented and
    exactly as separate a decision as ADR 0015 itself already states.

---

## Step 5 — Security & Financial Audit

1. **Target Hosts & Volume**: None new, by design (condition 6's preference). A
   self-contained, locally-verifiable token format means every authenticated request is
   verified in-process, with no per-request call to an external identity provider.
   Volume is every request `server.py` already receives, now carrying a credential to
   verify locally — this ADR does not add network hops, only local verification work.
2. **Rate Limit Allocation**: A new rate-limit key, scoped per authenticated principal
   (human session or worker credential), is required per condition 7, distinct from the
   existing `web.crawl` key and from `ApiState`'s global concurrency caps — both of
   which are unpartitioned today and would let one bad authenticated actor starve every
   other org. A per-org concurrency sub-cap is named as a should-have, not committed.
3. **Worst-Case Financial Spend**: `$0.00` direct spend from authentication itself — a
   self-contained token/key check has no metered API behind it (condition 6). This ADR
   does not change `CostLedger` behavior for any tool; it only changes how `org_id` is
   determined before a tool runs. Any cloud-hosting infrastructure spend belongs to a
   separate, not-yet-written hosting ADR, exactly as ADR 0015's own Step 5 answer 3
   scoped equivalent infrastructure spend out of that document.
4. **Idempotency Protection**: Not newly required by authentication itself — login and
   token verification are read-only with respect to job/org state. This ADR does not
   change the idempotency posture of any existing `RiskClass.WRITE`/`FINANCIAL` route;
   `create_job`'s existing `Idempotency-Key` header handling is unaffected. If condition
   5(b)'s worker-credential issuance is later implemented (under ADR 0015), *that*
   issuance flow will need its own idempotency answer at that time — not answered here
   because no such flow exists yet.
5. **Circuit Breaker Coverage**: Not applicable, by design. Condition 6 explicitly
   prefers a self-contained verification format specifically to avoid introducing a new
   upstream dependency that would need circuit-breaker coverage this codebase does not
   have on any HTTP path today (`src/core/circuit_breaker.py` is scoped to Postgres
   connections only, per ADR 0015's own correction). If a future implementation chooses
   a remote-introspection mechanism instead, that choice reopens this question and must
   answer it explicitly at that time.
6. **PII & Data Minimisation**: New exposure, but bounded. Session/worker credential
   material is new sensitive data requiring `SecretStr` handling (condition 10) and, for
   worker secrets, hash/verifier-only storage (condition 5b). Human operator identity
   (whatever minimal claim identifies "who approved this write" for audit purposes) is
   new PII this codebase has not stored before — its exact shape is an open question
   (see below), not decided by this ADR. This ADR does not change crawled-page-content
   handling in any way; that data-residency question belongs entirely to ADR 0015
   condition 11 and is untouched here.
7. **Input Sanitize & Injection Defense**: Every credential presented to the server must
   be parsed and verified before any claim inside it is trusted, and the resulting
   `org_id` becomes a derived value (condition 4), never a raw client-supplied string —
   directly closing the injection-by-string-guessing vector the critical finding
   describes. No dynamic or string-keyed dispatch is introduced by this design.
8. **Credential & Secret Protection**: `SecretStr` via `get_settings()`, never
   `os.environ`, for every secret this mechanism introduces (condition 10); worker
   secrets never stored recoverable at rest (condition 5b), matching ADR 0010's existing
   posture toward GSC OAuth secrets exactly. No hardcoded secrets are introduced by this
   design.

---

## Consequences

- The single largest live vulnerability in this codebase — full unauthenticated
  read/write access to every organization's GSC OAuth credentials — is closed only once
  condition 1 **and** the authentication mechanism itself ship together. Shipping
  authentication without condition 1's fix leaves the exact same exposure behind a
  login page instead of behind nothing; shipping condition 1's fix without real
  authentication leaves `org_id` derivation with nothing trustworthy to derive from.
  Neither half is sufficient alone.
- Condition 2's fourteen-route retrofit means an authenticated caller from one org can
  no longer read, cancel, retry, or otherwise act on another org's jobs — closing a
  cross-tenant exposure that authentication alone does not close. This is new
  authorization surface added in the same change as authentication, not a follow-up.
- Every route that already derives `org_id` from `X-Org-Id` today (`get_job`,
  `list_jobs`, `get_result`, `list_gsc_accounts`, `preview_screaming_frog_job`,
  `create_screaming_frog_job`, `create_job`) changes its trust model under condition 4:
  the header stops being ground truth. This is a behavior change to seven routes that
  today "work" only because nothing malicious has asserted a false `X-Org-Id` yet — not
  a cosmetic rename.
- `server.py`'s module docstring ("This server has no authentication...") becomes false
  the moment this ships and must be corrected in the same change — a Step 8 drift item
  for whoever implements this ADR, and a build-log entry is mandatory per CLAUDE.md §2.
  The docstring's `127.0.0.1`-only binding rationale, however, does **not** become false:
  this ADR adds the capability to authenticate; it does not itself authorize moving off
  loopback or sanction the undocumented cloud infrastructure ADR 0015 flagged.
- This is the first credential-issuing, credential-verifying subsystem in this
  codebase's history. It is new maintenance surface (expiry, rotation, revocation,
  lockout) this codebase has never had to operate before — the same "new governance
  territory, not an incremental extension" framing ADR 0013 and ADR 0015 both used for
  their own first-of-a-kind additions.
- `GuardrailEngine`'s deny-by-default `MANDATORY_HITL` posture, `policy_for()`, and
  `_BASE_POLICY` are unchanged by this ADR (condition 9). A logged-in operator gains the
  ability to be correctly identified as the actor requesting a write — not the ability
  to skip HITL approval for one.
- `facet_router.validate_org_access()` remains exactly the no-op it is today (condition
  11). This ADR must not be read, by itself or by a later summary, as having made
  facet-level org authorization real — it has not.
- The current CORS configuration (`allow_credentials=False`, `src/api/server.py` ~line
  1284) is a fact any future cookie-based session design will need to revisit; this ADR
  does not choose a mechanism (see Open Questions), so it does not resolve whether that
  flag changes. Named here so a future implementer does not discover it mid-build.

## Alternatives rejected

- **Design a single credential mechanism for both human operators and worker
  daemons.** Rejected per condition 5: a browser session and an unattended desktop
  daemon have different lifetime, rotation, and revocation needs, and ADR 0015
  condition 2 already requires the worker credential be distinct.
- **Use remote IdP token introspection per request.** Rejected per condition 6: it adds
  a new external dependency, and therefore a circuit-breaker requirement, to every
  request's critical path — a requirement this codebase has never built for any HTTP
  path (ADR 0015's own correction: `circuit_breaker.py` exists but is Postgres-scoped
  only).
- **Ship authentication now and treat the job-route IDOR retrofit (finding #2) as a
  later hardening pass.** Rejected: an authenticated Org B caller could still act on Org
  A's jobs the moment authentication alone ships, which is not an improvement over
  today's fully-open state for that specific exposure — it is the same exposure gated by
  a login instead of by nothing.
- **Fold facet-level org authorization (making `validate_org_access()` real) into this
  ADR.** Rejected per condition 11: "which facets can this org use at all" is a broader,
  distinct question from "does the caller own this specific record," and conflating them
  would grow this ADR's scope well beyond authenticating a caller and closing the two
  IDOR findings that are already concretely known.
- **Treat successful authentication as sufficient approval for a `RiskClass.WRITE` or
  `FINANCIAL` action.** Rejected per condition 9: this would quietly reintroduce
  auto-approval by another name, exactly the pattern CLAUDE.md §3 already names as a
  security defect for `AutoApproveProvider` outside `ENVIRONMENT=development`.
- **Solve per-org crawl-target allowlisting (whether Org B may point a crawl at Org A's
  infrastructure) inline in this ADR.** Rejected per condition 8: authentication answers
  who is calling, not what they may fetch; that question belongs with
  `UrlSafetyPolicy` and org-configuration policy, not with caller identity, and is
  named as a deferred, separate question rather than solved or ignored.

## Open questions this ADR does not resolve

- **Exact token/credential format and library** for the human session credential
  (condition 5a/6) — a signed JWT, an opaque server-verified token, or another
  self-contained scheme. A preference for "self-contained, locally-verifiable" is
  recorded (condition 6); no specific format is chosen.
- **Where human operator identity comes from.** No user, operator, or account concept
  exists anywhere in this codebase today (Context item 5) — this ADR does not specify
  how an operator's credentials are issued, stored, or reset, only that whatever
  mechanism is chosen must not violate conditions 4, 5, and 10.
- **Exact shape of the `org_id`-derivation lookup** for API-key-style credentials
  (condition 4) — a token claim versus a server-side table mapping key to org is left
  open.
- **Per-org concurrency sub-cap inside `ApiState`** (condition 7) — named as a
  should-have, not committed to this ADR's implementation scope.
- **Rate-limit-key design** for the new per-principal key (condition 7 / Step 5 answer
  2) — named as necessary, not specified.
- **CORS `allow_credentials` implications** if a cookie-based session design is chosen —
  flagged in Consequences, not resolved.
- **Whether `src/core/guardrails.py`'s `policy_for()` still loosens policy in
  development**, per CLAUDE.md §7 ruling 10, or whether that defect was already fixed
  elsewhere and the register is stale (Context item 3). This needs a git-history check.
  Note for `docs-scribe`, not resolved by this ADR.
