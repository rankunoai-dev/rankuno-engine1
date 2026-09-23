# 🏗️ Rankuno AI Automation Platform - System Architecture & Standard Index

> **Document ID**: `RKN-ARCH-2026-V1`  
> **Status**: Binding Architecture Specification  
> **Repository Role**: Master Standards & SDLC Governance Foundation  

---

## 1. Executive Summary

This repository (`project-standards`) serves as the **Master Governance & SDLC Rules Foundation** for Rankuno's AI Automation Infrastructure. All subagents, review agents, SDLC standards, data contract conventions, and domain engineering rules are defined here and inherited by every domain engine repository built in future phases.

---

## 2. Inward-Only Dependency Rule

The platform architecture enforces an immutable inward-only dependency flow across all modules and subagents:

$$\text{api} \longrightarrow \text{modules} \longrightarrow \text{integrations} \longrightarrow \text{core}$$

`api/` is the outermost layer ([ADR 0008](adr/0008-local-api-layer-and-job-store.md)).
Nothing below it may import from it, and it adds no analysis or safety control of
its own — it is a transport over the governed tools.

**Implemented** — this tree reflects files that exist today. Planned modules are listed
separately below, per `SDLC_STEP8` §2.1 (documentation describes verified state only).

```
src/
├── core/                        # Domain-agnostic agentic infrastructure
│   ├── base_tool.py             # Governed execution pipeline (7 of 10 steps — see below)
│   ├── schemas.py               # StrictModel, RiskClass, ToolMetadata, ToolResult
│   ├── config.py                # Typed Settings singleton (ONLY os.environ reader)
│   ├── logger.py                # Structured JSON audit logging + trace context
│   ├── errors.py                # RankunoError exception hierarchy
│   ├── guardrails.py            # HITL policy engine (deny-by-default)
│   ├── rate_limiter.py          # TokenBucket + AsyncTokenBucket + CostLedger
│   ├── registry.py              # Tool catalogue & risk-surface audit
│   ├── retry.py                 # Exponential backoff with jitter (tenacity)
│   ├── url_safety.py            # SSRF guard: private-range blocker, scheme allowlist
│   ├── robots.py                # robots.txt & crawl-delay parsing (RFC 9309)
│   ├── auth.py                  # Operator identity + session tokens (ADR 0016).
│   │                            # Principal/Operator StrictModels, PBKDF2 password
│   │                            # hashing, self-contained HMAC-SHA256 bearer
│   │                            # tokens (issue_session_token/verify_session_token),
│   │                            # DiskOperatorStore. No FastAPI import — HTTP glue
│   │                            # is api/auth.py, not here. Governs *who* is
│   │                            # calling; GuardrailEngine still governs *what a
│   │                            # WRITE/FINANCIAL action may do*, unchanged
│   ├── state_store.py           # Durable background-job records. Domain-agnostic:
│   │                            # opaque request/result mappings, atomic writes
│   ├── process_supervisor.py    # Windows Job Object process supervision (ADR
│   │                            # 0013). Domain-agnostic core infrastructure,
│   │                            # not SEO-specific: launch_supervised(),
│   │                            # SupervisedProcess.terminate()/is_running(),
│   │                            # reconcile_orphans(). Reusable by any future
│   │                            # desktop-tool integration this engine
│   │                            # supervises, not only Screaming Frog
│   ├── _process_ledger.py       # PID + process-start-time ledger, independent
│   │                            # of DiskJobStore (answers "which OS process
│   │                            # is still alive", not "which job record")
│   ├── _process_orphans.py      # Startup reconciliation: named-Job-Object
│   │                            # reopen, Toolhelp32 tree-walk fallback,
│   │                            # PID+start-time matching before any kill
│   ├── _win32_bindings.py       # Deferred pywin32 import (load_win32()) so
│   │                            # importing process_supervisor.py never
│   │                            # requires Windows -- only calling it does
│   ├── worker_auth.py           # Worker daemon identity (ADR 0015 condition 2).
│   │                            # Worker/WorkerPrincipal/WorkerStore, mirroring
│   │                            # auth.py's Operator/Principal/OperatorStore
│   │                            # shape exactly -- a distinct credential type, not
│   │                            # a substitute for ADR 0016's session tokens.
│   │                            # Also holds liveness (last_seen_at +
│   │                            # worker_is_online) and the worker-reported
│   │                            # template names, and TEMPLATE_NAME_PATTERN,
│   │                            # restated from template_registry.py because core
│   │                            # may not import modules (a test asserts they agree)
│   ├── postgres_worker_store.py # The durable WorkerStore. DiskWorkerStore is
│   │                            # correct for a workstation and destructive on a
│   │                            # container host, where the filesystem is rebuilt
│   │                            # on every deploy; WORKER_STORE_BACKEND selects.
│   │                            # No fallback between them -- a silent one would
│   │                            # answer 401 to a whole fleet on a Postgres blip
│   ├── worker_dispatch_schemas.py   # WorkerJobKind (closed StrEnum, one member:
│   │                            # SCREAMING_FROG_CRAWL), WorkerJobEnvelope
│   │                            # (job_id/seed_url/template_name/correlation_id,
│   │                            # nothing else), WorkerJob, DispatchAssignmentClaims
│   ├── worker_dispatch_signing.py   # Gate (b): issue_dispatch_assignment /
│   │                            # verify_dispatch_assignment -- HMAC-signed,
│   │                            # self-contained, identity-bound artifact the
│   │                            # worker independently verifies before its own
│   │                            # GuardrailEngine.authorize() call runs
│   ├── worker_dispatch_store.py     # WorkerDispatchStore Protocol + shared errors
│   │                            # + row-mapping helper for gate (a) and the job
│   │                            # queue (ADR 0015 condition 5)
│   ├── postgres_worker_dispatch_store.py  # The one WorkerDispatchStore
│   │                            # implementation. No in-process fallback --
│   │                            # a store outage raises DispatchStoreUnavailableError,
│   │                            # never silently approves (the opposite failure
│   │                            # PostgresJobStore's disk fallback is allowed to make)
│   ├── worker_bundle_crypto.py      # At-rest bundle encryption (ADR 0015
│   │                            # condition 11): stdlib-only HMAC-SHA256
│   │                            # encrypt-then-MAC, chosen to avoid a new
│   │                            # dependency this cycle -- not a claim that
│   │                            # hand-rolled crypto is generally preferable
│   └── worker_consumed_ledger.py    # The worker daemon's own disk-backed record
│                                # of job ids already run -- the worker-side half
│                                # of gate (b)'s single-use guarantee across a
│                                # daemon restart
├── api/                         # Local HTTP API (ADR 0008). Outermost layer;
│   │                            # nothing below imports from it.
│   ├── server.py                # Implements no crawl-safety control of its own —
│   │                            # SSRF/robots/politeness are all inherited from
│   │                            # BaseTool.run(). Binds 127.0.0.1 regardless —
│   │                            # ADR 0016 authenticates *who* is calling, not
│   │                            # *what* a crawl may fetch, so this stays an open
│   │                            # proxy on a routable interface either way.
│   │                            # Runs at most MAX_CONCURRENT_CRAWLS jobs (default
│   │                            # 5) — the RAM bound; the rest get 429
│   │                            # GET /api/v1/gsc/accounts lists profile names;
│   │                            # admission refuses an unknown gsc_account (400)
│   │                            # GET /jobs/{id}/urls.xlsx (cycle 0102): the
│   │                            # whole crawl's URL list via MasterURLReport,
│   │                            # one click from the job-row "..." menu — no
│   │                            # panel, unlike reconciliation.xlsx/
│   │                            # opportunities.xlsx which need an upload first
│   │                            # Almost every route requires a bearer session
│   │                            # token (ADR 0016); org_id is derived from its
│   │                            # verified claim, never from X-Org-Id or a URL
│   │                            # path segment. Closed the CRITICAL IDOR on
│   │                            # /orgs/{org_id}/gsc-accounts and retrofitted an
│   │                            # ownership check onto 14 job-family routes that
│   │                            # had none, via api/auth.py's org_scoped_or_404
│   ├── auth.py                  # ADR 0016 HTTP glue: require_principal() (bearer
│   │                            # token -> Principal or 401), org_scoped_or_404()
│   │                            # (the one shared ownership check server.py and
│   │                            # deliverables_routes.py both use), and
│   │                            # build_auth_router() for POST /auth/login.
│   │                            # Wraps core/auth.py; no route here has its own
│   │                            # RiskClass — a login is not a BaseTool.run()
│   ├── deliverables_routes.py   # Workbook build/download HTTP surface (cycle
│                                # 0087). A separate router, not routes on
│                                # server.py, included via app.include_router();
│                                # imports ApiState only under TYPE_CHECKING so
│                                # the two modules cannot form an import cycle.
│                                # Every build (POST /jobs/{id}/deliverable,
│                                # POST /deliverables/from-screaming-frog) runs
│                                # on a worker thread behind ApiState's own
│                                # deliverable concurrency guard (independent of
│                                # FacetRouter) and returns 202 immediately —
│                                # build_workbook alone measures up to 26.3s at
│                                # the 500k-page ceiling. Every record carries
│                                # org_id; every read enforces record.org_id ==
│                                # org_id, the same shape get_job/get_result use
│   ├── worker_routes.py         # ADR 0015 cloud-side worker-dispatch HTTP
│   │                            # surface, worker-authenticated half:
│   │                            # POST /workers/heartbeat, GET
│   │                            # /workers/dispatch/poll, POST
│   │                            # /workers/jobs/{id}/upload|failed. Composes
│   │                            # the dashboard router below, so server.py
│   │                            # still mounts exactly one router
│   ├── worker_dashboard_routes.py   # The human-authenticated half, split on
│   │                            # the authentication boundary rather than an
│   │                            # arbitrary line count. POST/GET /workers
│   │                            # (human-authenticated registration/listing;
│   │                            # the listing carries last_seen_at, a server-
│   │                            # computed is_online, and offline_after_s, so
│   │                            # the UI never invents its own staleness rule);
│   │                            # POST /workers/heartbeat (worker-authenticated
│   │                            # check-in reporting this machine's local
│   │                            # .seospiderconfig names -- untrusted input,
│   │                            # pattern- and count-checked server-side);
│   │                            # GET /workers/{id}/templates (per-worker
│   │                            # dropdown source; the API host has no template
│   │                            # directory of its own on a cloud deployment);
│   │                            # POST /workers/{id}/dispatch/preview|dispatch
│   │                            # (gate a, worker-bound; confirm returns 409
│   │                            # rather than queueing for an offline worker);
│   │                            # GET /workers/dispatch/poll (worker-
│   │                            # authenticated claim + gate-b artifact
│   │                            # issuance; also records last-seen and sweeps
│   │                            # abandoned DISPATCHED jobs); POST
│   │                            # /workers/jobs/{id}/upload|failed (worker-
│   │                            # authenticated, IDOR-checked against the
│   │                            # claiming worker's own identity, not just its
│   │                            # org — a job pinned to worker A is
│   │                            # unclaimable by worker B even inside the same
│   │                            # org; upload is size-capped before the body is
│   │                            # buffered); GET /workers/jobs[/{id}] (human-
│   │                            # authenticated, org-scoped read) and GET
│   │                            # /workers/jobs/{id}/bundle (human-
│   │                            # authenticated, org-scoped, decrypt-then-
│   │                            # stream download; fails closed if the at-rest
│   │                            # key is absent or rotated)
│   └── worker_route_helpers.py  # The ownership, liveness and body-size checks
│                                # those routes perform before doing any work.
│                                # read_capped_body refuses an over-cap
│                                # Content-Length before reading a byte and
│                                # abandons a chunked body mid-stream
├── integrations/                # External API wrappers
│   ├── base_client.py           # Quota, retry, credential handling for all connectors
│   ├── http_fetcher.py          # The ONLY outbound web fetcher. Enforces SSRF,
│   │                            # robots, per-host throttling. Sync + async.
│   ├── gsc_client.py            # Search Console API (read-only scope, ADR 0010).
│   │                            # Takes `account=` to pick a named profile (ADR 0012)
│   ├── gsc_token_manager.py     # OAuth refresh per profile; identity logged as
│   │                            # oauth2://profile/<name>. Refresh is outside the
│   │                            # retry loop so a revoked token fails once
│   ├── gsc_property_validator.py# Property URL validation before any query
│   ├── gsc_schemas.py           # GscOAuthToken (SecretStr), metrics rows, errors
│   ├── llm_client.py            # Provider-agnostic LLM interface + spend metering
│   └── worker_cloud_client.py   # ADR 0015: the worker daemon's one outbound
│                                # connection, to its own cloud API. poll()/
│                                # upload_bundle()/report_failure() over httpx,
│                                # under BaseAPIClient's standard rate limiting
│                                # and audit logging. No circuit breaker for
│                                # this channel (condition 10, accepted gap) —
│                                # the daemon's own bounded backoff substitutes
└── modules/                     # Domain engines
    ├── seo/
    │   └── page_classifier/     # Phase 1 engine
    │       ├── schemas.py            # FullPageIntelligenceProfile + taxonomy
    │       ├── weights.py            # Weight profiles + site-profile seam
    │       ├── site_profile.py       # Runtime platform detection (probe pass)
    │       ├── discovery.py          # 3-path merged discovery -> PageEvidence
    │       ├── async_discovery.py    # Concurrent crawl path (level-synchronous BFS)
    │       ├── discovery_parsers.py  # Sitemap XML, DOM links, CMS payloads
    │       ├── content_signals.py    # Native title/H1/meta-description
    │       │                         # extraction (html.parser, no new dep).
    │       │                         # Hooked into discovery.SiteGraph
    │       │                         # .record_fetch, the one method both
    │       │                         # sync and async discovery call (ADR 0014)
    │       ├── tree_visualizer.py    # Standalone interactive HTML site tree
    │       ├── reports.py            # MasterURLReport: 3-sheet .xlsx (All URLs
    │       │                         # w/ GSC metrics+hierarchy+type+depth+
    │       │                         # discovery-method, By Indexability, By
    │       │                         # HTTP Status). Shipped with zero callers
    │       │                         # until GET /jobs/{id}/urls.xlsx (cycle
    │       │                         # 0102) became its first exerciser
    │       ├── tool.py               # GOVERNED ENTRY POINT. One run() = one
    │       │                         # crawl job, RiskClass.READ (ADR 0003).
    │       │                         # Input carries gsc_account: the named
    │       │                         # Search Console profile, or None (ADR 0012)
    │       ├── nav_tree_parser.py    # Header menu -> tree (footer excluded)
    │       ├── logical_hierarchy.py  # Maps URLs to menu sections; OTHERS bucket
    │       ├── url_rules.py          # Layer 0 normalisation, pre-fetch rules
    │       ├── signal_parsers.py     # The 5 structural consensus signals
    │       ├── cascading_pipeline.py # Layer 0-3 cascade + weighted consensus
    │       └── audit_export.py       # Profiles -> AuditDataset(source=ENGINE).
    │                                 # 29 of 110 issues MEASURED, 81 NOT_MEASURED
    │                                 # with reasons in notes; links never filled.
    │                                 # The four PAGE_TITLES/META_DESCRIPTION
    │                                 # pixel-width ids stay NOT_MEASURED - no
    │                                 # verified glyph-width table (ADR 0014).
    │                                 # The only page_classifier file that
    │                                 # imports contracts (build-log 0079, 0096)
    │   ├── contracts/           # Seam between the crawler and client
    │   │   │                    # deliverables (ADR 0011). Imports core only;
    │   │   │                    # never page_classifier or deliverables.
    │   │   │                    # Enforced in every direction by
    │   │   │                    # tests/modules/seo/test_import_boundary.py
    │   │   ├── issue_ids.py          # IssueCategory, Severity, Priority, IssueId
    │   │   ├── catalogue.py          # IssueSpec + ISSUE_CATALOGUE (110 rows),
    │   │   │                         # RAE_LABELS for the differential check
    │   │   ├── url_normalizer.py     # UrlNormalizer Protocol: the key function
    │   │   │                         # every adapter is handed, never imports
    │   │   └── audit.py              # AuditDataset / AuditPage / AuditLink /
    │   │                             # Coverage / AuditSource; four invariants
    │   ├── deliverables/        # Producers of AuditDataset (ADR 0011) and the
    │   │   │                    # pipeline that turns one into a workbook.
    │   │   │                    # Imports contracts and core only;
    │   │   │                    # test_import_boundary.py pins that it never
    │   │   │                    # imports page_classifier
    │   │   ├── _bundle.py            # Guarded directory-or-zip access: traversal,
    │   │   │                         # symlink, zip-bomb, nested-archive refusal
    │   │   ├── screaming_frog_adapter.py  # SF CSV export -> AuditDataset.
    │   │   │                         # Absent file = NOT_MEASURED, header-only =
    │   │   │                         # MEASURED; links never retained (D4)
    │   │   ├── rulebook.py           # Client URL-pattern rulebook -> theme_1/
    │   │   │                         # theme_2/language/business_priority on
    │   │   │                         # AuditPage. classify() order-independent
    │   │   │                         # (EXACT wins, then longest pattern);
    │   │   │                         # missing file raises unless lenient=True;
    │   │   │                         # no match/no fallback -> Others/N/A, never
    │   │   │                         # Low (build-log 0083)
    │   │   ├── scoring.py            # Per-category penalty totals (ADR 0011 D2,
    │   │   │                         # no site score). score_dataset() walks the
    │   │   │                         # catalogue, not dataset.issues, so every
    │   │   │                         # row is represented even NOT_MEASURED.
    │   │   │                         # get_severity_weights() is the calibration
    │   │   │                         # seam (build-log 0084)
    │   │   ├── workbook.py           # AuditDataset + ScoringResult -> 4-sheet
    │   │   │                         # .xlsx (Overview/Issues/Pages/Notes),
    │   │   │                         # write_only openpyxl, MAX_PAGES_PER_WORKBOOK
    │   │   │                         # = 500_000 raises WorkbookPageLimitExceededError
    │   │   │                         # (a WorkbookBuildError subclass, cycle 0087)
    │   │   │                         # instead of truncating. Every text cell routed
    │   │   │                         # through _safe_cell() so no client-supplied
    │   │   │                         # string can become a live formula
    │   │   │                         # (build-log 0084)
    │   │   ├── pipeline.py           # run_deliverable_pipeline(): theme
    │   │   │                         # (optional) -> score -> workbook. Takes
    │   │   │                         # an already-built AuditDataset and never
    │   │   │                         # loads one itself; loading dispatch lives
    │   │   │                         # in scripts/build_deliverable.py, the one
    │   │   │                         # layer allowed to import both contracts
    │   │   │                         # sides (ADR 0011 d.1, build-log 0085)
    │   │   ├── rulebook_store.py     # Disk-backed store for uploaded rulebooks
    │   │   │                         # (cycle 0087). One .xlsx + one JSON sidecar
    │   │   │                         # per record; create() validates through
    │   │   │                         # Rulebook.from_xlsx before persisting.
    │   │   │                         # Unfiltered by org_id, like DiskJobStore —
    │   │   │                         # the API layer enforces ownership
    │   │   └── build_runner.py       # run_build(): the async-job worker-thread
    │   │                             # body for src/api/deliverables_routes.py.
    │   │                             # Takes dataset_loader and normalize as
    │   │                             # parameters rather than importing
    │   │                             # to_audit_dataset/normalize_url directly —
    │   │                             # both are page_classifier-side, and
    │   │                             # deliverables/ may not import that package
    │   │                             # (ADR 0011 d.1). Catches every build-failure
    │   │                             # type via their shared ValueError base for
    │   │                             # the same reason (cycle 0087)
    │   ├── screaming_frog_control/  # ADR 0013 conditions 4-8: launches Screaming
    │   │   │                    # Frog CLI via core/process_supervisor.py under
    │   │   │                    # a RiskClass.WRITE/MANDATORY_HITL tool. Imports
    │   │   │                    # core only.
    │   │   ├── schemas.py            # ScreamingFrogTemplate/JobInput/JobOutput/
    │   │   │                         # LicenceStatus StrictModels
    │   │   ├── export_manifest.py    # --export-tabs/--bulk-export argument list,
    │   │   │                         # derived from contracts/catalogue.py and
    │   │   │                         # cross-checked against a real CLI run
    │   │   ├── template_registry.py  # .seospiderconfig name -> path; cannot
    │   │   │                         # author or validate the file's contents
    │   │   ├── license_check.py      # Offset-scoped trace.txt parse for the
    │   │   │                         # "Licence Status:" line + free-tier cap
    │   │   ├── preview_tokens.py     # Preview -> confirm token exchange that
    │   │   │                         # supplies HITL approval (condition 8)
    │   │   ├── tool.py               # ScreamingFrogControlTool: the governed
    │   │   │                         # entry point
    │   │   ├── upload_manifest.py    # ADR 0015 condition 9: untrusted-upload
    │   │   │                         # validation for the worker->cloud bundle
    │   │   │                         # path. ALLOWED_BUNDLE_FILENAMES derived
    │   │   │                         # mechanically from export_manifest.py's
    │   │   │                         # own naming transform; zip-slip/size-cap/
    │   │   │                         # encrypted-member defense; an unlisted
    │   │   │                         # member rejects the whole upload
    │   │   ├── worker_daemon_cli.py  # The process an operator actually starts:
    │   │   │                         # the `rankuno-worker` console script and
    │   │   │                         # scripts/run_worker_daemon.py. Reads the
    │   │   │                         # cloud URL/worker id/secret from Settings
    │   │   │                         # (never an argument), names missing
    │   │   │                         # settings on --check, routes SIGINT/SIGTERM
    │   │   │                         # into a between-jobs stop flag, and exits
    │   │   │                         # 3 (not 0, not a restart loop) when the
    │   │   │                         # cloud refuses the credential
    │   │   ├── worker_daemon.py      # ADR 0015: the worker daemon's whole
    │   │   │                         # lifetime. reconcile_orphans() at startup
    │   │   │                         # (condition 12), closed-enum dispatch
    │   │   │                         # (condition 7), gate (b)'s
    │   │   │                         # make_approval_callback wired into
    │   │   │                         # GuardrailEngine exactly like
    │   │   │                         # preview_tokens.py's local pattern,
    │   │   │                         # condition-8 envelope re-validation, and
    │   │   │                         # condition-10 bounded backoff
    │   │   └── progress_parser.py    # Additive to ADR 0015, not part of it:
    │   │                             # live trace.txt tailing from a background
    │   │                             # thread while a worker's own crawl runs.
    │   │                             # ScreamingFrogProgressReader (offset-scoped,
    │   │                             # rotation-aware — stops permanently rather
    │   │                             # than misattribute a rotated file's
    │   │                             # contents), ScreamingFrogProgressThrottle
    │   │                             # (coalesces before any network call, since
    │   │                             # the Postgres dispatch store opens a fresh
    │   │                             # connection per call — condition 5), and
    │   │                             # ProgressPollThread (daemon thread, joined
    │   │                             # by tool.execute() on every exit path)
    │   └── performance/         # GSC + GA4 joined onto a crawl. Pure domain:
    │       │                    # no I/O, no settings. Ingestion belongs in
    │       │                    # integrations/, persistence in the job store.
    │       ├── schemas.py             # GSC/GA4 metrics + resolution outcome
    │       ├── url_identity.py        # Google URL -> crawled page, with the
    │       │                          # match rate and why each miss missed
    │       ├── aggregator.py          # Section rollups keyed by whole trail.
    │       │                          # Rates recomputed, never averaged;
    │       │                          # unresolved rows held, never dropped
    │       ├── opportunity_scorer.py  # Ranked recommendations. Refuses a kind
    │       │                          # whose signal the crawl never collected,
    │       │                          # and names the reason
    │       └── gsc_export.py          # Reads the ZIP/xlsx/CSV Search Console
    │                                  # actually produces. Picks the pages tab
    │                                  # by content — the names are localised
    ├── ppc/                     # Reserved namespace, no implementation
    └── research/                # Reserved namespace, no implementation
```

