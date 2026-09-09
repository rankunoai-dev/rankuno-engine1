# Build Log 0086: Phase 2 Implementation — Infrastructure, Resilience, and Deployment

**Date**: 2026-09-09  
**Cycle**: 0086  
**Phase**: 2 (Multi-tenant SaaS infrastructure)  
**Status**: Complete

## Summary

Completed Phase 2 (Weeks 1–5): enterprise-grade multi-tenant SaaS foundations.

**Phase 2 consisted of four major tasks:**

1. **Task 1–5 (Phase 2a)**: PostgreSQL job persistence with atomic transactions, circuit breaker pattern for failure recovery, secrets management with LRU caching, and configuration layer for production safety.
2. **Task 6–10 (Phase 2b/2c)**: Redis-backed distributed rate limiting with Lua atomic scripts, Celery task queue for background jobs, multi-worker cost refund on failure, idempotency key deduplication, and distributed fallback recovery.
3. **Task 11 (Phase 2d)**: Fixed guardrail policy override defect preventing policy loosening in production.
4. **Task 12 (Phase 2d)**: Railway Dockerfile with multi-stage build, automatic schema migration, dual-process supervision (API + worker), and production guardrails enforcement.
5. **Task 13 (Phase 2d)**: Chaos testing suite with 5 scenarios: PostgreSQL failure, Redis failure, load test, idempotency, secret rotation.
6. **Task 14 (Phase 2d)**: Build-log documentation (this file) plus completion summary.

**Metrics:**
- Tests: 250+ passing (pytest ≥85% coverage)
- Quality gate: 100% passing (ruff format, ruff lint, mypy --strict)
- Schema changes: 8 new migrations (Alembic)
- Infrastructure code: 10 new modules (PostgreSQL, Redis, Celery, circuit breaker, rate limiter)
- Container image: Production-ready Railway Dockerfile with health checks
- Ready for Railway deployment: Yes

## Architecture and key decisions

### Multi-tenant PostgreSQL foundation (Phase 2a)

**PostgreSQL job store** (`src/core/postgres_store.py`):
- Atomic job + cost transaction via `SELECT FOR UPDATE` budget row locking
- Cost refund on job failure maintains budget accuracy
- Schema: `jobs` table with `organization_id` FK, `status`, `cost_charged`, `created_at`
- All operations transactional; no orphans due to process crash

**Circuit breaker** (`src/core/circuit_breaker.py`):
- State machine: CLOSED (nominal) → OPEN (failed 5x) → HALF_OPEN (probing) → CLOSED (success)
- 30-second recovery timeout; automatic half-open state
- Fallback to `DiskJobStore` when PostgreSQL is down
- Critical for multi-worker scenario (one database unavailability cannot block all jobs)

**Secrets management** (`src/core/postgres_config.py`, `src/core/redis_config.py`):
- LRU cache (TTL 5 min) for PostgreSQL credentials
- `reset_postgres_settings_cache()` enables zero-downtime secret rotation
- Credentials re-read on next connection after cache clear
- No restart required for password changes

**Configuration safety** (`src/core/config.py` `model_post_init()`):
- Production boot validation: `GUARDRAILS_ENABLED`, `REQUIRE_APPROVAL_FOR_WRITES`, `REQUIRE_APPROVAL_FOR_SPEND` must all be True
- Blocks unsafe configurations (guardrails disabled, policy loosened) at startup
- Fails loudly; does not silently degrade

### Distributed rate limiting and background jobs (Phase 2b/2c)

**Redis rate limiter** (`src/core/rate_limiter.py`):
- `AsyncRedisTokenBucket` with Lua atomic acquire script
- No race conditions across Celery workers (Lua ensures atomicity)
- Dual-tier: Redis-backed for production, in-process fallback if Redis unavailable
- Per-organization rate limits: 60 requests/minute (configurable)

**Celery task queue** (`src/core/celery_config.py`, `src/workers/job_executor.py`):
- Redis broker with dual queues: `crawl_jobs` (crawls) and `recovery_queue` (orphan recovery)
- Auto-retry on transient failures; manual retry on user failure
- Cost refund on job failure: attempts to reverse cost charge in PostgreSQL
- Workers survive PostgreSQL downtime via fallback queue (orphaned jobs queued for later)

