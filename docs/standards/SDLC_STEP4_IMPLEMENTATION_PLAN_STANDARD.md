# 📝 SDLC Step 4 Standard: Reasoning-Driven Implementation Plan Protocol

> **Document ID**: `RKN-STD-SDLC-STEP4-V1`  
> **Status**: Binding Standard  
> **Applies To**: All Rankuno AI Platform Microservices & Modules  

---

## 1. Overview & Purpose

Step 4 converts an approved architecture (Step 2, signed off at Step 3) into a
**file-by-file execution plan**. The plan is written before implementation begins and
is specific enough that a different engineer could execute it and arrive at
substantially the same code.

A plan that says "implement the classifier" is not a plan. A plan that names the file,
the functions, their signatures, and their tests is.

---

## 2. Mandatory Plan Contents

### 2.1 File Manifest
Every file to be created or modified, with its purpose and whether it is new:

| Path | New? | Purpose |
| :--- | :--- | :--- |
| `src/modules/seo/page_classifier/signals.py` | Yes | Six consensus signal extractors |
| `tests/modules/seo/test_signals.py` | Yes | Unit tests, all network mocked |

### 2.2 Interface Declarations
Public function and class signatures, fully typed, **before** bodies are written. A
signature that cannot be written down is a design that is not finished.

### 2.3 Justified Ordering
The sequence of changes, with the reason for the order. Data contracts precede the
logic that produces them; interfaces precede implementations; tests are written
alongside, never deferred to the end.

### 2.4 Test Plan
For each unit of behaviour, state the happy path, the failure paths, and the edge cases
to be covered. Name the mocks. External services are always mocked
(`SDLC_STEP7` §2.3), so state where the boundary sits.

### 2.5 Explicit Non-Goals
What this change deliberately does **not** do, and why. This is what prevents scope
creep from being mistaken for thoroughness, and it is what a reviewer checks the diff
against.

### 2.6 Rollback Consideration
How the change is reverted if it proves wrong. For a schema or database change, state
the backward-compatibility position explicitly.

---

## 3. Rules

* **No speculative abstraction.** An interface with exactly one implementation and no
  concrete second use case in the plan must be justified in writing, or removed.
  Where a deferred second implementation *is* the justification — as in
  `docs/adr/0001` — cite the ADR.
* **No file over ~400 lines** in the plan. If a planned file exceeds it, split it now
  rather than after it is written.
* **Every `TODO` carries an issue number.** A plan that schedules unnumbered TODOs is
  scheduling technical debt.
* **The plan is a living document.** If implementation reveals the plan was wrong, stop
  and revise the plan. Do not silently diverge from it — the divergence is exactly what
  the Step 3 approval was granted against.

---

## 4. Step 4 Exit Criteria

- [ ] File manifest complete, with new/modified marked.
- [ ] All public signatures declared and fully typed.
- [ ] Implementation order stated and justified.
- [ ] Test plan covers happy path, failure paths, and edge cases per unit.
- [ ] Non-goals stated explicitly.
- [ ] Rollback position stated.
- [ ] Step 5 security and financial audit identified as the next gate, with the
      external surface (hosts, quotas, spend) already listed for it.