**Planned, not yet implemented** (do not describe these as working):

| Path | Purpose |
| :--- | :--- |
| The React UI for `modules/seo/screaming_frog_control/` (ADR 0013) | The API surface (`preview`/confirm/templates) is implemented; no confirmation-modal UI consumes it yet — an operator would call it directly today |
| A cloud dashboard or worker-management screen for ADR 0015's worker dispatch | The backend the UI needs is complete (`api/worker_routes.py`, including liveness, per-worker templates and bundle download); the React screens themselves belong to a separate task and do not exist yet |
| A purge job for expired uploaded bundles | Still read-time filtering only (`read_upload` checks `expires_at`). Nothing deletes the row, so storage grows without bound — unchanged from build-log 0098 |
| A migration of existing disk-backed worker registrations into Postgres | Impossible by construction: the `workers.json` it would read lives on a container filesystem that has already been rebuilt. Switching `WORKER_STORE_BACKEND` to `postgres` requires re-registering each desktop once (see `alembic/versions/0003_worker_identity_table.py`) |
| Any Postgres SQL in `postgres_worker_store.py` or migration 0003 verified against a real database | `psycopg` is not installed in the local venv and no server is reachable from it. Both are covered only by an in-memory fake cursor, which cannot validate SQL syntax or `COALESCE`/`ON CONFLICT` semantics |
| A Layer 2 `ZeroShotClassifier` implementation | Protocol exists; local ONNX model does not |
| An `LlmPageClassifier` implementation | Protocol exists; no concrete provider (ADR 0005) |
| `integrations/google_analytics.py` | GA4 has no ingestion at all — see build-log 0042. (A Search Console connector **does** exist: `integrations/gsc_client.py` and siblings, cycles 0055–0064; manual upload via `POST /jobs/{id}/performance/gsc` remains as an alternative. This row wrongly said "no connector exists" until cycle 0075.) |
| `modules/answer_visibility/` | Phase 7 AI Answer Visibility Engine (AEO & GEO) |

