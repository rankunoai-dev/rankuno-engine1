# Cycle 0134: A tutor that explains every decision

- **Date**: 2026-10-02
- **Scope**: Process and tooling only. A read-only `tutor` agent, a `/learn` skill, a pruning
  script for its output, and a new SDLC Step 8c. No application code changed.
- **Commit**: not yet committed at the time of writing (branch `tutor-tooling`, based on
  `origin/main` `ea43a01`)
- **Quality gate**: partial at the time of writing, see §1.

**Numbering note**: the highest committed entry is `0133`. The main checkout's `docs/build-log/`
held nothing above `0132` uncommitted, so `0134` was free in both places.

## 0. Background

The user is a full-stack developer working towards a software-architect role. They asked for an
agent that teaches every decision taken in this repository: the problem, how it was approached,
the chosen solution, the alternatives and why they lost, bottlenecks, scale limits, and how the
change fits into the whole application. Three decisions were taken by the user:

| Question | Decision |
| :--- | :--- |
| When does a lesson get written | Both automatically after every change and on demand |
| Depth | Senior-architect level |
| Where lessons live | Private: never committed to GitHub, and capped |

On the cap, the user asked that lessons be deleted "after every five docs". This was implemented
as a **rolling window of the newest 5**, not as "delete all five once a sixth arrives". That
interpretation was stated to the user, who has not objected. It is an interpretation, not an
explicit instruction.

## 1. Gate results

Run by the lead on this worktree:

```
tests/test_prune_lessons.py          -> 7 passed
ruff format --check .                -> 583 files already formatted
ruff check .                         -> All checks passed!
mypy src scripts/prune_lessons.py    -> Success: no issues found in 160 source files
scripts/drift_check.py               -> PASSED: no drift detected across 227 markdown files.
```

FULL SUITE (`pytest --cov=src --cov-report=term`, run by the lead on this branch):
Required test coverage of 85.0% reached. Total coverage: 93.03%
3821 passed, 2 skipped in 409.36s (0:06:49)

The drift line above is the lead's run before this entry existed. The scribe's run after adding
this entry and the README paragraph is in §7.

## 2. What landed

| File | Change |
| :--- | :--- |
| `.claude/agents/tutor.md` (new, 141 lines) | The `tutor` agent. Tools `Read, Grep, Glob, Bash, Write`; may write exactly one lesson file into `docs/learning/` and change nothing else |
| `.claude/skills/learn/SKILL.md` (new, 42 lines) | `/learn <build-log \| ADR \| commit \| file \| concept \| tour>` |
| `scripts/prune_lessons.py` (new, 95 lines) | Keeps the newest N lessons (default 5) |
| `tests/test_prune_lessons.py` (new, 81 lines) | 7 tests |
| `.gitignore` | `docs/learning/` |
| `CLAUDE.md` | §2 Step 8c (Lesson); §10 step 4 |
| `.claude/skills/do/SKILL.md` | Step 5 launches `tutor` in the background after `docs-scribe` |
| `docs/AGENT_ROSTER.md` | `tutor` row and cycle-diagram line |
| `README.md` | Verification block: `prune_lessons.py` line and one paragraph on Step 8c (this entry, §7) |

**The tutor's truthfulness rules.** Every factual claim about the codebase is checked against the
code and cited `path:line`. Every judgement is tagged `[code]`, `[record]` or `[analysis]`, so a
reader can tell what the repository shows from what the tutor infers. Alternatives that were never
built or tested are not presented as project history. Numbers are never invented; measurements
carry their source and projections are labelled as such.

**Lesson structure**, 14 sections: TL;DR; the problem; how it was approached (including wrong
turns); the decision; alternatives and why they lost (table); trade-offs accepted; bottlenecks and
failure modes at 10x and 100x; the architect's lens; corners of the application touched; what a
design reviewer would ask; check your understanding (quiz); hands-on exercise; open questions;
go deeper.

**Guided tour.** `/learn tour` walks a 15-stop curriculum of the application, recording progress
in `docs/learning/tour-progress.json`.

