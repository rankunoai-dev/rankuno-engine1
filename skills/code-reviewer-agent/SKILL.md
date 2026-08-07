---
name: code-reviewer-agent
description: Procedural skill for executing automated AI code reviews, security audits, Pydantic schema validation, and SDLC compliance checks.
---

# 🛡️ Code Reviewer Agent Protocol Skill

This skill defines the precise review process that any Antigravity AI Agent or subagent must execute during automated code reviews, pre-PR checks, or SDLC Step 7 verification.

---

## 🎯 Review Mission & Scope

The Code Reviewer Agent enforces high code quality, security, performance, and architecture alignment across Rankuno's automation repositories.

```
       ┌─────────────────────────────────────────────────────────┐
       │             INCOMING CODE / FEATURE PULL                │
       └────────────────────────────┬────────────────────────────┘
                                    │
       ┌────────────────────────────▼────────────────────────────┐
       │                 8-POINT REVIEW CHECKLIST                │
       │                                                         │
       │  1. Pydantic v2 Strict Typing & Validation             │
       │  2. Human-In-The-Loop (HITL) Guardrails Enforced        │
       │  3. Rate-Limiting & Exponential Retry Handling          │
       │  4. API Cost, Secret Leakage & Security Audit           │
       │  5. Error Handling & Custom Exception Hierarchy         │
       │  6. Modular Tool Isolation & Single Responsibility      │
       │  7. Unit Test Coverage & Verification Pass              │
       │  8. README & Architecture Drift Audit                  │
       └────────────────────────────┬────────────────────────────┘
                                    │
                 ┌──────────────────┴──────────────────┐
                 │                                     │
        [PASS: Proceed to Merge]             [FAIL: Return Refactoring Plan]
```

---

## 🔍 Detailed 8-Point Review Checklist

### 1. Pydantic v2 Strict Typing
- Verify all tool inputs and outputs use `pydantic.BaseModel`.
- Check that fields have explicit `Field(description=...)` annotations.
- Ensure no raw unvalidated dicts are passed across module boundaries.

### 2. HITL Guardrails Enforcement
- Ensure any action mutating state (file overwrite, database write, API spend) checks `GuardrailManager` or requests explicit user approval.
- Confirm high-risk tools define cost estimates or threshold checks.

### 3. Rate Limiting & Retry Resiliency
- Verify external API requests utilize `RateLimiter` and `@retry_with_backoff`.
- Check for anti-bot mitigation (user-agent rotation, proper request delays).

### 4. Security & Secret Leakage Prevention
- Confirm API keys and credentials are loaded strictly via `EnvironmentConfig` from `.env`.
- Ensure no hardcoded tokens, passwords, or private URLs exist in source code.

### 5. Error Handling & Exception Hierarchy
- Check that generic `except Exception:` blocks are avoided unless re-raising standard `RankunoError`.
- Ensure fail-safe default values or structured error responses are returned.

### 6. Single Responsibility & Modular Design
- Verify tools inherit from `BaseTool` in `src/core/base_tool.py`.
- Ensure business logic is separated into `src/modules/` and integrations into `src/integrations/`.

### 7. Automated Verification & Test Coverage
- Run quality gate via `.\scripts\verify.ps1` (or `pytest`).
- Check that unit tests exist in `tests/` for all new core logic and tools.

### 8. Architecture Drift Audit
- Compare modified exports and tool signatures against `README.md` and `docs/ARCHITECTURE.md`.
- Reject PRs or changes where public tools were added without updating documentation.

---

## 📝 Review Summary Template

When completing a code review, output the verdict using this structure:

```markdown
# 🛡️ Code Review Report

## Summary Verdict: [APPROVED / REVISION REQUIRED]

### Checklist Results:
- [x] Pydantic Schema Validation
- [x] HITL Safety & Financial Guardrails
- [x] Rate Limiting & Retry Backoffs
- [x] Secrets & Security Audit
- [x] Error Handling Hierarchy
- [x] Unit Test Coverage
- [x] Documentation & Drift Audit

### Findings & Action Items:
1. **[Minor/Major]**: ...
2. **[Refactoring Recommendation]**: ...
```
