# Cycle 0108: The upload allow-list is derived from the issue catalogue, not from CLI argument strings

- **Date**: 2026-09-27
- **Scope**: `ALLOWED_BUNDLE_FILENAMES` re-derived from `ISSUE_CATALOGUE.sf_sources` plus the spine; the worker's silent `continue` now reports what it dropped.
- **Commit**: uncommitted at time of writing
- **Quality gate**: see §1; session-wide figures in cycle 0110
- **Session thread**: entry 3 of 6 — see [0106 §0](0106-a-pattern-that-never-reaches-the-form.md)
- **ADR**: [0018](../adr/0018-bundle-allow-list-derives-from-the-issue-catalogue.md)

## 1. Gate results

Statically obtained, reproducible without running the suite (the operator's
full-gate run was in flight; see cycle 0110).

| Measurement | Value | How it was obtained |
| :--- | :--- | :--- |
| New tests | **8** | `+7` test functions in `tests/.../test_upload_manifest.py` (+183 lines), `+1` in `test_worker_daemon.py` (+35 lines), counted from `git diff` |
| `test_upload_manifest.py` total | 20 tests | `grep -c "def test_"` |
| Allow-list size, before and after | 96 → 96 | both derivations imported and counted |
| Names the old derivation produced that no export contains | **7** | set difference, listed in §4 |
| Real export filenames the old derivation therefore excluded | **7** | same, listed in §4 |
| `ISSUE_CATALOGUE` rows stuck at `NOT_MEASURED` as a result | **7 of 110** | each of the 7 files is the sole `sf_sources` entry of exactly one catalogue row; enumerated in §4 |

## 2. What landed

`ALLOWED_BUNDLE_FILENAMES` is now
`{spine} | {name for spec in ISSUE_CATALOGUE for name in spec.sf_sources}` — one
source of truth, the same one every consumer already asks by name. The
`_filename_for()` transform and the `EXPORT_TABS`/`BULK_EXPORT` imports are
deleted from `upload_manifest.py`.

`worker_daemon._upload_bundle` still filters to the allow-list before zipping,
but now collects what it skipped and logs
`worker_bundle_files_skipped {job_id, count, files}` at WARNING, and
`worker_bundle_uploaded` carries `skipped` alongside `files`.

The rejection message for an unexpected member no longer echoes the attacker-
supplied member name into the HTTP 400 body; the name goes to a debug log and
the body names the rule.

`test_upload_manifest.py` pins the drift in **both** directions: every catalogue
`sf_sources` name is admitted, and every admitted name is a catalogue name or the
spine. A future edit to either list that breaks the correspondence fails the
gate rather than silently dropping files at run time.

## 3. Design decisions

**Derive from the consumer, not from the producer's command line.** The
requirement the gate actually has to satisfy is "every file a deliverable reads
is admissible". Deriving from the catalogue makes the failure mode
unrepresentable instead of merely tested for. Deriving from the CLI argument
strings was an attempt to satisfy "every file the worker exports is admissible",
which is a different property and, as §4 shows, not computable from those strings
at all.

**Seven exact literals, not a numeric wildcard.** Five of the filenames embed a
threshold (`70`, `400`, `985`, `200`, `561`) that Screaming Frog takes from the
*active* configuration. A pattern like `h1_over_\d+_characters\.csv` would hand
the set of admissible filenames at an untrusted upload boundary to whoever
authored the `.seospiderconfig`. The literals stay, and the hazard is written
down: those thresholds live in an operator-authored `.seospiderconfig`, an opaque
Java-serialised binary this codebase cannot read (`template_registry.py`), so a
template that changes one of them silently renames its export file and both this
list and `catalogue.py` must then be corrected by hand.

## 4. Bugs found and fixed

**The "mechanical derivation" produced seven filenames that cannot occur.** The
old chain was *catalogue filename → CLI argument spelling → naming transform →
filename*, and the middle step is lossy in two ways:

| Old derivation produced | Screaming Frog actually writes | Why |
| :--- | :--- | :--- |
| `h1_over_x_characters.csv` | `h1_over_70_characters.csv` | The argument is `H1:Over X Characters`; `X` is a placeholder Screaming Frog replaces with the configured threshold, and the transform copied the letter |
| `meta_description_below_x_pixels.csv` | `meta_description_below_400_pixels.csv` | same |
| `meta_description_over_x_pixels.csv` | `meta_description_over_985_pixels.csv` | same |
| `page_titles_below_x_pixels.csv` | `page_titles_below_200_pixels.csv` | same |
| `page_titles_over_x_pixels.csv` | `page_titles_over_561_pixels.csv` | same |
| `hreflang_incorrect_language__region_codes.csv` | `hreflang_incorrect_language_region_codes.csv` | `" & "` — stripping `&` and mapping each space leaves a **double** underscore |
| `hreflang_inconsistent_language__region_return_links.csv` | `hreflang_inconsistent_language_region_return_links.csv` | same |

Both sets were computed here by importing the old transform and the catalogue
side by side, not read off a report.

**The symptom was silent data loss, not a rejected upload.** Each of those 7
files is the sole `sf_sources` entry of exactly one catalogue row, so the
consequence was 7 of 110 issue ids reporting `Coverage.NOT_MEASURED` forever:
`PAGE_TITLES_OVER_561_PIXELS`, `PAGE_TITLES_BELOW_200_PIXELS`,
`META_DESCRIPTION_OVER_985_PIXELS`, `META_DESCRIPTION_BELOW_400_PIXELS`,
`H1_OVER_70_CHARACTERS`, `HREFLANG_INCORRECT_LANGUAGE_REGION_CODES`,
`HREFLANG_INCONSISTENT_LANGUAGE_REGION_RETURN_LINKS`.

