# 🔍 SDLC Step 1 Standard: Investigation & Requirement Discovery Protocol

> **Document ID**: `RKN-STD-SDLC-STEP1-V1`  
> **Status**: Binding Standard  
> **Applies To**: All Rankuno AI Platform Microservices & Modules  

---

## 1. Overview & Purpose

Step 1 exists to stop work starting on a wrong premise. No architecture may be
drafted, and no code written, until the problem, the existing code, and the external
constraints have been **verified by inspection** rather than assumed.

The failure this step prevents is specific and expensive: an agent that assumes a
function signature, an API response shape, or a file path, and builds a plan on top of
it. Everything downstream inherits the error.

---

## 2. Mandatory Investigation Rules

### 2.1 Verify, Never Assume
* Read the actual code before describing what it does. Use `grep_search`, `list_dir`
  and file reads — never infer a signature from a name or a document.
* Where documentation and code disagree, **the code is the fact** and the documentation
  is the defect. Record the discrepancy; do not silently follow either one.
* Confirm a file exists before linking to it. A documented path that resolves to
  nothing is a documentation bug of the same severity as a broken import.

### 2.2 Establish the Baseline
Before changing anything, confirm the current state is green:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify.ps1
```

A pre-existing failure must be identified as pre-existing. Inheriting a red baseline
and then reporting your own change as the cause — or worse, as clean — wastes the
reviewer's time.

### 2.3 Map the Blast Radius
Identify, in writing:
* Which layers the change touches (`core` / `integrations` / `modules`).
* Which existing callers depend on the interfaces being changed.
* Whether the change crosses the Inward-Only Dependency Rule.
* Which external APIs, quotas, or credentials become newly required.

### 2.4 Surface Contradictions Immediately
Rankuno's specifications were written at different times and **do disagree**. The
authoritative resolutions live in `CLAUDE.md` §7. If investigation surfaces a conflict
not already ruled on there:

1. Do not pick one silently.
2. Record both positions and the documents they come from.
3. Escalate at the Step 3 HITL checkpoint for an explicit ruling.
4. Add the ruling to `CLAUDE.md` §7 once given.

---

## 3. Step 1 Exit Criteria

- [ ] Problem statement written in one paragraph, in terms of observable behaviour.
- [ ] Relevant existing code read and cited by path and line, not paraphrased.
- [ ] Baseline quality gate run, and its result recorded as green or pre-existing-red.
- [ ] Blast radius documented, including dependency-rule impact.
- [ ] External API constraints identified: quotas, auth model, documented rate limits.
- [ ] Any specification contradiction surfaced, with both sources named.
- [ ] Open questions listed explicitly. "None" is a valid answer only if it is true.
