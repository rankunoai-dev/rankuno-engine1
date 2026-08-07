# 📜 Rankuno Engineering & SDLC Guidelines

To ensure the AI automation codebase remains robust, maintainable, scalable, and fully documented, all development must adhere to the following standards.

---

## 1. Mandatory 8-Step SDLC Workflow

Every task, feature, bug fix, or update follows this standardized execution pipeline:

```
[Step 1: Problem & Requirement Discovery]
   │
   ▼
[Step 2: System Architecture & Data Schema Blueprint]
   │
   ▼
[Step 3: Human-in-the-Loop (HITL) Architecture Review Checkpoint] ◄── Operator Approval
   │
   ▼
[Step 4: Reasoning-Driven Implementation Plan]
   │
   ▼
[Step 5: Edge Case, Security, Rate-Limit & Financial Audit]
   │
   ▼
[Step 6: Modular Implementation]
   │
   ▼
[Step 7: Automated Verification (Build, Linters, Unit Tests)]
   │
   ▼
[Step 8: README & Architecture Drift Audit]
```

---

## 2. Documentation Drift & README Protocol

- **Single Source of Truth**: `README.md` and `docs/ARCHITECTURE.md` represent the current state of system capabilities.
- **Drift Detection**: Any time a new module, tool, API connector, or workflow is introduced, modified, or removed, the developer/agent MUST update `README.md` and `docs/ARCHITECTURE.md`.
- **IDE Notification**: If a change deviates from the documented architecture, the agent MUST explicitly notify the operator during the pull request/completion summary.

---

## 3. Human-in-the-Loop (HITL) Governance Matrix

| Action Type | Examples | Policy |
| :--- | :--- | :--- |
| **Read / Analytics** | Technical audits, SERP scraping, pulling GSC metrics, keyword clustering | Fully Automated |
| **Drafting / Generation** | Generating content briefs, draft ad copy, metadata recommendations | Automated with Operator Review |
| **Write / Financial** | Updating live client code, spending budget on Google Ads, purchasing API credits | **Human Confirmation Mandatory** |

---

## 4. Testing & Quality Standards

1. **Strict Data Typing**: Use Pydantic models for Python or TypeScript interfaces for all data boundaries.
2. **Unit Tests Required**: Every SEO tool or utility function must have associated unit tests in `tests/`.
3. **Mocking External Services**: Always mock external APIs (Google Ads, GSC, SERP scrapers) in test suites to ensure fast, deterministic CI execution without consuming quotas.
4. **Error Handling & Retries**: External HTTP calls must implement exponential backoff retry mechanisms (`tenacity` or custom wrappers).

---

*Adhere to these guidelines across all PRs, tools, and subagents.*