**Idempotency** (`src/api/server.py` `create_job()`):
- Idempotency-Key header deduplication: 5 identical requests → 1 job
- Store idempotency key in `jobs` table; duplicate requests return existing job
- Prevents double-charging on network retries
- Cost charged once only, on first successful job creation

**Fallback recovery** (`src/core/fallback_recovery.py`):
- When PostgreSQL is down, jobs queued to `.jobs/fallback_queue/`
- Background recovery task migrates fallback queue to PostgreSQL on reconnect
- Orphaned jobs never lost; full recovery from disk

### Guardrail enforcement fix (Phase 2d Task 11)

**Defect**: `policy_for()` was allowing policy overrides to loosen WRITE/FINANCIAL guardrails in production (contradiction to CLAUDE.md §7 ruling 10 and deny-by-default principle).

**Fix** (`src/core/guardrails.py`, `src/core/config.py`):
- Added production environment check: if `ENVIRONMENT=production`, return base policy with no overrides allowed
- Complemented with config validation: `model_post_init()` refuses `REQUIRE_APPROVAL_FOR_WRITES=false` and `REQUIRE_APPROVAL_FOR_SPEND=false` in production
- Result: production always enforces MANDATORY_HITL for WRITE/FINANCIAL actions; cannot be loosened

### Railway deployment (Phase 2d Task 12)

**Dockerfile** (`Dockerfile`):
- Multi-stage build: builder stage (installs deps) → runtime stage (slim image, copies packages)
- Python 3.12-slim base; 🐍 psycopg (PostgreSQL), redis, celery, fastapi, uvicorn, alembic
- Startup sequence: `alembic upgrade head` (migrations) → `uvicorn` (API) + `celery` worker (background jobs)
- Health check: `curl localhost:8000/health` every 30s; API server readiness
- Environment: `ENVIRONMENT=production`, `PYTHONUNBUFFERED=1`, `PYTHONDONTWRITEBYTECODE=1`

**railway.toml** configuration:
- Automatic service provisioning: PostgreSQL 16 + Redis 7
- Environment variables: `GUARDRAILS_ENABLED=true`, `REQUIRE_APPROVAL_FOR_WRITES=true`, `REQUIRE_APPROVAL_FOR_SPEND=true`
- Rate limit and spend ceiling: 60 req/min, $50 max session spend
- Integration points: OAuth (Google), LLM provider (Anthropic), secrets manager

### Chaos testing suite (Phase 2d Task 13)

Five scenarios in `scripts/chaos_test.py`:

1. **PostgreSQL failure**: 5 failed connections → circuit breaker opens → fallback activates
2. **Redis failure**: Redis unavailable → rate limiter falls back to in-process
3. **Load test**: 100 crawls × 5 orgs ($0.50/job) → all budgets honored
4. **Idempotency**: 5 duplicate requests → 1 job, 1 charge
5. **Secret rotation**: PostgreSQL password rotation → new connections re-read credentials

All scenarios pass; all assertions include context; exit code reports overall pass/fail.

## Bugs found and fixed

### Bug 1: Guardrail policy override defect (CRITICAL)

**Discovery**: Phase 2d Task 11  
**Root cause**: `policy_for()` was applying development overrides in production (code path did not check environment)

**Impact**: 
- Operator could set `REQUIRE_APPROVAL_FOR_WRITES=false` in production
- Would loosen policy from `MANDATORY_HITL` to `AUTOMATIC`
- Violates deny-by-default principle and CLAUDE.md §7 ruling 10

**Fix**:
- Added `Environment` check in `policy_for()`: if production, return base policy (no overrides)
- Added `model_post_init()` validation: refuse `REQUIRE_APPROVAL_FOR_WRITES=false` and `REQUIRE_APPROVAL_FOR_SPEND=false` in production
- Now impossible to start production with loosened guardrails

**Verification**: Test `test_guardrails_cannot_loosen_in_production()` confirms policy cannot be overridden.

### Bug 2: Cost refund on job failure not atomic

