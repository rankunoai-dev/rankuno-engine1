# Cycle 0119: A list that travels as a hash, and the claim that never carried it

- **Date**: 2026-09-29
- **Scope**: A finished Rankuno crawl's orphan and sitemap-only URLs are dispatched to a
  Screaming Frog worker as a `--crawl-list` file, approved by fingerprint and fetched by
  digest; plus the ADR-number collision that left 26 source files citing the wrong document.
- **Commit**: `cc7dac1` (`feat(screaming-frog): dispatch a crawl's orphan URLs through
  --crawl-list`). This entry is retrospective — the code shipped without it, which is the
  drift `CLAUDE.md` §2 exists to prevent. The documentation corrections in §5 and §7 are
  uncommitted at time of writing.
- **Quality gate**: see §1. Format, lint and drift re-executed by the scribe and pasted
  verbatim; `pytest` **not** re-run this session.

---

## 1. Gate results

### 1.1 What was re-executed here

```
$ .\.venv\Scripts\python.exe -m ruff format --check .
536 files already formatted
EXIT=0

$ .\.venv\Scripts\python.exe -m ruff check .
All checks passed!
EXIT=0

$ .\.venv\Scripts\python.exe scripts\drift_check.py
Running Architecture & Documentation Drift Audit...

--- Drift Audit Results ---
PASSED: no drift detected across 203 markdown files.
  - all relative links resolve
  - all domain modules documented
  - all skill directories populated
EXIT=0
```

Pasted from the final run, after every edit in this cycle including the 40 citation rewrites
in §5.1. They were also run before those rewrites, when the tree held one fewer markdown file
(`202`) and one fewer Python file (`535`); both exited 0 then too.

### 1.2 What was not re-executed, and why

`pytest` was not re-run. Two reasons, both recorded rather than worked around:

1. A concurrent session is active in this repository (a `ui-engineer` in `rankuno-ui/`,
   and the actor that took build-log number 0118 out from under this one mid-cycle). A
   second `pytest` would overwrite the in-flight run's `.coverage`, which is the same
   hazard build-log 0106 records.
2. The implementing commit's own figure was not captured in a form this scribe can quote,
   and inventing one is worse than saying so.

What can be stated from the diff, not from memory: `cc7dac1` adds **162** new
`def test_` functions across 13 test files (7 new, 6 extended), statically counted with
`git show cc7dac1 -- tests/ | grep -c "^+.*def test_"`. That is a count of test functions
added, **not** a count of tests that passed. No coverage number is claimed for this cycle.

---

## 2. What landed

### 2.1 `modules/seo/screaming_frog_control/url_list.py` — the list, and why it is frozen early

Screaming Frog's `--crawl` follows links, so the pages it can never reach — orphans, and
URLs published only in a sitemap — are exactly the ones worth auditing. This engine already
holds both. `build_url_list()` turns a finished crawl into the bytes `--crawl-list` reads.

The list is generated and frozen at **preview** time, before a human approves anything. The
reason is the one that governs the whole cycle: the bytes an operator approves a fingerprint
of have to already exist. Generating at download time would let the operator approve a
fingerprint of one list while the worker fetches whatever the source crawl says later, or
nothing at all if that crawl was deleted or re-run in between.

Five stages, each counted separately so a UI can say "excluded 18 external URLs" truthfully
rather than reporting one opaque shrinkage:

| Stage | Behaviour on a rejected URL |
| :--- | :--- |
| Dedupe (fragment dropped, query **kept**) | folded into its base URL |
| Scheme (`http`/`https` only) | dropped and counted |
| Registrable domain | dropped and counted, never a refusal |
| Host safety (`UrlSafetyPolicy`, per host) | dropped and counted |
| Ceiling | **refuses the whole list** |

`?page=2` is deliberately *not* collapsed — it is a different resource, and folding it would
silently drop real pages. `#pricing` and `#contact` are, because they are one fetch.

### 2.2 `core/json_stream.py` — reading a column without reading the document

Generating a list means reading every `url` out of a finished crawl's `result.json`. On this
workstation a real 100,687-page crawl is a 93 MB file. Measured, on that exact file:

| approach | peak RAM | wall clock |
| :--- | ---: | ---: |
| `json.load` + list comprehension | 292.3 MB | 3.09 s |
| `iter_array_object_field` | 5.3 MB | 3.76 s |

