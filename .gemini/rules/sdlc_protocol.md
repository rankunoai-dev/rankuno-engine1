# 🛡️ Rankuno AI Engine - SDLC Protocol & IDE Coding Rules

This document establishes the mandatory lifecycle protocol for any developer or AI coding agent working in this repository.

---

## 🔁 Mandatory 8-Step SDLC Execution Workflow

For ANY new task, feature, bug fix, or refactor, the AI agent and developer MUST follow this strict sequence:

### Step 1: Investigation & Problem Discovery
- Analyze the user request, domain requirements, and existing code.
- Identify missing dependencies, domain rules, and potential impact on existing modules.

### Step 2: High-Level Architecture & System Blueprint
- Draft/update the system architecture for the feature.
- Define explicit data structures, input/output schemas (Pydantic / TypeScript), and external API contracts.

### Step 3: Human-in-the-Loop (HITL) Architecture Review Checkpoint
- Present the proposed architecture to the operator/lead.
- STOP and request explicit feedback or approval before writing code.

### Step 4: Reasoning-Driven Implementation Plan
- Formulate a line-by-line implementation plan.
- Explicitly justify design choices and component dependencies.

### Step 5: Comprehensive Security, Edge-Case & Failure Audit
- Audit for potential failure modes:
  - **Rate Limits & API Quotas** (Google Ads, GSC, SERP APIs, LLM calls)
  - **Malformed / Unexpected HTML** (scrapers failing on anti-bot or structural changes)
  - **Data Privacy & API Key Exposure** (no hardcoded tokens)
  - **Financial / Spend Impact** (preventing unintentional API spend loop)
  - **Breaking Changes** to existing API contracts

### Step 6: Step-by-Step Modular Implementation
- Write code incrementally following `docs/SDLC_GUIDELINES.md`.
- Enforce strict typing, docstrings, modularity, and error handling with retries/backoffs.

### Step 7: Automated Build, Lint & Unit Test Verification
- Run static type checking and linters.
- Write and execute unit tests (pytest / vitest) covering happy paths and edge cases.
- Never declare completion without passing automated tests.

### Step 8: Documentation Drift & README Audit
- Compare changes against `README.md` and `docs/ARCHITECTURE.md`.
- If the implementation alters system capabilities, module paths, or APIs, update `README.md` immediately or notify the operator.

---

## 🚨 Drift Notification Rule
If a code change alters repository structure, environment variables, or module behavior, the agent MUST update `README.md` and log the update in `docs/INVESTIGATION_LOG.md`.
