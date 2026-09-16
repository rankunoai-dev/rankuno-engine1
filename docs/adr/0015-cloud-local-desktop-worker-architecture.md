# ADR 0015: Cloud + Local Desktop Worker Architecture for Screaming Frog Dispatch

**Status**: APPROVED — the operator recorded explicit written approval ("We can approve
these blueprints and schedule their implementation") on 2026-09-16, the way ADR 0013
records its own approval. Implementation is sequenced **after** ADR 0016 (`docs/adr/0016-
cloud-api-authentication.md`), per this ADR's own binding condition 1: nothing here may
be implemented before that ADR exists, is approved, and is actually built — this ADR's
own approval does not itself unblock condition 1. Until ADR 0016 lands in code,
`src/api/server.py`'s existing `127.0.0.1`-only binding and ADR 0004's local-workstation
posture remain unchanged and must not be described as superseded.

**Date**: 2026-09-15

**Scope**: Whether, and under what binding conditions, a cloud-hosted API/UI may
dispatch a Screaming Frog crawl job (ADR 0013 conditions 4-8) to a worker daemon running
on an operator's own Windows desktop, over an untrusted network, instead of requiring
the API server and the Screaming Frog CLI to be co-located on one machine. This is the
self-hosted-runner pattern (GitHub Actions runners, Jenkins agents), applied to a single
`RiskClass.WRITE`, `MANDATORY_HITL` tool.

---

## Context

### What exists today

`src/modules/seo/screaming_frog_control/tool.py` (`ScreamingFrogControlTool`) and
`src/core/process_supervisor.py` (Windows Job Objects, an independent PID ledger,
`reconcile_orphans()`) ship ADR 0013 conditions 4-8: a governed, `MANDATORY_HITL`
tool that launches Screaming Frog CLI headless and hands off a CSV bundle. Approval is
supplied by a two-call preview/confirm exchange
(`src/modules/seo/screaming_frog_control/preview_tokens.py`): `POST .../jobs/preview`
validates the seed URL and template and mints a short-lived, single-use token bound to
`(org_id, seed_url, template_name)`; `POST .../jobs` hands that token back, and a
`CallbackApprovalProvider` consumes it — never a bare `confirmed: true` boolean — at the
exact moment `GuardrailEngine.authorize()` asks for approval inside `tool.run()`
(`src/api/server.py` lines 1343-1420).

All of this assumes the API server and Screaming Frog CLI are the same machine.
`src/api/server.py`'s module docstring states the reason plainly: *"`serve()` binds
`127.0.0.1` deliberately. This server has no authentication, and it will fetch arbitrary
URLs on request — on a routable interface that is an open proxy. Local-only is the
security boundary (ADR 0004)."* A cloud-hosted API is a direct contradiction of that
stated boundary, not an extension of it.

### What is being asked

An operator wants to run the cloud API/UI somewhere other than the Screaming Frog
license machine, and have that machine — the operator's own Windows desktop — run a
lightweight worker daemon that: connects outbound to the cloud (transport is an open
decision below), receives a job assignment, runs it locally via the already-built
`process_supervisor.py` + `screaming_frog_control`, and uploads the resulting CSV bundle
back to the cloud.

### Pre-step security audit (binding inputs to this ADR)

A `security-auditor` pre-step ran against this exact proposal and returned **PASS WITH
CONDITIONS**. Its findings are restated below as this ADR's binding decision points, not
re-derived — Decision §2 numbers them the way ADR 0013 numbered its own eight
conditions.

### Direct inspection for this ADR

Beyond what the pre-step audit found, direct inspection of the current working tree
surfaced two facts material to this decision that the audit did not have in front of it:

1. **Cloud infrastructure already exists in this repo with no ADR recording it.**
   `Dockerfile`, `railway.toml`, `src/core/celery_config.py`, `src/workers/job_executor.py`
   (a Celery task, `execute_crawl`), `src/core/redis_config.py`, and
   `src/core/postgres_store.py` (`PostgresJobStore`) are all present in the working tree.
   `railway.toml` sets `numReplicas = 1` and provisions Postgres and Redis services.
   `src/api/server.py` already calls `_queue_job_to_celery(record.id)` on job creation,
   and its own idempotency registry carries the comment *"In production, this would
   query the idempotency_keys table in PostgreSQL for multi-process/multi-server
   deployments"* — i.e., the code already anticipates the multi-replica case this ADR's
   binding condition 5 (below) requires, but has not built it. None of this is recorded
   in an ADR anywhere in `docs/adr/`, and it directly contradicts ADR 0004's "local
   workstation only" ruling with no documented decision to revise it. This ADR does
   **not** resolve that gap — see Decision condition 13 and Consequences.

2. **`src/core/circuit_breaker.py` now exists**, contrary to CLAUDE.md §8's "does not
   exist" and contrary to the pre-step audit's framing of "no circuit breaker exists
   anywhere in this codebase (confirmed gap, CLAUDE.md §8)." A real `CircuitBreaker`
   class (`CLOSED`/`OPEN`/`HALF_OPEN`, 5-failure threshold, 30s recovery timeout) ships
   and is wired into `PostgresJobStore` for Postgres connection resilience. This is a
   **correction**, not a re-derivation of the finding: the primitive exists, but it is
   scoped to Postgres connections specifically, is not generic, and nothing in the
   codebase wires it — or any circuit breaker — to an outbound HTTP/WebSocket dispatch
   path. For the worker↔cloud channel this ADR proposes, the practical gap the audit
   named is still real; only the "does not exist anywhere" phrasing is now false at the
   file level. CLAUDE.md §8 itself needs a correction entry for this; that edit belongs
   to `docs-scribe`, not this ADR.

### Does ADR 0004's "cloud drops in behind an interface later" already exist in code?

**No — this ADR designs that interface for the first time.** ADR 0004's interfaces
(`ZeroShotClassifier` for Layer 2, `LLMClient` for Layer 3) are ML-inference
abstractions; they say nothing about job *transport* or *dispatch*. Separately, the
Celery/Postgres/Redis infrastructure found above is a same-trust-boundary worker pool —
Celery workers are assumed to be co-located with (or at least equally trusted as) the
API process and the resources a job needs. There is no existing concept anywhere in this
codebase of a job type that must be pinned to one specific operator-owned machine,
reached across an untrusted network, holding a licensed resource the cloud side does not
own. Worker identity, worker authentication, per-worker job pinning, and a
network-crossing approval handshake do not exist in any form today. This ADR is the
first design of that interface, not a wiring exercise against one that already exists.

---

## Decision

### 1. Architecture overview

```
┌────────────────────────────┐        outbound only         ┌──────────────────────────────┐
│   Cloud API (extends the   │ <──────────────────────────── │  Local Worker Daemon          │
│   existing FastAPI server, │   poll or push, TBD below      │  (operator's Windows desktop, │
│   behind the precondition  │ ────────────────────────────>  │  same machine as the SF       │
│   auth ADR — condition 1)  │   job assignment + signed       │  license seat)                │
│                             │   approval artifact             │                               │
│  - preview/confirm gate    │                                 │  - re-validates envelope      │
│    (reuses preview_tokens  │ <──────────────────────────── │    locally (StrictModel +     │
│    pattern, per-worker)    │   bundle upload (manifest-      │    UrlSafetyPolicy)            │
│  - persistent token +      │   constrained, size-capped)     │  - GuardrailEngine.authorize() │
│    idempotency store       │                                 │    with worker-local approval  │
│    (Postgres)               │                                 │    check (not a bare boolean)  │
│  - job routing pinned to   │                                 │  - process_supervisor.py +     │
│    the owning worker_id    │                                 │    screaming_frog_control      │
└────────────────────────────┘                                 │    (unchanged, ADR 0013)       │
                                                                 └──────────────────────────────┘
```

The desktop side is deliberately unchanged from ADR 0013: `process_supervisor.py`,
`ScreamingFrogControlTool`, `UrlSafetyPolicy`, and `GuardrailEngine` are reused as-is.
This ADR adds a dispatch/identity/approval layer in front of them, not a replacement.

### 2. Transport: polling vs WebSocket (open decision — needs operator sign-off)

The prompt that scoped this ADR explicitly asked for tradeoffs, not a unilateral choice.
Both directions are worker-initiated-outbound only regardless of the answer — a desktop
behind NAT/corporate firewall cannot reliably accept inbound connections, so the cloud
never opens a connection to the worker either way.

| | Polling (worker `GET`s a dispatch endpoint every N seconds) | WebSocket (worker holds a persistent outbound connection) |
| :--- | :--- | :--- |
| Latency | Bounded by poll interval (job pickup delay) | Near-immediate dispatch and cancellation |
| New infra | None — reuses the existing REST/`JobStore`/org-scoping patterns already in `server.py` | New — no WebSocket path exists anywhere in this codebase today |
| Multi-replica safety | Naturally stateless; a request landing on any replica just needs the shared store from condition 5 | Compounds condition 5's problem: which replica holds the live socket becomes a *second* sticky-routing problem on top of the token-store one, unless a pub/sub fan-out (e.g. Redis, already present) is added |
| Reconnect/backoff | Simple — a failed poll is just a retry next interval | Needs explicit heartbeat + reconnect + backoff logic in addition to condition 10's bounded backoff |
| Fit for this workload | Good — SF crawls run minutes to hours; jobs per desktop per day are low; dispatch-latency in the tens of seconds is not costly here | Better suited to high-frequency, low-latency dispatch, which this workload is not |

**Recommendation: polling for v1.** It reuses infrastructure and patterns that already
exist and are already proven (the org-scoped REST endpoints, `JobStore`), avoids adding
a second scaling problem on top of condition 5's, and the latency cost is negligible
against multi-minute-to-multi-hour crawl runtimes. This recommendation is explicitly
**not** a decision — it requires operator sign-off before implementation, per the scope
of this pass.

### 3. Binding conditions

Restating the pre-step audit's findings, plus the direct-inspection findings above, as
binding design requirements — mirroring how ADR 0013 §2 restated its own eight findings:

1. **Cloud-facing authentication is a precondition, not something this ADR designs.**
   `server.py`'s own docstring states local-only *is* the security boundary because the
   server has no authentication and will fetch arbitrary URLs on request. This ADR does
   not weaken that boundary and does not design general cloud API authentication —
   authenticating every existing route is a cross-cutting concern far larger than one
   tool's dispatch path. This feature is explicitly **blocked** on a separate,
   not-yet-written "Cloud API Authentication & Authorization" ADR. Nothing in this ADR
   may be implemented before that one exists and is approved.
2. **Worker identity is a distinct credential, layered on top of whatever the
   precondition ADR builds — not a substitute for it.** Each worker daemon holds one
   unique, long-lived credential (`SecretStr`, read via `get_settings()`, never
   `os.environ`) — never one platform-wide shared secret. If the cloud database stores
   anything about it, it stores a hash/verifier, never the recoverable secret (the same
   posture ADR 0010 already takes toward GSC OAuth secrets: `SecretStr`, never a
   plaintext value at rest). Dispatch/poll/upload endpoints filter strictly by the
   worker's own authenticated identity, never an `org_id` or `worker_id` the request
   merely claims in its body/query — reusing the IDOR-check pattern `get_job` already
   implements (`src/api/server.py`: `if job.org_id != org_id: raise HTTPException(403)`).
3. **Approval is a dual gate, not a single hop.** (a) A cloud-side preview/confirm gate,
   structurally identical to `preview_tokens.py`'s mint/consume flow, additionally bound
   to the target `worker_id`, gates whether a job is ever queued at all. (b) The worker
   daemon independently verifies a falsifiable, single-use, expiring, identity-bound
   approval artifact transported from the cloud — never a bare `"approved": true`
   boolean — before its own `GuardrailEngine.authorize()` call runs locally. A worker
   that trusts an unconditional boolean from the cloud is architecturally identical to
   wiring `AutoApproveProvider` into production: a hardcoded `True` gated behind a
   network hop instead of gated behind nothing, which CLAUDE.md §3 already names as a
   security defect outside `ENVIRONMENT=development`.
4. **HMAC command signing is a tampering/spoofing defense, not an approval mechanism.**
   Signing job envelopes and approval artifacts defends against network-path tampering
   and a third party spoofing the cloud or the worker. It does **not** defend against a
   compromised cloud API process, because the signing key lives inside the trust
   boundary being distrusted. Condition 3's dual gate — not signing — is what limits the
   blast radius of a compromised cloud process; no design may present signing as
   sufficient on its own.
5. **The preview-token store and the idempotency registry move to a shared, persistent
   store before this ships**, reusing Postgres (`src/core/postgres_store.py` /
   `src/core/postgres_config.py`, already present) — not inventing a third storage
   mechanism, and not Redis-only, given Postgres already carries the atomic-transaction
   pattern this codebase uses for job/cost state. (Redis is also already present via
   Celery's broker and is not ruled out if the implementation ADR/PR makes and states
   that tradeoff explicitly — but the choice must be named, not defaulted.) Name the
   failure mode explicitly: two cloud API replicas, an operator confirms on replica A
   (minting a token), the worker's poll/dispatch lands on replica B, which has never
   heard of that token. **The safe failure is "approval silently fails, nothing runs."**
   Never "fix" that friction by making an unrecognized token fail open.
6. **Screaming Frog jobs are pinned to the specific worker holding the license — never
   round-robined across an interchangeable pool.** ADR 0013's own consequences section
   already mandates this for the Celery-multi-worker case; it applies identically here.
   A job record for this tool must carry a required target `worker_id`; dispatch to any
   other worker is a routing bug, not a load-balancing choice.
7. **The worker daemon's dispatch loop uses a closed-enum discriminator, dispatched via
   literal match/if — never string-keyed dynamic dispatch, a dict-of-callables, `eval`,
   or `pickle`.** One member today: `SCREAMING_FROG_CRAWL` (a `StrEnum`, matching the
   convention already used by `FieldMappingStatus` and `CircuitBreakerState`). The
   envelope is JSON decoded into a `StrictModel`, matching `celery_config.py`'s own
   existing `task_serializer = "json"` choice — prior art already in this codebase for
   exactly this concern.
8. **The job envelope is minimal and matches `ScreamingFrogJobInput`'s shape exactly,
   plus transport metadata**: `{job_id, seed_url, template_name, correlation_id}`. No
   `extra_args`, `raw_command`, or path-override field is ever added to the cloud job
   schema — the same discipline `ScreamingFrogJobInput` already enforces locally. The
   worker re-validates every field itself (`UrlSafetyPolicy.validate()` on `seed_url`,
   `TemplateRegistry.resolve()` on `template_name`) — not trusted just because the cloud
   validated it once. Locally, that second check was defense-in-depth (ADR 0013
   condition 4 already re-checks for exactly this reason); across an untrusted network
   hop, the worker-side check becomes the *load-bearing* one.
9. **The upload path gets the same scrutiny as any untrusted file upload.** A size cap,
   path-traversal/zip-slip defense if the bundle is transported as an archive, and a
   hard constraint to exactly the files `export_manifest.py` already defines
   (`SPINE_TAB`, `EXPORT_TABS`, `BULK_EXPORT`) — never an arbitrary walk of
   `bundle_dir`.
10. **No circuit breaker exists for the worker↔cloud channel in v1 — this is an accepted
    gap, not an oversight.** `src/core/circuit_breaker.py` exists (see Context) but is
    scoped to Postgres connection resilience and is not generic or wired to any
    HTTP/WebSocket path; building or reusing one for this channel is deferred. Bounded
    exponential backoff on the worker's poll/dispatch/upload calls is the v1
    substitute, matching the honesty CLAUDE.md §8 already requires elsewhere in this
    codebase about this gap.
11. **Data residency changes for the first time: crawled page content now flows desktop
    → cloud storage.** Today's local flow never leaves the workstation. This ADR
    requires the implementation to specify, explicitly and before shipping: a retention
    window with automatic expiry for uploaded bundles, at-rest encryption in whatever
    cloud storage is used, and access scoped by org/worker the same way job records
    already are. The exact retention window is an open operator decision (see Open
    Questions) — this ADR does not set a number.
12. **The worker daemon answers ADR 0013 condition 3's question again, for itself.**
    Recommendation: **same-process** — the worker daemon and the Screaming Frog
    supervision run in one OS process, for the same reason ADR 0013 chose that for the
    local API server: `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` does not depend on the
    launching process staying alive, so splitting the daemon into a separate supervised
    process buys nothing for that guarantee while adding an extra process to keep
    running. This is new territory the local-only design never had to answer:
    `reconcile_orphans()` must run at the **worker daemon's own startup**, using the same
    `ledger_path` `launch_supervised` wrote to on that desktop, and must complete before
    the daemon begins polling for or accepting new dispatches. A worker daemon that can
    itself crash and restart is a new failure mode the local API server never needed to
    answer.
13. **Pre-existing cloud infrastructure drift (Dockerfile, railway.toml, Celery,
    Postgres, Redis — see Context) is flagged, not resolved, here.** This ADR scopes
    around it: it neither depends on that infrastructure being ADR-documented first, nor
    claims to reconcile it. A separate cleanup ADR recording the departure from ADR
    0004's "local workstation only" ruling is a blocking precondition for treating that
    infrastructure as sanctioned, and is out of scope for this document.
14. **Governance is not loosened anywhere in this chain.** The Screaming Frog launch
    itself remains `RiskClass.WRITE`, `MANDATORY_HITL`, deny-by-default with no approval
    provider wired in, regardless of how the job reached the desktop. No design under
    this ADR may propose auto-approval at the cloud edge, the transport layer, or the
    worker — extending ADR 0013 condition 8 explicitly across the new network boundary.

---

## Step 5 — Security & Financial Audit

1. **Target Hosts & Volume**: The new "host" is the cloud API's own public endpoint
   (not yet named or deployed — the precondition ADR's responsibility), reached
   *outbound* from the operator's desktop worker daemon. Volume is low and bursty: SF
   crawl jobs are infrequent (minutes-to-hours runtime each), so dispatch/poll traffic
   is bounded by the polling interval chosen in implementation (e.g. every 10-15s while
   idle), plus one bundle upload per completed job, size-capped per condition 9.
2. **Rate Limit Allocation**: A new `rate_limit_key`, scoped per worker identity (not
   per org, since the worker daemon — not an org's human operator — is the principal
   making poll/dispatch/upload calls), is required so one worker's poll loop cannot
   starve an unrelated tool's quota. No existing `rate_limiter.py` key fits this
   principal; this is an open implementation item, not resolved by this ADR.
3. **Worst-Case Financial Spend**: `$0.00` direct spend — Screaming Frog remains a
   locally licensed desktop tool, not a metered API, unchanged from ADR 0013's
   condition-7 answer; `CostLedger` does not apply to the tool call itself. New
   *infrastructure* spend (cloud hosting, storage, bandwidth for bundle uploads) is real
   but belongs to the precondition cloud-hosting ADR's cost accounting, not this one —
   named here so it is not silently uncounted anywhere.
4. **Idempotency Protection**: Required. `job_id` in the minimal envelope (condition 8)
   is the idempotency key; the worker must treat re-dispatch of an already-ledgered
   `job_id` as a no-op rather than launching a second Screaming Frog process, reusing
   `process_supervisor.py`'s own PID ledger keying. The cloud-side idempotency registry
   moves to the persistent store per condition 5 — the current in-process
   `_idempotency_registry` in `server.py` is explicitly insufficient for this feature.
5. **Circuit Breaker Coverage**: Not present for this channel in v1 (condition 10) —
   named as an accepted gap, bounded exponential backoff substituted. See the Context
   correction regarding `src/core/circuit_breaker.py`'s actual (Postgres-scoped) status.
6. **PII & Data Minimisation**: New exposure — crawled page content (URLs, titles,
   metadata, and any incidentally-captured page text in the near-duplicate/low-content
   exports) now leaves the desktop for cloud storage, where today's flow never left the
   workstation (condition 11). Retention window, at-rest encryption, and org/worker
   access scoping must be specified before shipping; this ADR does not set the exact
   retention number (see Open Questions). No new PII-specific scrubbing is proposed
   here — this inherits the existing crawl pipeline's posture toward incidental PII in
   crawled content, which is unchanged by this ADR.
7. **Input Sanitize & Injection Defense**: Every envelope field is re-validated locally
   by the worker through `StrictModel` and `UrlSafetyPolicy.validate()` (condition 8),
   never trusted solely on the strength of the cloud's earlier validation. Job-kind
   dispatch is a closed-enum literal match only (condition 7) — no dynamic or
   string-keyed dispatch surface exists for a network-supplied value to exploit.
8. **Credential & Secret Protection**: Per-worker unique long-lived credential via
   `get_settings()`/`SecretStr`, never a shared platform-wide secret, never a raw
   `os.environ` read, and never a recoverable value at rest in the cloud database
   (condition 2). No hardcoded secrets are introduced by this design.

---

## Consequences

- This is the first time a `RiskClass.WRITE`, `MANDATORY_HITL` tool's approval chain
  crosses an untrusted network boundary. Every mechanism that made ADR 0013's HITL gate
  trustworthy on one machine (in-process token store, a single approval callback
  invoked once, no network hop between mint and consume) must be re-derived for two
  machines and, per condition 5, potentially multiple cloud replicas. This is new
  governance territory, not an incremental extension — the same framing ADR 0013 used
  for its own novelty.
- `server.py`'s `127.0.0.1`-only binding and its documented "local-only is the security
  boundary" stance are **not** superseded by this ADR. They remain literally true of the
  current codebase until the precondition authentication ADR (condition 1) exists,
  is approved, and is implemented. Any implementation that begins before that happens
  reopens exactly the open-proxy risk that docstring names.
- `PreviewTokenStore` and `server.py`'s in-process idempotency registry stop being
  adequate the moment more than one cloud API process or a reconnecting worker is in
  play (condition 5). This is a required migration, not an optional hardening step, and
  it must land before this feature is trusted in anything but a single-replica,
  single-worker pilot.
- Crawled page content leaving the operator's desktop for the first time (condition 11)
  is a genuine change to this platform's privacy posture, previously a selling point of
  the local-only design (ADR 0004's Consequences: *"local inference means no page
  content leaves the machine... a genuine privacy advantage when auditing client
  sites"*). This ADR's design narrows that advantage specifically for Screaming Frog
  audit output, and only for operators who opt into cloud dispatch; it does not change
  the posture of any other tool.
- No metered spend is introduced by the tool itself (Step 5 answer 3); cloud
  infrastructure spend is real but out of this ADR's accounting scope.
- The pre-existing, undocumented cloud infrastructure (Dockerfile, railway.toml, Celery,
  Postgres, Redis — Context) remains exactly as undocumented as it was before this ADR.
  This document does not sanction it, reconcile it with ADR 0004, or rely on it being
  sanctioned; a human reading this ADR should treat that infrastructure's existence as a
  visible, separate problem, not as evidence this feature is closer to shippable than it
  is.

## Alternatives rejected

- **Trust a bare `"approved": true` boolean from the cloud to the worker.** Rejected per
  condition 3: this is `AutoApproveProvider` wired into production by another name,
  which CLAUDE.md §3 already treats as a security defect.
- **Treat HMAC signing as sufficient approval evidence on its own.** Rejected per
  condition 4: signing defends against tampering and spoofing, not a compromised
  signer — the signing key lives inside the exact trust boundary the dual-gate design
  (condition 3) exists to not fully trust.
- **Round-robin dispatch across an interchangeable worker pool.** Rejected per condition
  6 and consistent with ADR 0013's own consequences section: the Screaming Frog license
  seat is not host-transparent, and pretending otherwise silently breaks the first job
  routed to a worker without the license.
- **Design full cloud API authentication inline in this ADR.** Rejected: authenticating
  every existing route is a cross-cutting concern affecting far more than this one
  tool's dispatch path, and folding it in here would violate the smallest-safe-change
  discipline this document is trying to hold to. Scoped instead as an explicit
  precondition (condition 1).
- **Leave the preview-token store and idempotency registry in-process and treat the
  multi-replica case as a later hardening pass.** Rejected per condition 5: this is
  precisely the "unrecognized token fails open" trap the audit named, and the failure
  mode (a confirmed job silently never running, or worse, an unconfirmed one running) is
  not hypothetical — `server.py`'s own idempotency-registry comment already anticipates
  the multi-process case without having built it.
- **Choose polling or WebSocket unilaterally in this pass.** Rejected: the task scoping
  this ADR explicitly required presenting the tradeoff rather than deciding it. A
  recommendation is offered (§2) but is not binding without operator sign-off.

## Open questions this ADR does not resolve

- **Transport**: polling vs WebSocket. Recommendation given (§2: polling), not decided.
- **Shared store for condition 5**: Postgres vs Redis, both already present in this
  codebase. Recommendation given (Postgres, for its existing atomic-transaction
  pattern), not decided.
- **Retention window for uploaded crawl data** (condition 11 / Step 5 answer 6): no
  number is proposed here; this is an operator policy decision, not an engineering one.
- **Rate-limit key design** for worker poll/dispatch/upload endpoints (Step 5 answer 2):
  named as necessary, not specified.
- **The precondition cloud API authentication ADR itself** does not exist yet. Its
  scope, mechanism (API keys, mTLS, OAuth, something else), and timeline are all
  undetermined, and this feature cannot begin implementation before it does.
