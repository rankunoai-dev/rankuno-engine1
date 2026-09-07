# Agent Roster

The coding agents in `.claude/agents/` split the autonomous engineering workflow into
specialised roles. Claude Code loads them automatically; the main session (or a human) delegates
by name. `CLAUDE.md` binds every agent; each definition restates only the rules it enforces.

## Roles

| Agent | Type handled | Edits code | Runs the gate | Stops for HITL |
| :--- | :--- | :---: | :---: | :--- |
| `triage` | classification, dependency graph, routing | no | no | flags where stops are required |
| `investigator` | INVESTIGATION, root-cause tracing | no | targeted tests only | never (read-only) |
| `feature-builder` | NEW_FEATURE, CONFIGURATION | yes | yes | Step 3 before implementation; Step 5 audit if network or spend |
| `bug-fixer` | BUG_FIX | yes | yes | no, but never patches without reproduction |
| `ui-engineer` | UI_CHANGE in `rankuno-ui/` | yes (UI only) | UI checks | no |
| `refactorer` | REFACTOR, PERFORMANCE | yes | yes | if the refactor changes architecture |
| `security-auditor` | SECURITY, Step 5 audit | no | no | reports PASS / FAIL |
| `api-data-engineer` | API routes, schemas, job store, UI contract | yes | yes plus contract check | if the contract change is breaking |
| `test-engineer` | TESTING, Step 7 verification | tests only | yes | no |
| `reviewer` | final diff review | no | runs it if output missing | verdict only |
| `docs-scribe` | DOCUMENTATION, Steps 8 and 8b | docs only | drift check | no |

## Standard cycle

```
request
  -> triage                     classify, scope, route, name the HITL stops
  -> investigator               only when the cause or the affected flow is unclear
  -> security-auditor           before code, if the change touches network, secrets, or spend
  -> feature-builder | bug-fixer | ui-engineer | refactorer | api-data-engineer
                                 plan -> HITL stop (features) -> implement -> tests -> gate
  -> test-engineer              when the implementer's gate is red or coverage needs work
  -> reviewer                   read-only verdict on the diff
  -> docs-scribe                build-log entry, README, ARCHITECTURE, ADR, drift check
```

Not every cycle needs every agent. A one-line bug fix is `bug-fixer` then `docs-scribe`.
Every cycle ends with `docs-scribe`: the build log is mandatory (`CLAUDE.md` section 2).

## Handoffs between agents

Discoveries outside an agent's scope use `docs/standards/AGENT_HANDOFF_PROTOCOL.md`. The discovering
agent classifies the item (BLOCKING, DEPENDENCY, NON-BLOCKING, OPTIONAL, RISK), names the target
agent, and continues its own task unless the item is BLOCKING.

## Adding or changing an agent

An agent file is markdown with YAML frontmatter: `name`, `description` (this is what the main
session uses to decide when to delegate, so it must say *when* to use the agent), optional
`tools`, optional `model`. Read-only agents omit `Edit` and `Write`. Keep each file under
100 lines and point to `CLAUDE.md` and `docs/standards/` rather than duplicating them.
