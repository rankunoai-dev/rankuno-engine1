# Cycle 0158: A download for each tree category

- **Date**: 2026-10-19
- **Scope**: UI feature, no API or contract change. Each category row in the directory tree gets a "Download URLs for <category>" control that saves the URLs under that category, nested descendants included, as a CSV built in the browser from the loaded tree.
- **Commit**: `4c1f725` (`feat(ui): download the URLs under each tree category as CSV`), on branch `category-url-download`, on top of `efbe46d`. This entry is not committed; the lead commits it.
- **Commit trailer**: `Co-Authored-By: Claude Haiku 5.5`. The brief asked for Opus 5.5 as the trailer. The model that did the work was Haiku 5.5, and the lead ruled that the system attribution rule applies. The trailer records the model that did the work.
- **Quality gate**: TypeScript and targeted tests green (§1). No Python changed, so the Python gate was not run for this cycle. Figures below are the lead's and the implementer's reported runs, pasted from their reports. The scribe did not re-run vitest, per the brief.

## 1. Gate results

| Stage | Result | Run by |
| :--- | :--- | :--- |
| `npx tsc --noEmit` | exit 0 | lead |
| Targeted vitest (`categoryCsv.test.ts`, `CategoryDownload.test.tsx`, `VirtualizedTree.test.tsx`) | 3 files, 44 tests passed, exit 0 | lead |
| Full UI vitest | 60 files, 807 tests passed, exit 0 | implementer |
| `scripts/export_ui_contract.py --check` | not run | no exported type changed |
| Python gate (`verify.ps1`) | not run | no Python changed |
| `npm run build` | not run | not in brief |

The raw vitest output was not in the inputs this entry was written from, so only the counts and exit codes above are recorded.

Drift check, run after the README edit (§7):

```
Running Architecture & Documentation Drift Audit...

--- Drift Audit Results ---
PASSED: no drift detected across 260 markdown files.
  - all relative links resolve
  - all domain modules documented
  - all skill directories populated
```

## 2. What landed

The per-category control is a native `<button>` sitting beside the category row, labelled "Download URLs for <category>" and showing the count of URLs under it.

### Per file

- `rankuno-ui/src/lib/categoryCsv.ts` (79 lines):
  - `categoryPages(model, root)` walks `kids` iteratively with an explicit stack, from the category node downward. It keeps every node whose `kind` is not `"group"`, in document order, with no duplicates. A grouping node's `url` is a path the tree invented to hold children, so it is not a URL the crawl fetched.
  - `categoryCsv(model, root)` writes one header row and one row per URL, through the existing `toCsv` from `csv.ts`. Columns are `URL`, `Path` (`profile.normalized_path`), `Hierarchy level` (`profile.hierarchy_level`), `Page type` (`profile.primary_page_type`). A quarantined defaulter has no profile, so its last three cells are empty.
  - `neutralise()` prefixes a cell that starts with `=`, `+`, `-`, `@`, TAB or CR with an apostrophe. It is applied inside `categoryCsv` only.
  - `categoryFilename(label)` returns `urls-<slug>.csv`, falling back to `urls-category.csv` when the slug is empty.
- `rankuno-ui/src/components/tree/CategoryDownload.tsx` (56 lines): the control. The count is `node.cnt`. The button is disabled when the count is zero, shows the label "No URLs", and carries a `title` giving the reason. The click handler calls the existing `downloadCsv` with `categoryFilename` and `categoryCsv`.
- `rankuno-ui/src/components/tree/VirtualizedTree.tsx`: after each row with children, the list pushes a `CategoryDownload` into the rendered rows. Rows with children also get `paddingRight: 84` so their count is not drawn under the button. Leaf rows get neither.
- `rankuno-ui/src/components/tree/tree-overlay.css`: a `.vspacer .tdl` block (absolute, 78 px wide, 24 px high, right 6 px, theme variables `--line2`, `--panel`, `--dim`, `--ink`, `--faint`, `--primary`, `--mono`, `--radius`). Light and dark theme follow from the variables, the mechanism ADR 0036 describes.
- Tests: `rankuno-ui/src/lib/categoryCsv.test.ts` (181 lines), `rankuno-ui/src/components/tree/CategoryDownload.test.tsx` (127 lines).

### Why the export is built from the model, not from the screen

The tree list is windowed. The DOM holds only the rows in view, so reading rendered rows would export whatever happened to be scrolled into view or expanded. Walking `kids` in the in-memory model reaches every descendant regardless of which sections are open.

## 3. Design decisions

| Decision | Choice | Reason |
| :--- | :--- | :--- |
| Where the export is built | Client, from `DashModel` | The rows are already loaded. A server endpoint would be a second definition of "the URLs under this category". Same reasoning as `csv.ts`. |
| Contract | No change | No API route, no exported type, no `schema.ts` edit. |
| Which nodes are URLs | `kind !== "group"` | A group's `url` is invented. Pages and quarantined defaulters are URLs. |
| Count shown | `node.cnt` | The model already accumulates it as the number of URL-bearing nodes in the subtree. The control's number is then the number of CSV rows. |
| Control placement | Sibling of the row, not a child | The row has `role="button"`. A `<button>` inside it is invalid HTML, the same reason the branch control is a `span`. |
| Zero URLs | Disabled, labelled "No URLs", with a reason in `title` | A hidden control would leave the user unable to tell why a category has no download. |
| Page rows with children | Get the control, and their list includes the page itself | The page is a URL under its own category. A leaf has no children and so gets no control. |
| Formula neutralisation | In `categoryCsv`, not in `csv.ts` | Changing `csv.ts` would change the bytes of every existing export. This is recorded as a follow-up in §6. |
| Columns | Real fields only | No derived or invented columns. A quarantined defaulter's profile cells are empty rather than made up. |