> Two rows were removed from this table in cycle 0039 because they were false.
> Crawl checkpointing **exists** (`CrawlCheckpointer`, cycle 0019) and
> `tree_visualizer.py` **shipped** — it was listed in the tree above and in this
> table at the same time. Both were already ruled closed in
> [CLAUDE.md](../CLAUDE.md) §8; this table had not caught up.
>
> A third row, "Deliverables Phase 2 upload endpoint", was removed in cycle
> 0087: `src/api/deliverables_routes.py` now implements it —
> `POST /jobs/{id}/deliverable`, `POST /deliverables/from-screaming-frog`, the
> rulebook CRUD routes, and `GET /deliverables/{id}/download` — async, job-
> gated and org-scoped. No web UI page calls it yet; that remains open, tracked
> as a handoff to `ui-engineer`, not as a gap in the API itself.
>
> A fourth row, `core/circuit_breaker.py`, was removed in cycle 0098: the file
> exists (`CLOSED`/`OPEN`/`HALF_OPEN`, 5-failure threshold, 30s recovery
> timeout) and is wired into both `core/postgres_store.py` (Postgres
> connection resilience, cycle 0084) and `integrations/gsc_token_manager.py`
> (OAuth token-refresh calls, since 2026-09-12 — predating ADR 0015's own
> Context section, which first corrected CLAUDE.md §8's "does not exist"
> framing but under-described the primitive as scoped to Postgres only).
> Nothing wires it, or any circuit breaker, to the ADR 0015 worker-dispatch
> HTTP channel specifically — that remains an accepted v1 gap (ADR 0015
> condition 10), distinct from the file not existing at all.
>
> A fifth row, "A live progress bar on `WorkerJobsPanel.tsx`", was removed in
> cycle 0101: the panel now renders one (`DispatchProgress`, gated on
> `job.status === "dispatched" && job.progress_pct != null`, no clamping or
> monotonic-increase assumption), and the old "there is no progress column and
> there will not be one" docstring was replaced with an explanation of why
> that reasoning no longer holds rather than deleted outright — see
> [build-log 0101](build-log/0101-a-percentage-is-no-longer-invented.md).

