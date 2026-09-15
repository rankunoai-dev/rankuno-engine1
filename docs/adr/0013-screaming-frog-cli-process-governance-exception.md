# ADR 0013: Governance Exception for Driving Screaming Frog via CLI

**Status**: APPROVED — the operator recorded explicit written approval ("approved") for
the Step 3 design summarized below, in the same conversation this ADR was presented in.
The companion Step 3 design document referenced throughout this ADR was presented
alongside it but was never separately committed to the repository as its own file; its
binding content is the Decision section below, carried forward verbatim into the brief
that scoped the first implementation cycle (`src/core/process_supervisor.py`, the
foundational Job Object + ledger + reconciliation primitive — condition 1, condition 2,
and the same-process answer to condition 3). Later conditions (4-8: the seed-URL
`UrlSafetyPolicy` gate, the CLI/`.seospiderconfig` field mapping, license-failure
handling, and the `RiskClass.WRITE`/`MANDATORY_HITL` tool itself) remain unimplemented
and are scoped to later cycles against this same approval.

**Date**: 2026-09-15

**Scope**: Whether, and under what binding conditions, the engine may launch and
control Screaming Frog directly from the UI instead of requiring an operator to run it
manually and upload the CSV export. Extends ADR 0011, which forbade exactly this
without a governance exception recorded in writing.

---

## Context

ADR 0011 §3 states: "Driving Screaming Frog via its CLI is **not** permitted under this
ADR: it bypasses `UrlSafetyPolicy`, `robots.py`, the rate limiter and `BaseAPIClient`
(CLAUDE.md §1.5, §5). If a client workflow ever requires it, it needs its own ADR, its
own deployable with process-group termination and startup reconciliation, and a
governance exception recorded in writing." That ADR's context cites `RAE - Copy/`'s own
Screaming Frog subprocess as a `--pool=solo` launch with "a cancel path that orphans the
JVM" — the specific regression this exception must not repeat.

An operator now wants to trigger Screaming Frog directly from the UI, eliminating the
manual export/upload step ahead of the existing CSV-bundle pipeline
(`load_screaming_frog_bundle`, `scripts/build_deliverable.py sf-bundle`). This is a new
capability request, not a bug fix, and it revisits ADR 0011 §3 on its own terms.

A `security-auditor` pre-step ran against this request and returned
**GO-WITH-CONDITIONS**, with eight findings (two CRITICAL, two HIGH, three MEDIUM/LOW,
one confirmatory). This ADR records the resulting governance exception. The mechanisms
that satisfy each condition are specified in the companion Step 3 design document; this
ADR states that they are binding, not how they work.

Confirmed by direct inspection for this ADR: `grep` across `src/` for `subprocess`,
`Popen`, `CREATE_NEW_PROCESS_GROUP`, `JobObject`, `CreateJobObject` returns zero matches.
No process-group or Job Object mechanism exists anywhere in this codebase today. This is
new governance territory, not an extension of an existing pattern — and, separately, no
`RiskClass.WRITE` tool has ever been instantiated in this codebase (`grep` for
`RiskClass.WRITE` outside `guardrails.py`/`schemas.py` returns nothing). This is also
the first tool this ADR's decision will make of that risk class.

## Decision

1. **The ADR 0011 §3 prohibition is lifted for exactly one path**, described in full in
   the Step 3 design document, and only while every condition below holds. It is not a
   general licence to shell out to arbitrary external tools; a future integration needs
   its own exception.

2. **The eight security-auditor findings are binding design requirements, not
   suggestions**, restated here as the conditions of the exception:

   1. **Process-group termination is mandatory and must be a real Windows Job Object**
      (`CreateJobObject` / `AssignProcessToJobObject` with
      `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`), assigned before the child process can run
      any of its own code — not `subprocess.terminate()`/`kill()` alone, and not
      `CREATE_NEW_PROCESS_GROUP` alone (enables `CTRL_BREAK_EVENT` only, not guaranteed
      descendant termination).
   2. **A second, independent PID + process-start-time ledger is mandatory**, written
      before Screaming Frog launches and read by a startup reconciliation routine that
      is separate from `DiskJobStore.recover_orphans()`. `recover_orphans()` must never
      be described as covering this case — it fails a `JobRecord`, it has no concept of
      an OS process, and today nothing ever looks for an orphaned Screaming Frog process
      again.
   3. **Whether the launcher lives in the API server process or a separate supervised OS
      process must be decided and justified in writing**, not defaulted. No precedent
      exists in this codebase either way.
   4. **A pre-flight `UrlSafetyPolicy.validate()` gate on the seed URL is mandatory**
      before Screaming Frog ever launches. This closes SSRF on the *seed* URL only, and
      the design must say so explicitly: Screaming Frog's own subsequent redirects and
      discovered links are not, and cannot be, validated by this engine's SSRF guard —
      they run inside a process this engine does not control.
   5. **Every UI-to-Screaming-Frog field mapping must be stated explicitly**, with each
      entry marked verified, needs-verification, or no-mapping. No CLI flag or
      `.seospiderconfig` key may be assumed correct without that marker, and no
      engine-side guarantee (e.g., `AsyncTokenBucket` accounting) may be implied for a
      setting that only reaches Screaming Frog's own internal throttle.
   6. **A license failure must surface as a distinct, named `JobRecord.error`** —
      `"Screaming Frog license invalid/expired"` — never a generic subprocess exit-code
      message, never retried, never silently degraded to an empty result.
   7. **If a separate supervisor process is chosen (condition 3), the design must state
      explicitly whether it reopens the in-process `CostLedger`/rate-limiter multi-worker
      gap (CLAUDE.md §8)**, even if the answer is "not applicable" — with a reason.
   8. **The exception does not loosen governance.** This capability is `RiskClass.WRITE`
      or stricter, `MANDATORY_HITL`, deny-by-default with no approval provider wired in.
      No design may propose auto-approval.

