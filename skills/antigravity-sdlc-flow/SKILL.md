---
name: antigravity-sdlc-flow
description: Procedural skill for executing Google Antigravity's 8-Step Reasoning-Driven SDLC Workflow (Investigation, Architecture, HITL Review, Plan, Edge Case Audit, Code, Unit Test, README Audit).
---

# ⚡ Antigravity SDLC Execution Protocol Skill

This skill defines the exact procedural workflow that any Antigravity AI Agent or Subagent MUST execute when handling a feature request, bug fix, tool development, or system refactor.

---

## 🎯 The Antigravity 8-Step SDLC Loop

```
               ┌──────────────────────────────┐
               │ 1. INVESTIGATE & DISCOVER   │
               └──────────────┬───────────────┘
                              │
               ┌──────────────▼───────────────┐
               │ 2. ARCHITECTURE & SCHEMAS    │
               └──────────────┬───────────────┘
                              │
               ┌──────────────▼───────────────┐
               │ 3. HITL REVIEW CHECKPOINT    │ ◄── User Approval
               └──────────────┬───────────────┘
                              │
               ┌──────────────▼───────────────┐
               │ 4. STEP-BY-STEP REASONING PLAN│
               └──────────────┬───────────────┘
                              │
               ┌──────────────▼───────────────┐
               │ 5. SECURITY & EDGE-CASE AUDIT│
               └──────────────┬───────────────┘
                              │
               ┌──────────────▼───────────────┐
               │ 6. MODULAR IMPLEMENTATION     │
               └──────────────┬───────────────┘
                              │
               ┌──────────────▼───────────────┐
               │ 7. AUTOMATED UNIT TESTING    │
               └──────────────┬───────────────┘
                              │
               ┌──────────────▼───────────────┐
               │ 8. README & DRIFT AUDIT      │
               └──────────────────────────────┘
```

---

## 📋 Detailed Step Execution Rules

### Step 1: Investigation & Discovery
- Inspect the codebase using `grep_search`, `list_dir`, or `view_file`.
- Never guess code logic or paths; verify existing structures first.

### Step 2: Architecture & Schema Definition
- Define typed interfaces (`Pydantic` models in Python / `TypeScript` interfaces).
- Map data boundaries (Inputs, Outputs, External APIs).

### Step 3: HITL Review Checkpoint
- Present the architectural design to the user.
- Wait for explicit user confirmation or feedback.

### Step 4: Step-by-Step Implementation Plan
- Write a clear line-by-line plan listing target files and changes.

### Step 5: Security, Rate-Limit & Edge-Case Audit
- Audit for API rate limits, anti-bot blocks, data leakage, breaking changes, and API cost impact.

### Step 6: Modular Implementation
- Write clean, modular, typed code adhering to `docs/SDLC_GUIDELINES.md`.

### Step 7: Automated Unit Testing & Build Verification
- Execute tests using `run_command` (`pytest` / `vitest`).
- Fix all lint errors and failing test assertions. Never declare success without passing tests.

### Step 8: README & Architecture Drift Audit
- Compare implementation against `README.md` and `docs/ARCHITECTURE.md`.
- If new modules/APIs were added, update `README.md` immediately and notify the user.