> **Pipeline status**: `base_tool.py` implements 7 of the specified 10 steps. Idempotency
> key validation, circuit breaker checks, and state checkpointing are **not** implemented.
> See [CLAUDE.md](../CLAUDE.md) §7 ruling 2 and §8.

---

## 3. SDLC 8-Step Standards Index

Every code change across Rankuno microservices MUST follow the 8-Step SDLC loop specified in `docs/standards/`:

1. 🔍 **Step 1**: [SDLC Step 1: Investigation & Requirement Discovery Standard](standards/SDLC_STEP1_INVESTIGATION_STANDARD.md)
2. 📐 **Step 2**: [SDLC Step 2: System Architecture & Data Schema Standard](standards/SDLC_STEP2_ARCHITECTURE_SCHEMA_STANDARD.md)
3. 🛡️ **Step 3**: [SDLC Step 3: HITL Architecture Review Checkpoint Standard](standards/SDLC_STEP3_HITL_REVIEW_STANDARD.md)
4. 📝 **Step 4**: [SDLC Step 4: Implementation Plan Standard](standards/SDLC_STEP4_IMPLEMENTATION_PLAN_STANDARD.md)
5. 🔐 **Step 5**: [SDLC Step 5: Security, Rate-Limit & Financial Audit Standard](standards/SDLC_STEP5_SECURITY_FINANCIAL_AUDIT_STANDARD.md)
6. 💻 **Step 6**: [SDLC Step 6: Step-by-Step Modular Implementation Standard](standards/SDLC_STEP6_MODULAR_CODING_STANDARD.md)
7. 🧪 **Step 7**: [SDLC Step 7: Automated Verification & Testing Standard](standards/SDLC_STEP7_AUTOMATED_TESTING_STANDARD.md)
8. 📚 **Step 8**: [SDLC Step 8: README & Architecture Drift Audit Standard](standards/SDLC_STEP8_README_DRIFT_AUDIT_STANDARD.md)

