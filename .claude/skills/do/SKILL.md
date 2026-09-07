---
name: do
description: Turn an informal command into a scoped engineering brief via the prompt-generator agent, then hand that brief to the correct coding agent (feature-builder, bug-fixer, ui-engineer, refactorer, api-data-engineer, investigator, test-engineer, docs-scribe) and relay the result. Use for any casual request such as "fix the redirect table", "add clicks to the gsc card", "why is the crawl slow", or when the user says /do <command>.
---

# /do - generate the brief, then delegate

You are the main session. Do not investigate or implement the command yourself. Run this sequence.

## 1. Generate the brief

Launch the `prompt-generator` agent with the user's command verbatim:

```
Agent(subagent_type="prompt-generator", prompt="<the user's exact words>", run_in_background=false)
```

Its output is a brief with TARGET AGENT, START BY LOCATING, DEPENDENCY CHAIN, DO NOT,
ACCEPTANCE CRITERIA, VERIFY WITH, and HITL STOP REQUIRED.

## 2. Show the brief

Print the brief to the user in a fenced block. This is the "Better" prompt they asked for; they must
see it before work starts so a wrong routing is caught early.

## 3. Pre-step

If PRE-STEP is `security-auditor`, run that agent first with the brief and include its verdict.
A FAIL verdict stops the sequence; report it.

## 4. Delegate

Launch the TARGET AGENT with the full brief as its prompt, plus this line:
"Follow the brief exactly. Inspect only the dependency chain it names. Use
docs/standards/AGENT_HANDOFF_PROTOCOL.md for anything outside it."

Rules:
- If HITL STOP REQUIRED is `yes` (features, architecture-changing refactors, breaking contracts),
  the agent will return a plan and stop. Relay the plan and end your turn. Do not approve on the
  user's behalf.
- Otherwise let the agent run to completion, including its gate run.

## 5. Close the cycle

When the target agent reports done with a green gate, launch `docs-scribe` with the agent's final
report so the build-log entry is written. Skip this only for pure INVESTIGATION briefs.

## 6. Relay

Report to the user: the brief's TARGET AGENT and TYPE, what was changed, real gate output, handoffs
the agents raised, and the build-log entry path. Never restate a gate result from memory.