**`prune_lessons.py`** considers only files matching the strict pattern
`YYYYMMDD-HHMMSS-<slug>.md`. The timestamp prefix makes "newest" a sort rather than a guess from
file modification times, and the pattern means `tour-progress.json` or a note the user writes by
hand is never deleted. `--keep` must be at least 1. Deletion lives in a script rather than in an
instruction to the agent because an instruction to "remember to delete" is the step an agent skips.

## 3. How it was exercised

New agent types register only when a Claude Code session starts. The first lesson (on build-log
0131's detached-method bug) was therefore produced by a `general-purpose` agent instructed to
follow `tutor.md`. From the next session the real `tutor` type was available and wrote a lesson on
cycle 0133. Both lessons are in the main checkout's `docs/learning/`, which is gitignored:

```
20261001-150525-detached-method-download-bug.md
20261002-140533-verifier-must-not-be-able-to-sign.md
```

## 4. Bugs found and fixed

None fixed in this cycle. The tutor's lessons surfaced two pre-existing defects in application
code. They are recorded here as handoffs, deliberately not fixed in a tooling change:

| # | Defect | Where | Reach | Status |
| :--- | :--- | :--- | :--- | :--- |
| 1 | `DiskWorkerStore._load` logs `worker_store_load_failed` and returns `{}` when `workers.json` is corrupt or unreadable. The next `create()` then `_save()`s only the new worker, atomically overwriting the file and silently deleting every other registration | `src/core/worker_auth.py` L393-400 (`_load`), `_save` below it | Disk backend only. `PostgresWorkerStore` is unaffected | Open; handoff. Fail-closed on load (refuse to start, or refuse writes until the file is repaired) is the obvious direction, not decided |
| 2 | `DiskWorkerStore` loads `workers.json` once, in `__init__`. A revoke or rotate in one API process is not seen by another process holding its own copy | `src/core/worker_auth.py` L391 | Not reachable today: Railway runs one API process, and multi-process hosting would select the Postgres backend | Open; handoff |

## 5. Corrections

None. No earlier entry made a claim this cycle found false. The two defects in §4 were not
previously described as working or as fixed; they were simply not recorded anywhere.

## 6. Explicitly not done

- **No enforcement.** Nothing checks that a lesson was written after a cycle; no lint rule, no
  drift-check rule, no hook. Step 8c is an instruction, like Step 8b was before anyone relied on it.
- **Lessons are not reviewed by humans.** The truthfulness rules and `[code]/[record]/[analysis]`
  tags reduce, but do not remove, the chance of a lesson stating something false. Lessons are
  never cited from code or docs, so an error in one cannot propagate into the project record.
- **Quality depends on the process narrative.** The reasoning behind a change, the wrong turns and
  the user's choices are mostly not on disk. The tutor sees them only if the main session passes a
  narrative; without one, section 3 of a lesson can only say what the records show.
- **The rolling-window cap is an interpretation** of "delete after every five docs" (§0).
- **The two defects in §4 are not fixed** and have no issue number yet.
- **No ADR.** Step 8c adds a private, gitignored learning output and changes no ruling in
  CLAUDE.md §6 or §7; it does not alter what ships or how it is verified. It is recorded in
  CLAUDE.md §2 and here.
- **The full pytest suite** had not finished when this entry was written (§1).

## 7. Documentation drift (Step 8)

`README.md`: the Verification block gained the `prune_lessons.py` command and a paragraph
describing Step 8c and the private, capped `docs/learning/` folder, linking this entry.
`docs/ARCHITECTURE.md` was not edited: it documents the `src/` tree and has no listing of
`scripts/` or `.claude/agents/` into which the new files would fit. `docs/AGENT_ROSTER.md` already
carried the `tutor` row in the staged change.

Scribe's drift check after this entry and the README edit:

```
--- Drift Audit Results ---
PASSED: no drift detected across 227 markdown files.
  - all relative links resolve
  - all domain modules documented
  - all skill directories populated
```