Fifty-five times less memory for twenty percent more time. The memory is the number that
matters: a cloud replica that inflates a third of a gigabyte per "build me a URL list"
request is one concurrent request away from its own container limit.

It is a real decoder on a sliding window, never a regex. The same file carries **100,736**
occurrences of `"url":` for 100,687 pages, because `navigation` nodes further down the
document have a `url` field of their own. A pattern cannot tell those apart.

`DiskJobStore.iter_result_page_urls` gets this property. `PostgresJobStore` does **not** —
see §6.3.

### 2.3 The digest through four gates — `core/worker_dispatch_*`

`url_list_sha256` is a pattern-pinned (`^[0-9a-f]{64}$`) SHA-256 added to
`DispatchPreviewToken`, `DispatchAssignmentClaims` and `WorkerJobEnvelope`. It is bound into:
the cloud preview row; the confirm statement's own `WHERE` clause (via
`IS NOT DISTINCT FROM`, so `NULL` matches `NULL` for an ordinary `--crawl`); the signed
assignment claims, so the existing HMAC covers it with **no change to the signing
construction**; and `describe_invocation`, which names the crawl, the count and three real
URLs, because a bare hash is not something a human can approve.

The bytes never travel in the token. They live in a content-addressed
`worker_dispatch_url_lists` table (migration `0007`) and are fetched over the worker's own
authenticated channel. The reasoning is now [ADR 0023](../adr/0023-a-url-list-travels-as-a-digest.md),
which also records that this **reverses** `WorkerJobEnvelope`'s stated "carries nothing
else" stance and narrows ADR 0015 condition 8.

### 2.4 `api/url_list_routes.py` and `GET /workers/jobs/{id}/url-list`

`GET /jobs/{id}/url-list/sources` says which sources are available and gives a reason for
each that is not, so a UI never offers a choice that would fail. "Orphans Only" is genuinely
conditional: an orphan is defined by comparison against an uploaded Screaming Frog export
(`EngineGapReason.SITEMAP_ORPHAN`), and that comparison does not exist until one is uploaded.

`GET /workers/jobs/{id}/url-list` is **the only route in this architecture where bytes travel
cloud → worker**. Everything else in ADR 0015 goes the other way, so it is scoped
accordingly: `owned_job` requires *the* worker the job was pinned to, not merely a worker in
the right org, and `read_url_list` filters on `org_id` in SQL a second time. The digest is
deliberately not sent in a response header — a second copy beside the bytes is a copy anyone
who can alter the bytes can also alter.

`url_list_routes.py` is a separate module from `worker_dashboard_routes.py` because that file
was already at this codebase's 400-line target; `build_url_list_router` is included by
`build_worker_dashboard_router`, so `server.py` still mounts one router.

### 2.5 `license_check.py` — a shortfall this codebase could not previously see

With a known supplied list length, the Screaming Frog free-tier cap becomes detectable for
the first time. "Crawled exactly 500" only means *capped* when more than 500 were supplied.
A real 500-URL list that completed is therefore no longer reported as degraded, and a genuine
shortfall (`url_list_shortfall`, derived in `_to_view`, not stored) is surfaced on the
finished job. It is `None` whenever either input is missing, because "cannot say" is a
different claim from "nothing missing".

---

## 3. Design decisions

### 3.1 Refuse over the ceiling; never trim

`SCREAMING_FROG_URL_LIST_MAX_URLS` defaults to 10,000 and raises `UrlListTooLargeError`
rather than truncating. A trimmed list audits fewer pages than the approval text says it
does, with nothing anywhere signalling the difference, and it would destroy the truncation
check in §2.5 — which works precisely by comparing supplied length against pages crawled.
10,000 was chosen against three real crawls on this workstation (100,687 / 33,439 / 26,255
pages); **every one exceeds it**, which is the intent. "All Discovered URLs" on a large site
is the request that should have to be reconsidered.

Off-domain URLs take the opposite treatment — dropped and counted, never a refusal. Refusing
a 10,000-URL list over 18 outbound links would make the feature useless.

### 3.2 SSRF validation once per host, not once per URL