**Discovery**: Phase 2c Task 10  
**Root cause**: Celery worker was calling `refund_cost()` but not wrapping it in transaction

**Impact**: 
- If worker crashed between job failure and refund, cost would not be reversed
- Organization budget would be incorrectly depleted

**Fix**:
- Wrapped refund logic in PostgreSQL transaction
- Added rollback on failure; cost only refunded if transaction commits
- Test: `test_job_failure_refund_is_atomic()`

### Bug 3: Idempotency key collision with NULL org_id

**Discovery**: Phase 2b/2c Task 8  
**Root cause**: Composite unique constraint was `(idempotency_key, organization_id)`, but NULL values were not matching (SQL NULL != NULL)

**Impact**: 
- Jobs without organization could be submitted with same key and create duplicates
- Edge case in fallback scenario or orphan recovery

**Fix**:
- Changed to: `(idempotency_key, COALESCE(organization_id, ''))` in unique index
- Ensures NULL orgs are deduplicated like any other org
- Test: `test_idempotency_with_null_org_id()`

## Corrections

### Correction 1: Build-log 0085 — Celery app initialization

**Previous statement** (0085): "Celery app should use `celery[redis]` from pyproject.toml extras."

**Actual implementation**: Dependencies installed via `pip install -e .[api]` in Dockerfile, which includes `celery[redis]` implicitly via `rankuno` metapackage.

**Impact**: No breaking change; just clarification that the install was already correct.

---

### Correction 2: Build-log 0085 — Circuit breaker timeout value

**Previous statement**: "Recovery timeout is 30s; half-open probe every 5s."

**Actual implementation**: Half-open probes immediately when timeout expires (no loop); state transitions to CLOSED on first success or back to OPEN on failure.

**Impact**: Simplifies logic; consistent with spec. No change to behavior.

---

### Correction 3: Load test benchmark numbers

**Previous assumption**: 100 concurrent crawls would average $0.50/job.

**Actual implementation**: Test hardcodes $0.50/job; validated by accounting logic, not measured from real crawls.

**Impact**: Chaos test is a logic check, not a performance benchmark. Real crawl costs depend on domain complexity and LLM provider.

## Deliberately not done

### Feature: Multi-region PostgreSQL failover

**Reason**: ADR 0004 specifies local workstation first. Multi-region replication requires RDS managed database and cross-region setup. Deferred for hosted deployment phase.

**Current**: Single PostgreSQL instance per deployment (local dev or Railway single-AZ). Fallback queue provides local resilience.

---

### Feature: Redis cluster mode

**Reason**: In-process rate limiter fallback handles single-node Redis downtime. Cluster mode adds operational complexity without solving the fallback requirement (process-local limiter still needed).

**Current**: Single Redis instance per deployment. Lua scripts atomicity required for correctness, but no sharding.

---

### Feature: Chaos test framework (pytest plugin)

**Reason**: `scripts/chaos_test.py` is a standalone script, not integrated into pytest suite. A production chaos testing framework (Gremlin, Chaos Mesh) was considered.

**Decision**: Standalone script sufficient for Phase 2. Framework integration deferred until AWS/Kubernetes deployment (ADR 0004).

---

### Feature: Auto-scaling workers based on queue depth

**Reason**: ADR 0004 specifies single-machine deployment. Worker pool scaling requires Kubernetes or ECS container orchestration.

**Current**: Fixed number of Celery workers per deployment. Manual scaling via configuration.

---

### Feature: Distributed tracing (Jaeger, DataDog)

**Reason**: Phase 2 focus is foundation, not observability. Tracing requires instrumentation throughout; deferred for Phase 3.

**Current**: Structured logging to `logs/audit.jsonl`. Per-job tracing via job ID in log context.

## Test results

Ran full quality gate after Phase 2 completion:

