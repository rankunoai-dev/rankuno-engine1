# Cycle 0019: Crawl checkpoints and partial-tree recovery

- **Date**: 2026-08-11
- **Scope**: Survive process death with the URLs already discovered, and let the
  operator render them.
- **Commit**: uncommitted at time of writing
- **Quality gate**: 1,010 tests, 95.69% coverage, `mypy --strict` clean

---

## 1. Gate results

```
=== Format ===      PASSED   All checks passed!
=== Lint ===        PASSED   All checks passed!
=== Type check ===  PASSED   Success: no issues found in 41 source files
=== Tests ===       PASSED   1010 passed in 43.07s
                             Required test coverage of 85.0% reached. Total coverage: 95.69%
ALL GATES PASSED.
```

Frontend: `npx tsc --noEmit` exit 0, `npx vite build` exit 0.

---

## 2. A crash that was misdiagnosed, and the one that was real

The plan named `http://[::1]/` as a previous crash cause. It is not one — it
returns `UnsafeUrlError`, which is the SSRF guard doing its job. Verified
directly before building anything on the premise.

The real vector was `http://[invalid-ipv6]/`, and the root cause is the standard
library:

```
File "src/core/url_safety.py", line 220, in validate
File ".../urllib/parse.py", line 446, in _check_bracketed_host
    ip = ipaddress.ip_address(hostname)
ValueError: 'invalid-ipv6' does not appear to be an IPv4 or IPv6 address
```

`urlsplit()` raises on a bracketed host that is not a valid IP — a Python 3.11
hardening. The bare `ValueError` escaped **both** `UrlSafetyPolicy.validate()`
and `extract_page_links()` (through `urljoin`), so one malformed `<a href>`
destroyed link extraction for the whole page it sat on.

Fixed at both sites: `validate` converts it to `UnsafeUrlError`, which every
caller already handles, and link extraction skips the href and keeps the rest.

### Why no universal `except Exception` guard

The plan asked for one around every URL parse, fetch and extraction. That would
re-introduce a defect this repository already fixed once: cycle 0003 found
`BaseAPIClient.call()` swallowing guardrail violations so callers **retried SSRF
blocks**. A blanket catch-and-continue makes an SSRF refusal indistinguishable
from a 404 — `fetch_failures += 1; continue` for both.

The fetch and DOM paths already had scoped guards. What was missing was one
unguarded stdlib call, and a precise fix is what the situation warranted.

---

## 3. Checkpoints save URLs, not classifications

`CrawlCheckpointer` writes on **whichever of two boundaries arrives first**:
10 seconds, or 100 pages. Either alone fails at one end of the range — at Turbo
speed 10 seconds is 250 pages, and on a slow site 100 pages is several minutes
exposed to a power cut.

What is saved is the discovered URL set. Not the classified output, which was
the plan's proposal: re-serialising every profile on each write is megabytes
through `fsync` hundreds of times per crawl, measurably more expensive than the
crawling itself. URLs are the part that cannot be recovered without going back
to the network; classification is CPU-only and can be redone.

`GET /jobs/{id}/checkpoint` returns a `PageClassificationOutput` — the same shape
as a finished crawl, so the client renders it through the path it already has. A
second shape would mean a second set of components to keep in step.

Every recovered page is `UNKNOWN` at `0.0` confidence, and `stopped_reason`
says why. That is honest rather than lazy: a checkpoint holds URLs. The
structure is real; what each page *is* was never determined, and a recovered
view must not be mistaken for a completed crawl.

---

## 4. Correction to cycle 0013

Cycle 0013 marked interrupted jobs `FAILED` with the reasoning that "the work
genuinely is lost", and build-log 0018 repeated it. That was true when written
and is **no longer true**: a checkpoint outlives the process.

`recover_orphans` now appends "partial results were saved and can be viewed" to
the failure reason when a checkpoint exists. The job still failed — it produced
no result — but what it found is recoverable, and the UI offers it.

---

## 5. What the UI does with it

`CrawlJobSummary.recoverable` is true when a job has a checkpoint and no result.
The error banner then carries a **Render partial tree** button, placed next to
the failure reason because that is where the operator is already looking.

Loading a checkpoint sets status `partial`, never `succeeded`, and forces the
`path` grouping — there is no navigation footprint in a checkpoint, so offering
the navigation view would present an empty one as though the site had no menu.

---

## 6. Explicitly not done

* **No navigation footprint in the checkpoint.** It is parsed from the homepage
  body, which is not saved, so a recovered view is URL-path only. Storing HTML
  is exactly the cost this design avoids.
* **No resume.** A checkpoint is for *viewing* what was found, not for
  continuing the crawl. Resuming needs the frontier and the visited set, and
  reusing a checkpoint from different crawl settings would silently mix them.
* **No live process-death test.** The checkpoint path is unit-tested; no server
  was killed mid-crawl to observe recovery end to end.
* **Checkpoints are never deleted.** `.jobs/` grows with every crawl, and a
  20,000-URL checkpoint is roughly 1–2 MB.
* **The 3-crawl concurrency cap still bounds memory, not the checkpoint.** A
  crawl still holds its whole graph including page HTML in RAM; the checkpoint
  changes what survives a crash, not what a crawl costs while running.