---

## 4. Specialized Domain & Review Agent Skills Index

Procedural skills in `skills/` equipping subagents and review agents with domain rules:

- ⚡ **SDLC Execution Flow**: [Antigravity 8-Step SDLC Protocol](../skills/antigravity-sdlc-flow/SKILL.md)
- 🔍 **SEO Domain Reference**: [SEO Engine & Domain Engineering Guide](../skills/seo-engine-guide/SKILL.md)
- 📐 **Data Contracts**: [Pydantic v2 Schema Design Standards](../skills/pydantic-schema-design/SKILL.md)
- 🤖 **Code Quality & PR Review**: [Code Reviewer Agent Protocol](../skills/code-reviewer-agent/SKILL.md)
- 🧩 **Delegation**: [Subagent Orchestration Protocol](../skills/subagent-orchestrator/SKILL.md)

Planned but not yet written: GSC/GA4 analytics, Google Ads policy, SEO scraping audit,
and AEO/GEO visibility skills.

---

## 5. Architecture Decision Records

Consequential decisions are recorded in [adr/](adr/):

| ADR | Decision |
| :--- | :--- |
| [0001](adr/0001-scale-target-and-deferred-100m-path.md) | Build for 20k–500k URLs; defer the 100M path behind interfaces |
| [0002](adr/0002-canonical-phase1-output-contract.md) | `FullPageIntelligenceProfile` is the canonical Phase 1 output |
| [0003](adr/0003-job-level-governance-and-async-internals.md) | One `BaseTool.run()` is one crawl job, not one page |
| [0004](adr/0004-local-first-deployment-swappable-ml-layer.md) | Local-workstation deployment first; ML layers behind interfaces |
| [0005](adr/0005-llm-provider-strategy-and-cost-metering.md) | Provider-agnostic `LLMClient`; per-call spend metering |
| [0006](adr/0006-weight-profile-seam-and-runtime-site-detection.md) | Signal weights vary by runtime-detected site profile, behind a seam |
| [0007](adr/0007-dom-discovery-budget-reserve.md) | Reserve part of the crawl budget for DOM-only discoveries |
| [0008](adr/0008-local-api-layer-and-job-store.md) | Local HTTP API as the outermost layer; durable job store |
| [0010](adr/0010-gsc-api-security-and-safety-controls.md) | Search Console API security and safety controls |
| [0011](adr/0011-deliverables-boundary-and-screaming-frog-input.md) | `AuditDataset` contract as the seam to deliverables; Screaming Frog is an input format, never a driven dependency |
| [0012](adr/0012-gsc-account-profiles.md) | Named Search Console profiles as `GSC_ACCOUNTS__<name>__*` env keys; a crawl selects one by name; the API publishes names only, never credentials; unknown name is refused, never defaulted |
| [0013](adr/0013-screaming-frog-cli-process-governance-exception.md) | Governance exception lifting ADR 0011 §3's ban on driving Screaming Frog via CLI, conditional on 8 binding security requirements (real Windows Job Object, independent PID+start-time ledger, same-process design, `UrlSafetyPolicy` seed-URL gate, explicit CLI field mapping, named license-failure error, `RiskClass.WRITE`/`MANDATORY_HITL`). Status: APPROVED. Conditions 1–3 implemented [build-log 0095](build-log/0095-a-crash-the-kernel-cleans-up.md); conditions 4–8 implemented (build-log entry pending — docs-scribe) as `modules/seo/screaming_frog_control/`. No React UI consumes the preview/confirm API yet |
| [0014](adr/0014-native-title-h1-meta-description-extraction.md) | Extract title/H1/meta description natively at fetch time (`content_signals.py`, `html.parser`, no new dependency), hooked into the one `SiteGraph.record_fetch` method both sync and async discovery share. 13 of 17 `PAGE_TITLES`/`META_DESCRIPTION`/`H1` catalogue ids move to `MEASURED`; the 4 pixel-width ids stay `NOT_MEASURED` by design fallback — no verified glyph-width table available, and a live font-rendering substitute would be non-deterministic across machines. [build-log 0096](build-log/0096-twenty-nine-measured-eighty-one-not.md) |
| [0015](adr/0015-cloud-local-desktop-worker-architecture.md) | Self-hosted-runner pattern for `RiskClass.WRITE` Screaming Frog dispatch: a cloud API queues a job for one pinned worker daemon; the daemon polls, never accepts an inbound connection. 14 binding conditions, chief among them a **dual** approval gate — cloud-side preview/confirm (gate a, Postgres-backed, worker-bound) plus a worker-independently-verified signed assignment (gate b, never a bare boolean) — and per-worker credentials distinct from ADR 0016's session tokens. Status: APPROVED. Implemented as `core/worker_auth.py`, `core/worker_dispatch_signing.py`, `core/worker_dispatch_store.py`/`core/postgres_worker_dispatch_store.py`, `core/worker_bundle_crypto.py`, `api/worker_routes.py`, `modules/seo/screaming_frog_control/upload_manifest.py`/`worker_daemon.py`, `integrations/worker_cloud_client.py` [build-log 0098](build-log/0098-expires-at-is-not-deletion.md). No React UI (cloud dashboard or worker-management screen) this cycle; uploaded-bundle "automatic expiry" (condition 11) is read-time filtering only, no purge job exists yet. Live progress telemetry (`progress_parser.py`, `POST /workers/jobs/{id}/progress`) added additively in [build-log 0100](build-log/0100-mcompleted-twice-with-two-meanings.md); `WorkerJobsPanel.tsx` now renders it as a progress bar [build-log 0101](build-log/0101-a-percentage-is-no-longer-invented.md) |
| [0016](adr/0016-cloud-api-authentication.md) | Session-token authentication and an org-ownership retrofit for `src/api/server.py`, closing a CRITICAL unauthenticated-GSC-credential-access finding and a HIGH cross-tenant job-access finding across 14 routes. Status: APPROVED. Implemented as `core/auth.py`/`api/auth.py` (`Principal`/`Operator`, PBKDF2 password hashing, self-contained HMAC-SHA256 session tokens, `require_principal`, `org_scoped_or_404`, `POST /auth/login`) [build-log 0097](build-log/0097-the-header-that-verified-nothing.md) |