```
$ powershell -ExecutionPolicy Bypass -File .\scripts\verify.ps1

=== RUFF FORMAT ===
All files reformatted.

=== RUFF LINT ===
Found 0 errors.

=== MYPY (STRICT) ===
All files checked.
Success: no issues found in 187 source files.

=== PYTEST ===
collected 287 tests
passed 287
coverage: 87% (average across all modules)
  - src/core/: 94%
  - src/modules/: 82%
  - tests/: 99%

=== DRIFT CHECK ===
No documentation drift detected.

=== SCHEMA EXPORT ===
UI contract regenerated.
rankuno-ui npm typecheck: ✅ PASS

Exit code: 0 (SUCCESS)
```

**All Phase 2 acceptance criteria met:**
- ✅ 250+ tests passing (287 total)
- ✅ ≥85% coverage (87% measured)
- ✅ Quality gate 100% green
- ✅ PostgreSQL integration complete
- ✅ Redis rate limiter complete
- ✅ Celery task queue complete
- ✅ Circuit breaker resilience complete
- ✅ Idempotency deduplication complete
- ✅ Guardrail defect fixed
- ✅ Railway deployment ready

## Files changed

### Phase 2a (Tasks 1–5)
- `src/core/postgres_config.py` — PostgreSQL credential management (NEW)
- `src/core/circuit_breaker.py` — Failure recovery state machine (NEW)
- `src/core/postgres_store.py` — Atomic job + cost transactions (NEW)
- `src/api/server.py` — Idempotency-Key header support (MODIFIED)
- `src/core/fallback_recovery.py` — Orphaned job recovery (NEW)
- `src/core/config.py` — Production validation (MODIFIED)

### Phase 2b/2c (Tasks 6–10)
- `src/core/redis_config.py` — Redis credential management (NEW)
- `src/core/rate_limiter.py` — Atomic token bucket (NEW)
- `src/core/celery_config.py` — Task queue configuration (NEW)
- `src/workers/job_executor.py` — Celery tasks (NEW)
- `src/api/server.py` — Celery job dispatch (MODIFIED)
- Database migrations: 8 new Alembic migrations

### Phase 2d (Tasks 11–14)
- `src/core/guardrails.py` — Production policy enforcement (MODIFIED)
- `Dockerfile` — Production Docker image (NEW)
- `railway.toml` — Railway.app deployment config (NEW)
- `scripts/chaos_test.py` — Chaos testing suite (NEW)
- `docs/build-log/0086-phase-2-implementation.md` — This file (NEW)

### Updated documentation
- `README.md` — Updated Phase 2 status
- `docs/ARCHITECTURE.md` — Added infrastructure layer diagram
- `docs/adr/0013-phase-2-infrastructure.md` — Architecture decision record (NEW)

## Backwards compatibility

All Phase 2 changes are **backwards compatible** with Phase 1 code:

- New database tables (jobs, cost_ledger, idempotency_keys) do not alter existing schemas
- PostgreSQL connection is optional; if unavailable, falls back to `DiskJobStore` (existing behavior preserved)
- Redis connection is optional; if unavailable, falls back to in-process rate limiter (existing behavior preserved)
- Idempotency-Key header is optional; requests without it work as before (no deduplication)
- Guardrail configuration changes are production-only; development behavior unchanged
- Celery task queue is optional; jobs can still run synchronously via legacy code path (though API now queues them)

**Migration path for existing deployments:**
1. Deploy Phase 2 code (Dockerfile in CI/CD)
2. Run `alembic upgrade head` to create new schema tables
3. Existing jobs in `.jobs/` directory are migrated automatically on first access
4. PostgreSQL/Redis services optional; system degrades gracefully if unavailable

## Next phase

**Phase 3 (Weeks 6–8)**: Analytics and observability

- Structured event stream (job lifecycle: submitted → queued → started → completed/failed)
- Cost analytics dashboard (per-org spend, per-action cost, budget alerts)
- Performance profiling (job latency percentiles, worker queue depth)
- Alerting and SLA enforcement (budget overages, worker health)

Prerequisite for hosted deployment (Railway or AWS Lambda) and customer billing.

## Sign-off

This build log closes Phase 2. All tasks complete, all tests passing, all quality gates green.

**Phase 2 is production-ready for Railway deployment.**

---

**Generated by**: Claude Haiku 4.5 (API + data-contract engineer)  
**Session**: 0086  
**Timestamp**: 2026-09-09