`UrlSafetyPolicy.validate()` calls `socket.getaddrinfo` and has **no cache**. A per-URL check
on a 50,000-URL list is 50,000 blocking DNS lookups inside a request handler, for a list that
resolves one or two names. `_safe_hosts()` validates each distinct host once. This is sound
for the property being enforced — the verdict is a function of the host, not the path — and
is a deliberate trade of granularity for liveness, not an oversight.

### 3.3 CRLF, UTF-8, no BOM

Screaming Frog is a Java application reading a file this engine may have written on a Linux
cloud host. A BOM decodes as a zero-width no-break space glued to the first URL, which then
fails to resolve — one silently missing row at the top of every list. Nothing written here
carries one and `read_url_list_file` strips one it finds, so a file an operator re-saved from
Notepad still works. CRLF costs one byte per URL and removes the only ambiguity that matters.

The worker **re-renders** the file from the parsed URLs rather than writing the downloaded
bytes, after verifying the download. Verification happens on the raw bytes first, so
normalising afterwards cannot launder a tampered list.

---

## 4. Bugs found and fixed

### 4.1 The field was threaded through every model and never actually minted

A review of this change before commit found `url_list_sha256` correctly added to
`DispatchPreviewToken`, `WorkerJobEnvelope`, `WorkerJob`, the preview and confirm store
methods, the migration, the routes — **and** to `DispatchAssignmentClaims`.

But `issue_dispatch_assignment` in `core/worker_dispatch_signing.py`, the only code in the
system that mints claims, was never modified. It took no `url_list_sha256` parameter and
passed none, so `DispatchAssignmentClaims.url_list_sha256` took its `None` default on
**every mint, for every job, including list jobs**.

The consequence chain, in order:

1. The worker's `if claims.url_list_sha256 is not None` was always False.
2. `prepare_url_list` was therefore never called. The list was never fetched.
3. The tool ran with no `UrlListInvocation`, which is an ordinary `--crawl` of the seed URL.

So **every approved list dispatch would have run as a site spider**. An operator who read
"LIST MODE over 4,312 orphan URLs", weighed it, and approved it would have got a full crawl
of the site instead — the exact opposite of what the HITL gate exists to guarantee, and a
`RiskClass.WRITE` action doing something other than what was approved.

Secondly, and independently: the digest was consequently **unsigned**. The worker had no
signed copy to verify a download against, which removes the entire basis of §2.3. Even a
worker that *did* call `prepare_url_list` would have been comparing downloaded bytes against
`None`.

Fixed before commit: `issue_dispatch_assignment` gained a `url_list_sha256: str | None = None`
parameter documented in its own `Args:`, and `api/worker_routes.py`'s poll handler now passes
`url_list_sha256=job.envelope.url_list_sha256` (`worker_routes.py:202`). A default of `None`
keeps every existing caller's behaviour byte-identical for an ordinary `--crawl`.

### 4.2 Why no test caught it — the pattern this project keeps repeating

`tests/modules/seo/screaming_frog_control/test_worker_url_list.py` constructs a
`DispatchAssignmentClaims` **by hand**, with a digest already present, and tests
`prepare_url_list` in isolation against it. Every assertion in that file passes whether or not
any production code has ever put a digest into a claim set.

Nothing drove a list job along the real path: `/poll` → `issue_dispatch_assignment` →
`verify_dispatch_assignment` → the worker's branch. The end-to-end dual-gate test that does
walk that path (`test_dual_gate_end_to_end_worker_verifies_a_genuine_assignment`) uses a
list-less dispatch and asserts `claims.seed_url`.

This is the same failure shape as build-log 0116's 19 service tests asserting
`len(result) > 0` against an empty temp directory, and 0115's tests mocking the adapter so
they never saw a wrong id: **a test that builds the state it wants instead of exercising the
path that produces it**. Such a test cannot fail for the reason the feature can break.

The gap is narrowed but not closed — see §8.1.

---

## 5. Corrections

### 5.1 26 source files cited an ADR about a different subject

`docs/adr/0022-postgres-backed-job-store.md` is titled *"Crawl job records, results,
checkpoints, and homepage snapshots move to Postgres"*. It says nothing about URL lists, the
dispatch envelope, or `--crawl-list`.

The URL-list cycle reserved number 0022 and wrote it into its source docstrings; a concurrent
Postgres-persistence cycle (build-log 0118, commits `1a84ed6`/`3895677`) then took 0022
first. `git show 1a84ed6 | grep "^+.*ADR 0022"` returns exactly one line — the ADR's own
title. Every other citation in the tree came from `cc7dac1`, which added **40** of them.

