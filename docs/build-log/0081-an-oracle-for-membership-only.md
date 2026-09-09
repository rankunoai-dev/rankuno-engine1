# Cycle 0081: An oracle for membership, not scoring

- **Date**: 2026-09-09
- **Scope**: Phase 0 work item P0-7 (the opt-in RAE differential check) of
  `docs/DELIVERABLES_IMPLEMENTATION_PLAN.md`, under ADR 0011. New file
  `scripts/diff_against_rae.py`, one additive field `Settings.rae_archive_dir`
  on `src/core/config.py`, an additive `.env.example` block, and 13 new tests
  in `tests/modules/seo/deliverables/test_diff_against_rae.py`. Closes the
  P0-8 docs row for this item (build-log entry, plan/README/ARCHITECTURE
  drift, no new ADR needed).
- **Commit**: uncommitted at time of writing.
- **Quality gate**: **GREEN** — `2033 passed, 1 skipped, 1 warning` Python /
  `232 passed` UI / `Total coverage: 93.92%`. `ALL GATES PASSED.`
  (docs-scribe's own run, verbatim in §1.)

**Origin.** `docs/DELIVERABLES_IMPLEMENTATION_PLAN.md` §4, P0-7 row: "Reads
`Settings.rae_archive_dir: Path | None` (via `get_settings()`, never
`os.environ`). Skips cleanly if unset. For each crawl folder: our SF
adapter's sets vs RAE's `load_url_set` semantics, reporting differences and
matching them against a known-differences list (§7). Not part of the gate."
ADR 0011 scopes the RAE archive as "a test oracle for issue membership only
... not an oracle for scoring or layout" and requires "no RAE code is
copied." This cycle is that item, closed.

---

## 1. Gate results

`ruff format --check` was run first in isolation to confirm the correction
in §6 actually holds before trusting the full gate:

```
296 files already formatted
```

Full gate (`scripts\verify.ps1`, no `-Fix`), this session's own run, verbatim
tail:

```
=== Format ===
296 files already formatted
PASSED: Format

=== Lint ===
All checks passed!
PASSED: Lint

=== Type check ===
Success: no issues found in 68 source files
PASSED: Type check

=== Tests ===
...
TOTAL                                                           7783    381   1948    139    94%
32 files skipped due to complete coverage.
Required test coverage of 85.0% reached. Total coverage: 93.92%
2033 passed, 1 skipped, 1 warning in 136.24s (0:02:16)
PASSED: Tests

=== UI Component Tests ===
...
 Test Files  21 passed (21)
      Tests  232 passed (232)
   Start at  12:50:37
   Duration  10.61s (transform 3.30s, setup 12.51s, collect 38.64s, tests 21.93s, environment 38.51s, prepare 6.55s)

close timed out after 1000ms
Tests closed successfully but something prevents Vite server from exiting
You can try to identify the cause by enabling "hanging-process" reporter. See https://vitest.dev/config/#reporters
PASSED: UI Component Tests

ALL GATES PASSED.
Next: SDLC Step 8 - README & architecture drift audit.
```

(The "close timed out" / "Vite server" lines are Vitest's known post-run
shutdown noise on this project — present after a green result, not a
failure; the line immediately after is still `PASSED: UI Component Tests`.)

Targeted run of the new file alone, for the record (13 tests, matching
test-engineer's report):

```
tests\modules\seo\deliverables\test_diff_against_rae.py .............    [100%]
13 passed in 0.59s
```

`2033 passed` here versus `2020 passed` in
[build-log 0080](0080-recovery-had-no-way-to-say-it-was-done.md) is not this
cycle's 13 tests alone — the working tree also still carries the unrelated,
uncommitted `max_concurrent_crawls` change flagged in
[0080 §6](0080-recovery-had-no-way-to-say-it-was-done.md#6-explicitly-not-done)
and [0080 §8.3](0080-recovery-had-no-way-to-say-it-was-done.md#8-follow-ups),
which this entry did not touch and is not attempting to account for.

`drift_check.py`, verbatim (run after this entry's own file was written,
hence 152 rather than the 151 cited by 0080 — one more tracked markdown
file, this one):

```
Running Architecture & Documentation Drift Audit...

--- Drift Audit Results ---
PASSED: no drift detected across 152 markdown files.
  - all relative links resolve
  - all domain modules documented
  - all skill directories populated
```

---

## 2. What shipped

### 2.1 `scripts/diff_against_rae.py` — the differential check (P0-7)

Opt-in, read-only, not part of the gate (plan P0-7 row, and confirmed absent
from `scripts/verify.ps1`). `main()` reads `Settings.rae_archive_dir` through
`get_settings()` (CLAUDE.md §1 rule 3 — never `os.environ` directly) and
skips cleanly (exit 0, a one-line message, no exception) when the setting is
unset, the path is not a directory, or the directory has no subfolders.

For each crawl folder under the archive it does two independent reads and
diffs them by `IssueId`:

- **Ours**: `load_screaming_frog_bundle` (`src/modules/seo/deliverables/
  screaming_frog_adapter.py`) — the real adapter under the gate, unmodified,
  imported and reused rather than re-implemented.
- **RAE's**: `read_rae_style_issue`, an independent reimplementation of
  `load_url_set`'s documented column and size rules (plan §7): union
  whichever of `Address`/`Source`/`Destination` columns a file has,
  case-insensitively; skip files under 100 bytes. This is a restatement of
  documented *behaviour*, not a port — ADR 0011's "no RAE code is copied"
  extends to data as much as code (the test module's own docstring says the
  same for its fixtures). RAE's own reader is `pandas`-based; this one is
  standard library only, consistent with the rest of the repository not
  taking a `pandas` dependency for one script.

`diff_dataset_against_rae` compares the two sets per `IssueId` from
`ISSUE_CATALOGUE` and filters the four deliberate differences from plan §7
before deciding whether a mismatch is a real regression:

1. Inlinks: RAE unions `Source ∪ Destination`; the adapter reads `Source`
   only. Detected structurally (`has_destination_column`) rather than by
   issue name, so it fires on any file shaped that way, not a hard-coded
   list.
2. RAE's 100-byte skip: detected the same way (`skipped_small_file`).
3. `UNWIRED_SECURITY_ISSUES` — the ten Security `IssueId`s D3 wired that
   RAE's own table never pointed at a CSV — is a fixed `frozenset` of ten,
   pinned by a test (§3) so an edit to it is deliberate.
4. Label spelling: not filterable code because it is not reachable — every
   comparison is keyed by `IssueId`, and `RAE_LABELS` is used only to print
   a human-readable label in a reported difference, never to match on.

Anything left over after those four filters is printed as `UNEXPECTED` and
`main()` returns 1; a clean run prints `OK - matches RAE issue membership`
per folder and returns 0. A folder the adapter itself refuses
(`ScreamingFrogBundleError` — no spine file, zip-bomb guard, etc.) is
reported `SKIPPED`, not a crash, and does not fail the run: the differential
check exists to compare readers, not to re-validate the adapter's own input
guards, which have their own tests (build-log 0077).

### 2.2 `Settings.rae_archive_dir` — `src/core/config.py`

```python
rae_archive_dir: Path | None = Field(
    default=None,
    description=(
        "Directory of RAE crawl-report folders, read only by "
        "scripts/diff_against_rae.py as an issue-membership oracle. A "
        "path, not a credential; unset skips the check cleanly."
    ),
)
```

Additive only, inserted after the SEO providers block, alongside the
existing `ahrefs_api_key`/`semrush_api_key` fields. It is a filesystem path,
not a secret — the plan's Step 5 audit (§6 Q8) already covers this: "None
introduced. `rae_archive_dir` is a path, not a credential, and is optional."
The edit did not touch the `max_concurrent_crawls` region a few lines above
it, which belongs to the other in-flight session (§8).

### 2.3 `.env.example`

```
# Directory of RAE crawl-report folders. Opt-in: used only by
# scripts/diff_against_rae.py as an issue-membership oracle (ADR 0011).
# A path, not a credential. Unset skips the check cleanly.
# RAE_ARCHIVE_DIR=
```

Commented out by default, same convention as the rest of the file: nothing
runs against a real archive unless an operator who has one sets it.

---

## 3. Tests

`tests/modules/seo/deliverables/test_diff_against_rae.py` — 13 tests, all
against a synthetic RAE-shaped fixture built inline by the test module. No
RAE data enters the repository (ADR 0011's "no RAE code is copied" applied
to data, matching the stance `tests/fixtures/deliverables/sf_bundle/`
already took for the SF adapter in build-log 0074/0077).

- `TestSkipsCleanly` (3) — unset, missing-directory, and empty-directory
  archives all return 0 from `main()` without touching any adapter code.
- `TestReadRaeStyleIssue` (3) — the oracle reader unions
  `Address`/`Source`/`Destination`; skips a file under 100 bytes and flags
  it; an absent file is not a skip (never contributes `skipped_small_file`,
  since "not present" and "present but too small" are different states the
  diff logic treats differently).
- `TestDiffDatasetAgainstRae` (2) — one synthetic crawl folder exercises all
  three suppressible categories (inlinks Source-only, 100-byte skip, unwired
  Security) in the same run as a fourth, genuinely undocumented case: a CSV
  carrying both `Address` and `Source` columns, which the adapter
  deterministically reads via `Address` and the oracle reader unions via
  both. That fourth case is not explained by any of the four plan §7
  categories and is asserted to show up in `.differences`, not
  `.known` — proving the filter does not over-suppress. The second test
  pins `UNWIRED_SECURITY_ISSUES` at exactly the documented ten.
- `TestMainEndToEnd` (3) — a real regression returns 1 with `UNEXPECTED` in
  the output; a clean archive returns 0 with `OK`; a folder the adapter
  refuses is `SKIPPED`, not fatal.
- Two `Settings.rae_archive_dir` field tests — defaults to `None`; accepts a
  `Path`.

---

## 4. Design decisions

**Independent reimplementation of `load_url_set`, not an import of RAE
code.** ADR 0011 decision 6 ("No RAE code is copied") and decision 3
(Screaming Frog is a supported input format, not a driven dependency) both
point the same way: the oracle reader restates RAE's documented column/size
rules from the plan, in the standard library, rather than vendoring or
porting the `pandas`-based original. The cost is that the oracle reader is
itself untested against real RAE output inside the gate — the gate only
proves it against the synthetic fixture's known shapes (§8).

**Filter by structural signal, not by issue name.** The known-differences
filters (`has_destination_column`, `skipped_small_file`) key off what the
CSV actually looks like, not off a hard-coded list of "these issues are
allowed to differ." A future issue whose source file happens to carry a
`Destination` column inherits the inlinks exemption automatically; one that
does not, does not. This is deliberately narrower than a per-`IssueId`
allow-list, which would have had to be kept in sync by hand and would have
silently widened over time.

**Reuse the real adapter, not a copy of it.** "Ours" in the diff is a live
call to `load_screaming_frog_bundle`, so a future change to the adapter's
column-reading rules is exercised by this script automatically the next time
an operator runs it against the archive, rather than by a frozen copy of
today's behaviour.

---

## 5. Bugs found and fixed

None in `scripts/diff_against_rae.py`, the reused adapter, or the new
`Settings` field itself — test-engineer's own report names none, and this
session's independent re-run of the targeted suite and the full gate found
none either. This cycle's test suite is deliberately built to *demonstrate*
that the mechanism does not silently absorb an unanticipated mismatch as a
fifth "known difference": `TestDiffDatasetAgainstRae`'s fourth fixture case
(a CSV carrying both `Address` and `Source` columns, §3) is not covered by
any of the four documented categories and is asserted to land in
`.differences`, not `.known`. That is a proof the filter is conservative by
construction, not a bug found in it.

The one real bug encountered while gating this cycle's diff was not in this
cycle's own code — it was a stale `Format` failure inherited from
[build-log 0080](0080-recovery-had-no-way-to-say-it-was-done.md)'s markdown
fences, already fixed in the working tree before this entry's own gate run.
See §6 (Corrections) rather than duplicating it here: `scripts/verify.ps1`
gates the whole tracked tree, so a stray formatting defect anywhere fails
the same step a code change would, which is why it surfaced while closing
this cycle even though it originated in a different file.

---

## 6. Corrections

1. **The `ruff format` blank-line defect that failed `verify.ps1`'s `Format`
   step was in [build-log 0080](0080-recovery-had-no-way-to-say-it-was-done.md),
   already committed to `main`, not in this cycle's own files.** Two Python
   code fences in 0080 (`_recover_in_bg` shown twice, at what were then
   lines 33-37 and 124-128) defined a module-level function immediately
   followed by a module-level statement (`threading.Thread(...).start()`)
   with no blank line between them. Ruff's PEP 8 rule for blank lines before
   a top-level statement following a `def` (the same class of rule as
   E302/E305) applies inside a fenced code block the same way it applies to
   a real `.py` file, because `scripts/verify.ps1`'s `Format` step runs
   `ruff format --check` over the whole tracked tree, markdown fences
   included — the same mechanism [0080 §5](0080-recovery-had-no-way-to-say-it-was-done.md#5-corrections)
   already documented for a *different* defect class (a formatter rewriting
   an elided trailing comma into a one-element tuple) found in 0079's
   fences. This is a second, distinct instance of the same root cause: a
   fenced illustrative snippet is checked by the same formatter as real
   source, and a fence that is not itself independently valid, blank-line-
   complete Python fails the gate exactly as a real file would.

   The main session fixed it directly in the working tree — two blank lines
   inserted before each `threading.Thread(...).start()` line, no other
   change to 0080's prose or its cited source — and re-verified
   `ruff format --check` clean (§1 above, run in isolation before the full
   gate). Per the build-log rule against revising history, 0080's own text
   is not edited by this correction; the fix is a whitespace-only change to
   its illustrative fences to keep the tracked tree gate-clean, recorded
   here rather than in 0080 itself. `git diff --stat` for the file at the
   time of this entry: `docs/build-log/0080-recovery-had-no-way-to-say-it-was-done.md | 2 ++`
   — exactly the two blank lines, nothing else.

---

## 7. P0-8 reconciliation (plan §4, P0-1 through P0-7 vs the build-log index)

One pass, against the build-log index (`docs/build-log/README.md`) as it
stood at the start of this cycle (through 0080) plus this entry (0081).
Not a re-verification of each cycle's own gate.

| Item | Plan §4 status (before this cycle) | Build-log reality | Action taken |
| :-- | :-- | :-- | :-- |
| P0-1 Contract models | No inline "done" marker | Landed 0073 (`contracts/audit.py`, three invariants) | Marked done, cites 0073 |
| P0-2 Catalogue as data | No inline "done" marker | Landed 0073 (110-row catalogue, enum ↔ rows 1:1) | Marked done, cites 0073 |
| P0-3 Screaming Frog adapter | No inline "done" marker | Landed 0074, hardened (zip/bundle guards) 0077 | Marked done, cites 0074, notes 0077 |
| P0-4 Engine adapter | Already marked "done, build-log 0079" | Matches — landed 0079, correction on `CANONICALS_MISSING` recorded there | No change needed |
| P0-5 Fixtures | No inline "done" marker | Landed 0074 alongside P0-3; `tests/fixtures/deliverables/` exists (`sf_bundle/`, `sf_export_filenames.txt`) | Marked done, cites 0074 |
| P0-6 Import boundary | Already marked "done, build-log 0079" | Matches — `test_import_boundary.py`, `ast`-based, both directions | No change needed |
| P0-7 Differential check | Not started ("RAE diff script (P0-7) ... not started" per README.md) | This cycle | Marked done, cites 0081 (this entry); README/ARCHITECTURE rows updated to match |

No row was found overstating status (nothing claimed "done" ahead of a real
landing); the gap was entirely the opposite direction — five rows (P0-1,
P0-2, P0-3, P0-5, P0-7) had landed or, for P0-7, were landing in this cycle,
without the plan's own §4 table saying so inline, even though `README.md`'s
status table already reflected P0-1/P0-2/P0-3/P0-5 as done with citations.
`docs/DELIVERABLES_IMPLEMENTATION_PLAN.md` §4 now carries an inline "done,
build-log NNNN" marker on every P0-1 through P0-7 row, matching the style
already used for P0-4/P0-6. P0-8 itself (this docs pass) is not re-marked in
the plan table beyond what §9's sequencing note already says ("landed as
0073") — that note describes the *first* P0-8 pass (ADR 0011 to APPROVED,
the initial contract docs); this cycle is a second, narrower P0-8 pass
scoped to P0-7 only, and does not change what §9 says about 0073.

---

## 8. Explicitly not done

- **Not part of `scripts/verify.ps1` or CI**, by design (plan P0-7 row: "Not
  part of the gate"). The archive lives outside the repository and nothing
  in the gate depends on it existing.
- **Not exercised against the real RAE archive** (`RAE - Copy/rankuno-reports/`,
  49 crawl folders per the plan's Verification section). This cycle's tests
  are entirely against the synthetic fixture built in
  `test_diff_against_rae.py`; running the script against the real archive
  and reviewing its output is a manual step for an operator who has that
  archive on disk, not something this cycle did or could do inside the
  sandboxed gate.
- **No `--archive-dir` CLI override.** Settings-only (`RAE_ARCHIVE_DIR` via
  `.env.local` / `Settings.rae_archive_dir`), matching the plan row exactly
  ("Reads `Settings.rae_archive_dir`"). An operator who wants to point at a
  different archive without editing `.env.local` has no flag to do that
  with; they edit the setting or export the environment variable before
  running the script.
- **The `max_concurrent_crawls` work already present in the working tree**
  (`src/api/server.py`, `tests/api/test_server.py`, `tests/core/test_config.py`,
  parts of `.env.example`, `README.md`, `docs/ARCHITECTURE.md`) is another
  session's in-flight, uncommitted change, flagged in
  [0080 §6](0080-recovery-had-no-way-to-say-it-was-done.md#6-explicitly-not-done)
  and not touched, reviewed, or described by this entry beyond what was
  strictly necessary to add the `rae_archive_dir` lines next to it.
- **`api.err` / `api.out`** at the repository root remain untracked and
  unaddressed, as they have been since
  [0079 §6](0079-sixteen-measured-ninety-four-not.md); out of scope here.
- **Phase 1 (the rulebook) is untouched.** This cycle closes Phase 0 (P0-1
  through P0-8); `deliverables/rulebook.py` and everything in plan §5
  remains the one item left before Phase 1 can be dispatched.

---

## 9. Files changed

```
scripts/diff_against_rae.py                                  new — P0-7 differential check
src/core/config.py                                            + rae_archive_dir: Path | None (additive)
.env.example                                                   + RAE_ARCHIVE_DIR block (additive, commented)
tests/modules/seo/deliverables/test_diff_against_rae.py       new — 13 tests
docs/DELIVERABLES_IMPLEMENTATION_PLAN.md                       §4 P0-1/P0-2/P0-3/P0-5/P0-7 rows marked done with citations
README.md                                                       new status-table row for scripts/diff_against_rae.py;
                                                                 P0-3/P0-5 row's "not started" P0-7 clause removed
docs/ARCHITECTURE.md                                            "Planned, not yet implemented" table row narrowed to
                                                                 rulebook.py only; P0-7 citation added
docs/build-log/0081-an-oracle-for-membership-only.md           this entry
docs/build-log/README.md                                       +1 index row
```

Not touched by this entry: `src/api/server.py`, `tests/api/test_server.py`,
`tests/core/test_config.py` beyond what was already present (another
session's `max_concurrent_crawls` work, per the brief for this cycle); no
new ADR (P0-7 applies ADR 0011's existing "RAE archive as an oracle for
issue membership only" ruling — it does not add a new one).

---

## 10. Follow-ups

1. **Run `scripts/diff_against_rae.py` against the real `RAE - Copy/rankuno-reports/`
   archive.** An operator step, not a gate step — set `RAE_ARCHIVE_DIR` and
   read the output. This is the only way the independent reimplementation of
   `load_url_set` gets validated against real data rather than a synthetic
   fixture.
2. **`max_concurrent_crawls` still needs its own build-log entry**, as
   [0080 §8.3](0080-recovery-had-no-way-to-say-it-was-done.md#8-follow-ups)
   already said. Still not this cycle's to write.
3. **Phase 1 (rulebook)** is the next item on
   `docs/DELIVERABLES_IMPLEMENTATION_PLAN.md` — plan §5, `P1-1` through
   `P1-5`.
