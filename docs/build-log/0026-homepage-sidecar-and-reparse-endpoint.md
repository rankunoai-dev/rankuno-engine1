# Cycle 0026: Homepage HTML sidecar storage and zero-network re-parse endpoint

- **Date**: 2026-08-19
- **Scope**: Implement `.jobs/<id>.homepage.html` sidecar storage during crawl execution, and add `POST /api/v1/jobs/{id}/reparse` for instant synchronous offline navigation re-parsing without network I/O.
- **Commit**: `bfd51ed`
- **Quality gate**: `1,231 passed`, `Total coverage: 95.19%`

## 1. Gate results

```
=== Format ===
PASSED: Format

=== Lint ===
PASSED: Lint

=== Type check ===
PASSED: Type check

=== Tests ===
Required test coverage of 85.0% reached. Total coverage: 95.19%
1231 passed, 1 warning in 102.32s
ALL GATES PASSED.
```

UI, separately: `tsc --noEmit` clean. Contract regenerated.

---

## 2. What landed

### A. Step 1: Homepage HTML Sidecar (`.homepage.html`)
- **`homepage_sink` Callback Pattern**: `PageClassificationTool._apply_navigation()` takes a `homepage_sink: Callable[[str], None]` (matching `checkpoint_sink`), decoupling file storage mechanics from module execution logic.
- **`DiskJobStore.write_homepage(job_id, html_body)`**: Persists the homepage HTML as `.jobs/<job_id>.homepage.html` (~300 KB).
- **Safety & Resiliency Rules**:
  1. `MAX_HOMEPAGE_BYTES = 8 MB`: Oversized bodies are dropped rather than truncated to avoid partial tree parsing.
  2. Non-blocking error handling: `write_homepage()` never raises exceptions, guaranteeing a sidecar IO error can never crash a crawl.

### B. Step 2: Synchronous Offline Re-Parse Endpoint (`POST /jobs/{id}/reparse`)
- **Endpoint Specification**: `POST /api/v1/jobs/{job_id}/reparse`
- **Execution Profile**:
  - 100% synchronous and offline (~20ms–500ms depending on page count).
  - 0 network requests, 0 worker threads, 0 concurrency slot consumption, 0 SSRF re-validation.
- **History & Sidecar Continuity**:
  - Creates a new job record with label `"<url> (reparsed)"`, preserving the original job for audit trail comparison.
  - Copies the homepage sidecar onto the new job record to maintain re-parse continuity on multi-hop re-parses.
- **Schema Safety**: Returns HTTP 409 Conflict if stored result predates contract validation rules instead of raising HTTP 500.

---

## 3. End-to-End Verification

- Verified against stored 27,562-page `kinsta.com` crawl dataset:
  - Sidecar written: `127 KB`
  - Offline re-parsed time: `575 ms`
  - Navigation roots: `15 -> 6` (gained `Platform`, `Solutions`, `Resources`)
