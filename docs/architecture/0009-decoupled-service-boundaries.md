# ADR 0009: Decoupled Service Architecture & Worker-Queue Compatibility

## Status
Accepted

## Context
As the Rankuno AI Engine scales from local workstation execution to distributed production worker pools (e.g. Celery, Redis Task Queues, Temporal, AWS ECS / Kubernetes worker pods), feature modules must remain completely decoupled from transport, scheduling, and storage infrastructure.

If domain logic (e.g. crawler engines, reconcilers, parsers, classifiers) directly imports server frameworks, hardcodes `.jobs/` disk paths, or relies on shared process state, scaling out to distributed background workers would require massive code refactoring.

## Decision & Architectural Rules

Every new feature and engine module added to the codebase MUST strictly adhere to the following 4 Service Decoupling Rules:

### Rule 1: Pure Domain Interfaces (Zero Infrastructure Imports)
- Domain modules under `src/modules/<domain>/` must operate exclusively on pure Pydantic schemas or primitive data structures.
- Domain code **MUST NOT** import FastAPI, Starlette, Uvicorn, or concrete storage implementations.
- Domain functions must be stateless, pure, and re-entrant: `InputSchema -> OutputSchema`.

### Rule 2: Sink Callbacks for Side Effects
- Side effects (progress telemetry, intermediate checkpoints, homepage sidecar persistence, logging) must be passed into domain tools via injected callback sinks:
  - `on_progress: Callable[[Telemetry], None]`
  - `checkpoint_sink: Callable[[CheckpointData], None]`
  - `homepage_sink: Callable[[str], None]`
- The domain module invokes the sink without knowing whether the sink writes to a local `.jobs/` directory, a Redis queue, an S3 bucket, or a WebSocket stream.

### Rule 3: Distributed Worker Readiness
- Every job execution MUST be self-contained: all parameters required to run a job must be serializable inside `PageClassificationInput` (or domain payload).
- Workers running on separate servers must be able to execute any job given only the input payload, returning a fully serializable `PageClassificationOutput`.

### Rule 4: Transport-Agnostic API Adapters
- Code under `src/api/` acts strictly as a transport adapter layer.
- API handlers convert HTTP payloads into domain models, delegate execution to workers/tools, and convert domain outputs to HTTP responses.
- Adding a CLI command, a gRPC handler, or a message queue worker to trigger a feature must require **0 changes to the underlying domain code**.

---

## Verification & Enforcement
- All future features developed by AI agents and contributors must pass these decoupling boundaries.
- `drift_check.py` and test suites verify that domain modules retain 0 imports from server or CLI layers.