**The hazard had already been written down, and the allow-list was built from the
transform anyway.** `export_manifest.py:16-27` carries a "Needs-verification
note" from the live 2026-09-15 run stating that a threshold embeds a number
rather than the placeholder word, that four of the five were never independently
run, and that a template overriding one of those settings "will silently change
these five output filenames, not error" — ending "Flagged rather than asserted as
fact". The next module to consume that file derived a security allow-list from
the mechanism the note had just flagged.

**The signal existed in production logs and was indistinguishable from normal.**
`screaming_frog_adapter.py` logs
`WARNING sf_sources_absent {files, count}` (currently line 293) for any catalogue
file a bundle lacks. It fired on every crawl with those seven names in it. That
warning is also the correct, expected output when a client's crawl legitimately
has no hreflang, so nothing in the log distinguished "not measured because the
site has none" from "not measured because the file was thrown away".

## 5. Corrections

**I told the team this defect caused real bundles to be rejected wholesale. That
was wrong.** `validate_and_extract_bundle` would indeed have raised
`BundleUploadError` on such a member, but it never saw one: the worker daemon
applies the *same* allow-list as a filter with a silent `continue`
(`worker_daemon._upload_bundle`), so the seven files were dropped before the zip
was built and the upload that arrived was always valid. No upload was ever
refused. The true symptom is the one in §4 — seven issue types permanently
`NOT_MEASURED`.

The evidence, from the operator's before/after runs:

| | `worker_bundle_uploaded` | catalogue rows `NOT_MEASURED` from this cause |
| :--- | :--- | :--- |
| Before | `{"files": 1}` | 7 |
| After | `{"files": 8, "skipped": 0}` | 0 |

Two notes on those figures, stated rather than smoothed: they are the operator's
measurements from a live worker run and were not reproduced here (no Screaming
Frog install or worker is reachable from this session); and `files: 1` is the
count for that particular crawl's export directory, not a claim that a full crawl
only ever produced one admissible file.

**`upload_manifest.py`'s new module docstring says "45 real Screaming Frog 19.4
export folders" (catalogue spelling 45/45, transform 0/45); the masterfile
measurement in cycle 0107 says 49 folders.** Both numbers are the operator's, from
the same archive, and I could not reconcile which subset each pass used —
`Settings.rae_archive_dir` is not populated on this machine. `README.md` describes
that archive as 49 crawls (build-log 0081). Treat 45 as "at least 45 of the 49
were checked for this property"; do not quote the two figures as if they measured
the same set.

**A docstring in this cycle's own new test file still described the rejected
design.** `tests/modules/seo/deliverables/test_masterfile_bundle_build.py`
stated that `ALLOWED_BUNDLE_FILENAMES` "is derived mechanically from the
Screaming Frog CLI arguments the worker runs". Corrected in place to name the
catalogue derivation, because that sentence was the justification a future reader
would have relied on.

## 6. Explicitly not done

- **The five thresholds are still unreadable.** Nothing in this codebase can
  parse a `.seospiderconfig`, so nothing can *verify* that a template leaves the
  five character/pixel settings at their defaults. If an operator authors a
  template that changes one, the export filename changes, the file is dropped
  again, and the only signal is the `worker_bundle_files_skipped` warning added
  this cycle. That warning is the whole mitigation.
- **`search_console_all.csv` and `analytics_all.csv` are still not admissible**,
  so the Search Console / GA4 enrichment the masterfile services read is
  unreachable through the worker path (cycle 0107 §5.2).
- **No alert or metric on a non-empty skipped set.** It is a WARNING in the
  worker's log; nothing surfaces it to the cloud API or the dashboard, so a
  future recurrence is visible only to whoever reads worker logs.
- **The four pixel-threshold filenames were never independently confirmed
  against a live run**, only the `H1:Over X Characters` one (the flag at
  `export_manifest.py:16-27` still stands). The catalogue spelling is now trusted
  because it matches real export folders, not because the mechanism was verified.
- **`export_manifest.py` still derives the CLI arguments**, and its transform note
  is unchanged. This cycle removed the allow-list's dependency on that transform;
  it did not make the transform correct.

## 7. Files changed

| File | Change |
| :--- | :--- |
| `src/modules/seo/screaming_frog_control/upload_manifest.py` | +40/-28 — catalogue-derived allow-list, `_filename_for()` deleted, non-echoing rejection message, module docstring rewritten with the seven names and the `.seospiderconfig` hazard |
| `src/modules/seo/screaming_frog_control/worker_daemon.py` | +18/-1 — skipped set collected, `worker_bundle_files_skipped`, `skipped` on `worker_bundle_uploaded` |
| `tests/modules/seo/screaming_frog_control/test_upload_manifest.py` | +183 — 7 tests including the two-way drift test |
| `tests/modules/seo/screaming_frog_control/test_worker_daemon.py` | +35 — 1 test, the skipped-set report |
| `tests/modules/seo/deliverables/test_masterfile_bundle_build.py` | docstring corrected (§5) |
| `docs/adr/0018-bundle-allow-list-derives-from-the-issue-catalogue.md` | new |

## 8. Follow-ups

1. Surface a non-empty `skipped` set to the cloud API on upload, so the drift is
   visible without reading a desktop worker's log file.
2. Add `search_console_all.csv` and `analytics_all.csv` to the catalogue-adjacent
   admissible set, or remove the services' dependency on them.
3. Confirm the four pixel filenames against a live Screaming Frog run and clear
   the `export_manifest.py:16-27` flag, or promote that flag into a test that
   fails when the two lists disagree.
4. Reconcile the 45-folder and 49-folder figures against the archive when a
   machine with `rae_archive_dir` is available, and state one number.