## 4. Bugs found and fixed

The implementer reported no code defect in its own work. Three items are recorded because they affect how this cycle should be read.

1. **Process, not code: the lead briefly treated the planning brief as a finished build.** The brief text was returned as a result, and it was taken for the implementation. The UI engineer was then launched properly and did the build. No code was affected, but the session's record of "what was built" was wrong for a short time. Recorded so that a later reader does not take a planning brief as a build.
2. **Pre-existing, found while scoping the formula fix: `csv.ts` quotes delimiters but does not neutralise formulas.** `field()` in `rankuno-ui/src/lib/csv.ts` wraps a value in quotes when it holds `,`, `"`, CR or LF. It does not stop a leading `=`, `+`, `-`, `@`, TAB or CR from being read as a formula. Crawled paths are attacker-influenced text. This cycle fixes the new export only (§6).
3. **Test-coverage gap, found by reading, not by running.** The test "agrees with the node count the control displays" (`categoryCsv.test.ts`) checks `categoryPages(...).length === node.cnt` over one fixture built with `buildDashModel(..., "path")`. That fixture has no quarantine tree. The quarantine branch in `dashboardModel.ts` (the `quarantineRoot` and defaulter groups, around lines 495-545) sets `cnt` by a different route, and the invariant is not tested for it. The reasoning from the code is that the two agree, since defaulter leaves carry `cnt: 1` and `kind: "defaulter"`, but this is unproven. It is recorded in §6.

## 5. Corrections

None. No earlier build-log entry was found to be false by this cycle. Earlier entries were not edited.

## 6. Explicitly not done

- **Browser check at narrow widths and in dark theme.** jsdom does no layout, so the tests cannot see overlap. The 84 px right gutter (78 px button plus 6 px inset) may overlap the row's text at narrow widths. This is unverified.
- **Timed export of a multi-thousand-URL category in a real browser.** The 20,000-URL test in `categoryCsv.test.ts` asserts the build finishes in under 5 s on the test runner. It is a bound that catches an accidental quadratic walk. It is **not** a benchmark, and no browser timing exists.
- **Chunked or yielding build.** The build is synchronous. A very large category holds the main thread until the CSV string is built and the blob is created. The duration in a browser is not measured.
- **Formula neutralisation for the other exports.** `csv.ts` `field()` is unchanged, so the existing client CSV exports still do not neutralise formulas. The server-side CSV routes and `urls.xlsx` also lack it: this is the F7 finding in build-log 0140 (its §6), not fixed here. Closing it is a follow-up, not part of this cycle. Changing `csv.ts` would change the bytes of existing exports, so it was kept out of this change on purpose.
- **Count-equals-export test for the quarantine branch.** See §4.3. The test covers the path-grouped fixture only.
- **No bulk "all categories" export.** The brief asked for one download per category. Not built.
- **No `export_ui_contract.py --check`.** No exported type changed, so the check was not run.
- **No Python gate.** No Python file changed.

## 7. Files changed

Source (commit `4c1f725`): `rankuno-ui/src/lib/categoryCsv.ts` (new), `rankuno-ui/src/components/tree/CategoryDownload.tsx` (new), `rankuno-ui/src/components/tree/VirtualizedTree.tsx` (+14, -1), `rankuno-ui/src/components/tree/tree-overlay.css` (+36).

Tests (commit `4c1f725`): `rankuno-ui/src/lib/categoryCsv.test.ts` (new, 181 lines), `rankuno-ui/src/components/tree/CategoryDownload.test.tsx` (new, 127 lines).

`git show --stat 4c1f725`: 6 files changed, 493 insertions, 1 deletion.

Docs (this entry): `docs/build-log/0158-a-download-for-each-tree-category.md` (new), `docs/build-log/README.md` (index row), `README.md` (one paragraph under "The local API and the React UI" describing the control). `docs/ARCHITECTURE.md` has no per-component UI listing, so it was not changed. `CLAUDE.md` section 8 has no entry for this gap, so it was not changed.

## 8. Follow-ups

- **security-auditor / feature-builder**: neutralise formula-leading cells in `csv.ts` `field()` and in the server-side CSV routes and `urls.xlsx`, as F7 in build-log 0140 requires. This changes the bytes of existing exports, so it needs its own cycle and a decision on byte-stability.
- **test-engineer**: add a quarantine-tree case to the count-equals-export test (§4.3).
- **User or lead**: a browser check at narrow widths and in dark theme (§6), and a timed export of a multi-thousand-URL category in a real browser.
- **User**: decide whether a bulk "all categories" export is wanted.