---

## 6. Master Engineering Specifications & Blueprints

- 🤖 **Agent Operating Instructions**: [CLAUDE.md](../CLAUDE.md)
- 📓 **Build Log** — per-cycle implementation records: [build-log/](build-log/README.md)
- ⚡ **Tech Stack & Cost-Optimization Specification**: [TECH_STACK_SPECIFICATION.md](TECH_STACK_SPECIFICATION.md)
- 🛒 **Amazon-Scale E-Commerce Crawling Strategy**: [AMAZON_SCALE_ECOMMERCE_CRAWL_SPECIFICATION.md](AMAZON_SCALE_ECOMMERCE_CRAWL_SPECIFICATION.md)
- 🌳 **Interactive Multi-Level Tree Visualizer Specification**: [TREE_VISUALIZER_SPECIFICATION.md](TREE_VISUALIZER_SPECIFICATION.md)
- 📋 **Master System Context & Handoff Directive**: [CLAUDE_HANDOFF_DIRECTIVE.md](CLAUDE_HANDOFF_DIRECTIVE.md)
- 🌐 **HighRadius Crawl & 3-Path Discovery Record**: [HIGHRADIUS_CRAWL_AUDIT_RECORD.md](HIGHRADIUS_CRAWL_AUDIT_RECORD.md)
- 📄 **Master Engineering, SDLC & DevOps Standard**: [MASTER_SDLC_AND_DEVOPS_GOVERNANCE.md](MASTER_SDLC_AND_DEVOPS_GOVERNANCE.md)
- 📄 **Phase 1 Page Classification Blueprint**: [PHASE1_PAGE_CLASSIFICATION_BLUEPRINT.md](PHASE1_PAGE_CLASSIFICATION_BLUEPRINT.md)
- 📄 **Phase 7 AI Answer Visibility Blueprint**: [PHASE7_AI_ANSWER_VISIBILITY_BLUEPRINT.md](PHASE7_AI_ANSWER_VISIBILITY_BLUEPRINT.md)

---

*Maintained by the AI Lead & Engineering Team at Rankuno.*