3. **`BaseAPIClient` does not apply to the Screaming Frog process launch itself**, and
   this ADR records that as a deliberate, bounded gap rather than a silent omission.
   `BaseAPIClient` governs HTTP calls *this process* makes; launching a local executable
   is not an HTTP call, and Screaming Frog's own crawl traffic never transits this
   engine's HTTP stack. `UrlSafetyPolicy` on the seed URL (condition 4) is the
   compensating control the exception installs in `BaseAPIClient`'s place, and it is
   explicitly partial.

4. **The existing CSV-bundle pipeline is the sanctioned output path and is not
   modified.** A completed run must hand off into the existing
   `load_screaming_frog_bundle` / `scripts/build_deliverable.py sf-bundle <path>` path
   unchanged. This exception governs how the CSV bundle gets produced, not how it is
   read.

## Consequences

- Screaming Frog becomes, for the first time, something this engine can cause to run —
  a `RiskClass.WRITE` capability with real external side effects (load on a third-party
  server, a licensed desktop process under this engine's control), where every other
  shipped tool today is `RiskClass.READ`. The governance weight this carries is new to
  the codebase, not an incremental extension of an existing pattern.
- `DiskJobStore.recover_orphans()` remains exactly what it was — a job-record status
  scan — and must not be extended to also mean "and no OS process was orphaned." The two
  concerns stay in separate mechanisms, per condition 2.
- A generic, reusable Windows process-governance primitive is added to `core/` rather
  than folded into SEO-specific code, so a future `RiskClass.WRITE` desktop-tool
  integration does not have to re-derive the Job Object / ledger mechanism from
  scratch. Detailed in the Step 3 design document.
- This exception is scoped to a single Windows workstation (ADR 0004). OS process
  handles, Job Objects and PIDs are not portable across machines. If a concurrent
  Celery-based multi-worker migration (observed in-flight in this codebase's current
  working tree, e.g. `src/api/server.py`'s `_queue_job_to_celery`) reaches this
  capability, the Screaming Frog job must be pinned to whichever worker host owns the
  Screaming Frog installation and license seat — this ADR does not and cannot make the
  mechanism host-transparent, and no future change should claim it does without a new
  ADR.
- No metered spend is introduced. `CostLedger` does not apply to this capability
  (condition 7's answer, restated here): Screaming Frog is a locally licensed desktop
  tool, not a per-call metered API.

## Alternatives rejected

- **Port RAE's original subprocess pattern.** This is the regression ADR 0011 already
  named and rejected once (`--pool=solo`, a cancel path that orphans the JVM). Re-using
  it here would reintroduce the exact defect this exception exists to close.
- **Treat this as a `BaseAPIClient` subclass.** Structurally impossible — there is no
  HTTP request from this process to wrap, retry, or rate-limit. Forcing the shape would
  produce a client with no `authenticate()` and no real request, misrepresenting what
  the connector does.
- **Loosen `RiskClass` to `DRAFT` or make approval `OPERATOR_REVIEW`.** Rejected per
  condition 8: nothing in the security findings supports loosening, and the blast
  radius (an uncontrolled external process, third-party server load, SSRF exposure on
  discovered links) is exactly the profile `WRITE`/`MANDATORY_HITL` exists for.
- **Defer the process-group/Job Object question to a later cycle and ship a
  `subprocess.Popen` wrapper now.** Rejected: this is precisely the state ADR 0011
  refused to accept from RAE, and Finding 1/2 establish that the consequence (a silently
  orphaned Screaming Frog process) is not hypothetical — it is the documented failure
  mode of the code this feature replaces.

## Open question this ADR does not resolve

How a `MANDATORY_HITL` approval is actually supplied for this tool is a genuine,
unresolved design question — not a detail to be assumed away — because
`GuardrailEngine.authorize()`'s `ApprovalProvider.request_approval()` call inside
`BaseTool.run()` is synchronous and blocking, and this codebase has never wired a real
`ApprovalProvider` for any tool before (every shipped tool is `RiskClass.READ`,
`AUTOMATIC`). The Step 3 design document lays out the two candidate shapes and
recommends one; the operator's sign-off on that recommendation is part of what this
ADR's HITL stop is for.
