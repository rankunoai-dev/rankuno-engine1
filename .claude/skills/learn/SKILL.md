---
name: learn
description: Ask the tutor agent for a senior-architect lesson on anything in this repo - a build-log entry (/learn 0127), an ADR (/learn ADR 0015), a commit (/learn last-commit, /learn 65cf0d2), a file or module (/learn async_discovery.py, /learn the job store), a concept (/learn how auth works), or the guided tour of the whole application (/learn tour, /learn tour 8). Use whenever the user says /learn, "teach me", "explain why this was built this way", or "walk me through" a part of the system.
---

# /learn - one lesson from the tutor

The tutor agent (`.claude/agents/tutor.md`) writes the lesson. This skill only turns the user's
words into a precise target and relays the result. Do not write the lesson yourself.

## 1. Resolve the target

| User says | Target to pass |
| :--- | :--- |
| a 4-digit number (`0127`) | `build-log 0127` |
| `ADR <n>` | `ADR <n, zero-padded to 4>` |
| `last-commit`, `last <n>`, a sha | that commit or range (resolve `last-commit` with `git log -1 --format=%h`) |
| a file path or module name | that file/module (confirm it exists with Glob first) |
| `tour` / `tour <n>` | `tour` / `tour <n>` |
| `last-change` or nothing | the most recent build-log entry (`ls docs/build-log`, highest number) |
| anything else | pass the user's words as a concept |

If the target is ambiguous (two files match, an ADR number does not exist), ask the user one short
question rather than guessing.

## 2. Run the tutor

```
Agent(subagent_type="tutor", run_in_background=false, prompt="
Target: <resolved target>
Depth: senior architect (the student is a full-stack developer).
Process narrative: <if this conversation produced the change, a short factual account of how the
work went: what was investigated, wrong turns, what the user decided, what failed first.
Otherwise: none available - reconstruct from the records and say so.>
Follow .claude/agents/tutor.md exactly, including running scripts/prune_lessons.py.")
```

## 3. Relay

Tell the user, briefly: the lesson's title and path, its TL;DR, and what the prune script removed.
Offer the natural next lesson (the next tour stop, or the first item under "Go deeper"). Lessons
live in `docs/learning/`, which is gitignored and holds at most the newest 5.
