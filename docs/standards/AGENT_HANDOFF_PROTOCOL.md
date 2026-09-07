# Agent Handoff Protocol

Every agent in `.claude/agents/` uses this template when it discovers work outside its current
scope, or when it must pass its task to another agent. The goal is that the receiving agent can
continue without repeating the investigation.

Transfer the compressed, high-signal state only: objective, findings, evidence, decisions,
assumptions, files, commands, unresolved questions, next action. Do not paste conversation history.

## Classify the discovery first

| Label | Meaning | Action |
| :--- | :--- | :--- |
| BLOCKING | The original task cannot safely continue. | Route to the owning agent now; original task pauses. |
| DEPENDENCY | The original task depends on this change. | Add to DEPENDENCY_SCOPE; do it, or hand off and wait. |
| NON-BLOCKING | Can be handled separately. | Write a handoff record; continue the original task. |
| OPTIONAL | Nice-to-have improvement. | Note it in the build-log "Explicitly not done" section. |
| RISK | Needs validation, not necessarily a task. | Note it with the evidence; flag to the human. |

Never silently move an OUT_OF_SCOPE item into implementation. Never hide a discovery.

## Template

```
HANDOFF TYPE:        FEATURE / BUG / UI / SECURITY / PERFORMANCE / DATA-CONTRACT / DOCS / OTHER
SOURCE TASK:         <original task, one line>
DISCOVERED TASK:     <new task, one line>
STATUS:              BLOCKING / DEPENDENCY / NON-BLOCKING / OPTIONAL / RISK
TARGET AGENT:        triage | investigator | feature-builder | bug-fixer | ui-engineer |
                     refactorer | security-auditor | api-data-engineer | test-engineer |
                     reviewer | docs-scribe

SUMMARY:             <what was discovered>
EVIDENCE:            <path:line, test names, pasted output, logs>
CURRENT UNDERSTANDING: <what is known as FACT>
ROOT CAUSE:          <only if confirmed by reproduction; otherwise "not confirmed">
HYPOTHESIS:          <if root cause not confirmed>
IMPACT:              <what could break, who is affected>
CONFIDENCE:          HIGH / MEDIUM / LOW

RECOMMENDED NEXT ACTION: <what the next agent should investigate or do first>
FILES / AREAS:       <relevant paths>
TESTS / COMMANDS:    <exact commands that reproduce or verify>
CONSTRAINTS:         <CLAUDE.md rules, ADRs, known gaps that apply>
DO NOT:              <things the next agent should avoid>
```

## Where handoffs are recorded

- In the discovering agent's final report, under a `HANDOFFS` heading.
- In the cycle's build-log entry under "Explicitly not done", so the record survives the session.
- If the item is a security finding, also in the `security-auditor` output for the cycle.
