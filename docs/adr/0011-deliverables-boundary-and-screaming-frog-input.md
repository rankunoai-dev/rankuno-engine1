# ADR 0011: Deliverables Package Boundary and Screaming Frog as an Input Format

**Status**: APPROVED
**Date**: 2026-09-08

**Scope**: How client-deliverable generation is added to the engine without disturbing the crawler, and what role Screaming Frog plays.

---

## Context

`RAE - Copy/` was evaluated for integration (review 2026-09-07/08; deep read of
`masterfile_overview_report.py`). Its value is a 110-row issue catalogue, a rulebook
design, and the idea of Excel masterfiles as the client deliverable. Its code is not
portable: one database table, no tests, no migrations, Screaming Frog driven as a
Windows subprocess with `--pool=solo`, a cancel path that orphans the JVM, 26 catalogue
entries that can never fire, and fifteen silent-failure paths that render "not measured"
as "clean".

The engine crawls and classifies; it produces no client deliverable. The two must
connect without either importing the other.

## Decision

1. **A data contract is the seam, not a process boundary.** `AuditDataset` in
   `src/modules/seo/contracts/` — a `StrictModel` with a page spine, `{IssueId → URL set}`,
   and a mandatory per-issue `coverage` map. `page_classifier` and a new `deliverables`
   package both import `contracts`; neither imports the other. A test enforces it.

2. **The deliverables package lives in this repository under the same gate**, not as a
   separate service. It becomes a service only when a measured trigger fires: workbook
   build time, memory against a large dataset, or a need to run where the engine does not.
   Because the seam is a serialisable model, that move is "put HTTP in front of it".

3. **Screaming Frog is a supported input format, not a dependency.** The deliverables
   package accepts a bundle of SF CSV exports through an adapter. Driving Screaming Frog
   via its CLI is **not** permitted under this ADR: it bypasses `UrlSafetyPolicy`,
   `robots.py`, the rate limiter and `BaseAPIClient` (CLAUDE.md §1.5, §5). If a client
   workflow ever requires it, it needs its own ADR, its own deployable with process-group
   termination and startup reconciliation, and a governance exception recorded in writing.

4. **One catalogue, enum-typed.** RAE's two catalogues disagree in 30 places. Resolution
   rules: a silent table yields; never-scored rows take the dashboard value; where both
   have an opinion, stricter wins. `Severity` and `Priority` are enums; blank is
   unrepresentable.

5. **Not measured is a value.** Every `IssueId` carries `MEASURED` or `NOT_MEASURED`, and
   `NOT_MEASURED` implies an empty set. A workbook renders it as "Not measured by this
   crawl", never as zero issues.

6. **Fail loud.** A missing rulebook on a client deliverable is an error. Lenient mode is
   an explicit flag that stamps the dataset.

## Consequences

- The engine adapter is honest about coverage from day one: most categories are
  `NOT_MEASURED` until parsers exist. That is the correct state, and it is visible.
- Rulebook themes are applied to `AuditPage`, not `FullPageIntelligenceProfile` (ADR 0002
  contract unchanged).
- Link edges are not persisted by the crawler in this decision (memory model, CLAUDE.md
  §8). The SF adapter can fill `links`; the engine adapter declares Internal Links
  `NOT_MEASURED` until a separate cycle measures the cost.
- The RAE archive is a test oracle for **issue membership only** (the sets are Screaming
  Frog's, RAE merely reads them). It is not an oracle for scoring or layout.
- No RAE code is copied. Designs and data are re-implemented under the gate.

## Alternatives rejected

- **Port RAE wholesale as a service.** Imports the liabilities (one table, no tests, SF
  subprocess, orphaned JVMs) and leaves the asset (the catalogue) buried in 1,328 lines.
- **Put the contract in `core`.** `core` is domain-agnostic by rule; an SEO issue
  catalogue is not.
- **Add themes to the profile now.** Touches the canonical contract and the UI exporter
  for a deliverables concern.
- **Persist edges now.** Changes the crawler's memory model without a measurement.