So a reader following any of those 40 pointers landed on a document about job persistence.
Corrected in this cycle to [ADR 0023](../adr/0023-a-url-list-travels-as-a-digest.md),
written here for the purpose, with no logic touched — comments and docstrings only:

| Location | Citations rewritten |
| :--- | ---: |
| `src/` (12 files) | 26 |
| `tests/` (10 files) | 13 |
| `alembic/versions/0007_worker_dispatch_url_lists.py` | 1 |
| **Total** | **40** |

`grep -rn "ADR 0022" src/ tests/ alembic/ scripts/` now returns **nothing**. Every surviving
occurrence is in prose about job persistence and was left alone: the ADR's own title,
`README.md` rows 140 and 349, `ARCHITECTURE.md`'s `postgres_store.py` tree entry, build-log
0118, and its index row. Those landed from the concurrent Postgres session *during* this
cycle and are all correct. No legitimate reference to the Postgres ADR was altered.

The build-log index already warns that four code comments cite "cycle 0104" when they mean
0107. This is the same class of defect one level up, and the second time in this repository
that concurrent sessions have collided over a reserved number.

### 5.4 Build-log 0118 §4.3 is wrong about migration `0007`

Written concurrently with this entry, build-log 0118 §4.3 flags a stale cross-reference in
`alembic/versions/0006_job_payload_storage.py` and adds:

> `alembic/versions/0007_worker_dispatch_url_lists.py`'s own docstring correctly says
> "ADR 0022".

It did say that, and it was **not** correct — migration 0007 creates
`worker_dispatch_url_lists`, which the Postgres-job-store ADR does not mention. That line was
one of the 40 in §5.1 and now reads "ADR 0023". The claim is understandable: from inside the
Postgres cycle, 0022 was the right number for 0022's own work, and a citation to it looked
right wherever it appeared. That is precisely why a number collision is expensive — it makes
wrong citations look verified. 0118 is left intact per rule 4.

### 5.2 `docs/ARCHITECTURE.md` asserted that `--crawl-list` appears nowhere in `src/`

`ARCHITECTURE.md:520` said, of `rankuno-ui/src/lib/urlParser.ts`:

> `--crawl-list` appears nowhere in `src/`, so the URL-list upload `urlParser.ts` is held
> for does not exist yet either

True when written (cycle 0112). Falsified by `cc7dac1`, which added
`src/modules/seo/screaming_frog_control/url_list.py`, `worker_url_list.py` and
`src/api/url_list_routes.py`. Corrected in this cycle's Step 8 update.

### 5.3 The dispatch envelope is no longer minimal

Build-log 0117 and ADR 0021 both state that the
`DispatchPreviewRequest` → `DispatchPreviewToken` → `DispatchAssignmentClaims` →
`WorkerJobEnvelope` → `ScreamingFrogJobInput` chain is byte-identical and that the envelope
"carries nothing else". Both were true of cycle 0117's change and are **no longer true of the
envelope**: `url_list_sha256` is the first field added since ADR 0015. Those entries are not
edited (rule 4); the reversal is recorded here and argued in ADR 0023's Context.

---

## 6. Explicitly not done

### 6.1 The UI

No React surface consumes any of this. `GET /jobs/{id}/url-list/sources` exists precisely so
a UI never has to guess which sources are offerable, and nothing calls it yet. A
`ui-engineer` is working on it concurrently and separately; until that lands, list-mode
dispatch is **API-only** and an operator cannot reach it from the dashboard.

### 6.2 The worker does not re-apply `UrlSafetyPolicy` to the list it downloads

Checked in `src/modules/seo/screaming_frog_control/worker_url_list.py` rather than assumed.
`prepare_url_list` fetches the bytes, compares `fingerprint(body)` against
`claims.url_list_sha256`, parses, refuses an empty list, re-renders and writes. There is **no
`UrlSafetyPolicy` import in that module** and no per-entry host check anywhere worker-side;
`worker_daemon.py` holds a policy and applies it to the **`seed_url`** only.

The SSRF control on list entries is therefore **cloud-side admission alone**, on the far side
of the hop ADR 0015 calls untrusted. What the digest does give is that the worker crawls
exactly the bytes a human approved and nothing else, so substitution between the cloud's
storage and the worker process is closed. What it does not give is an independent check that
the cloud admitted the right thing. Accepted for v1 and recorded as an obligation in ADR 0023;
until it exists, list-mode SSRF protection must not be described as defence in depth.

### 6.3 `PostgresJobStore.iter_result_page_urls` does not get the bounded-memory property

Postgres returns the result as an already-parsed `json` column, so the document is whole in
the process before any of it can be iterated — 292 MB, not 5.3 MB, on the measurement in §2.2.
A `jsonb_path_query_array` projection would fix it and was deliberately not attempted: the
column is `json` not `jsonb`, the cast is not free on a 90 MB document, and untested SQL that
first meets a real database at deploy is the risk migration review exists to avoid. Acceptable
only because ADR 0004 deploys the local workstation, which uses `DiskJobStore`. A hosted
deployment generating a list from a very large crawl will spend the memory.

### 6.4 Migration `0007` has never run against a real database

Rendered for the PostgreSQL dialect offline. No PostgreSQL server is reachable from this
workstation and `psycopg` is not installed, so it is covered by an in-memory fake cursor only
— the same posture migrations 0002–0005 carry (build-log 0098, 0117).

### 6.5 `UrlListInvocation.source` is left empty worker-side

Which subset an operator picked ("orphans" / "all") is a cloud-side label, deliberately not
carried in the signed claims: it would be one more signed field existing only to be displayed.
The confirmation modal names it; the worker's own summary names the crawl, the count, a sample
and the fingerprint, which is what identifies the list.

---

## 7. Files changed

### 7.1 In the implementing commit `cc7dac1` (33 files, +4,520 / −48)

| Area | Files |
| :--- | :--- |
| New, `src/` | `api/url_list_routes.py`, `core/json_stream.py`, `modules/seo/screaming_frog_control/url_list.py`, `.../worker_url_list.py` |
| New, migration | `alembic/versions/0007_worker_dispatch_url_lists.py` |
| Modified, `src/` | `api/worker_dashboard_routes.py`, `api/worker_route_helpers.py`, `api/worker_routes.py`, `api/worker_schemas.py`, `core/config.py`, `core/postgres_store.py`, `core/postgres_worker_dispatch_store.py`, `core/state_store.py`, `core/worker_dispatch_schemas.py`, `core/worker_dispatch_signing.py`, `core/worker_dispatch_store.py`, `integrations/worker_cloud_client.py`, `modules/seo/screaming_frog_control/license_check.py`, `.../schemas.py`, `.../tool.py`, `.../worker_daemon.py` |
| Tests | 7 new (`tests/api/test_url_list_routes.py`, `tests/core/test_json_stream.py`, `tests/modules/seo/screaming_frog_control/test_tool_list_mode.py`, `test_url_list.py`, `test_worker_daemon_list_mode.py`, `test_worker_url_list.py`), 6 extended |
| Documentation | **none** — which is why this entry exists |

### 7.2 In this documentation cycle

| File | Change |
| :--- | :--- |
| `docs/adr/0023-a-url-list-travels-as-a-digest.md` | new |
| `docs/build-log/0119-a-list-that-travels-as-a-hash.md` | this entry |
| `docs/build-log/README.md` | index row |
| `README.md` | feature row for list-mode dispatch |
| `docs/ARCHITECTURE.md` | module tree entries, ADR table row, §5.2's falsified claim |
| 23 `src/`, `tests/` and `alembic/` files | 40 citation rewrites, comments and docstrings only |

---

## 8. Follow-ups

1. **A test that drives a list job through `/poll`.** §4.2's gap is still open: nothing
   asserts that a confirmed list dispatch produces claims carrying the digest. The
   regression that §4.1 fixed would still not be caught by a failing test today, only by
   review. This is the highest-value item here.
2. **Worker-side `UrlSafetyPolicy` on downloaded entries** (§6.2). Bounded — the URLs are
   already parsed inside `prepare_url_list`.
3. **The UI** (§6.1), in flight separately.
4. **Run migration `0007` against a real database** (§6.4), with 0002–0005.
5. **A `jsonb` projection for `PostgresJobStore.iter_result_page_urls`** (§6.3), when a
   hosted deployment makes it matter.
