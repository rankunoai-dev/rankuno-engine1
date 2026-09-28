# Cycle 0116: Three causes for one empty workbook

- **Date**: 2026-09-28
- **Scope**: The 21 RAE masterfile services stop rendering empty workbooks against a real Screaming Frog export — 4 of 21 produced rows before, 12 of 21 after — by fixing three independent causes, only one of which the brief anticipated.
- **Commit**: `0239a50` (`fix(deliverables): masterfiles produce real data instead of empty workbooks`), on branch `fix/ui-reload-restores-view-and-crawl`
- **Quality gate**: `ALL GATES PASSED.` — 3327 passed, 2 skipped, 92.72% coverage against an unchanged 85% floor; UI 43 files passed

---

## 0. Two things to read this entry with

### 0.1 The documentation was committed after the code, deliberately

`docs/build-log/README.md` rule 1 says to write the entry in the same change as
the code, because a log written later is a reconstruction. This entry breaks that
rule knowingly. The working tree was being moved by another actor mid-cycle
(§9), so the implementation was committed on its own the moment it was green, to
protect it, and the documentation follows as `0239a50`'s successor. Nothing here
is reconstructed from memory: every figure in §1 and §2 was re-derived from the
commit and from a re-run against the same export, by a different agent than the
one that wrote the code. Where the implementer's report and the tree disagree,
the tree is recorded and the disagreement is named (§5.4, §5.5).

### 0.2 This is not the "complete" that was claimed twice before

Commit `0d26e26` called these 21 services "Complete RAE masterfile parity".
[Build-log 0107 §5](0107-a-directory-that-could-never-exist.md) corrected that to
13 of 21 empty. This cycle takes 4 of 21 producing rows to 12 of 21. **Twelve is
not twenty-one.** Of the nine that still produce nothing, three are
`NOT_MEASURED` by design, five have genuinely empty inputs on the one site
measured, and one (`pagination`) is a real residual that was handed off rather
than papered over (§6.2). See §2.1 for which is which.

---

## 1. Gate results

The implementing cycle's `verify.ps1` run, verbatim:

```
PASSED: Format / PASSED: Lint / PASSED: Type check
Required test coverage of 85.0% reached. Total coverage: 92.72%
3327 passed, 2 skipped, 1 warning in 472.55s
Test Files 43 passed (43)
ALL GATES PASSED.
```

Baseline at `1fd6029` ([build-log 0113](0113-the-test-suite-was-killing-live-crawls.md))
was 88.42% over 3189 Python tests, so this cycle is **+138 tests and +4.30 points
of coverage**.

Independently re-executed by the scribe on the committed tree, not re-typed from
the report:

| Check | Command | Result |
| :--- | :--- | :--- |
| Format | `ruff format --check` on `deliverables/`, `contracts/sources.py`, `tests/.../deliverables/` | `73 files already formatted`, exit 0 |
| Lint | `ruff check` on the same paths | `All checks passed!`, exit 0 |
| Types | `mypy --strict src/modules/seo/deliverables/ src/modules/seo/contracts/sources.py` | `Success: no issues found in 35 source files` |
| Tests | `pytest tests/modules/seo/deliverables/ tests/api/test_masterfile_endpoints.py --no-cov -q` | exit 0, **345 dots, zero `F`/`E`** |

The full `verify.ps1` was **not** re-run by the scribe: a second `pytest` would
overwrite `.coverage`, and the scribe's own change is documentation-only. The
targeted run's aggregate summary line did not print — the same stdout-buffering
artifact recorded in [0098 §1](0098-expires-at-is-not-deletion.md) and
[0100](0100-mcompleted-twice-with-two-meanings.md); the 345 is a count of the
progress dots, and the exit code is 0.

### 1.1 One `VERIFICATION FAILED: Tests` that was never attributed

An earlier `verify.ps1` invocation in this cycle reported `VERIFICATION FAILED:
Tests`. That run's output had been piped through `grep … | tail -40` and the
failing test's identity was lost with it. The same command has since run green
three consecutive times, plus `pytest --cov=src` standalone twice at 92.72%. The
suite has no randomisation, no `pytest-xdist` and no ordering plugin, so there is
no obvious mechanism for order-dependence.

**It is recorded as unattributed, not as a flake.** The implementer declined to
call it a flake and so does this entry. A reader who hits a one-off test failure
in this suite should treat this paragraph as a prior, not as a dismissal.

---

## 2. What landed

### 2.1 The measurement

Every service was built against one real Screaming Frog 19.4 export —
`RAE/rankuno-reports/3c877a3d-bba9-4cf5-98f1-5175e45a4283`, 115 CSVs, roughly
24,000 pages. The "after" column below was **re-derived by the scribe** by
rebuilding all 21 workbooks from that folder and counting cells in column A that
begin `http`. Every figure reproduced exactly.

| Service | Rows before | Rows after | Why |
| :--- | ---: | ---: | :--- |
| `non_functional_internal_links` | empty | **51,965** | filenames + `INDEXABLE_ONLY=False` |
| `security` | empty | **34,347** | filenames (3 → 12 source files) |
| `directives` | 0 | **10,309** | `INDEXABLE_ONLY=False` |
| `response_codes` | 0 | **7,756** | `INDEXABLE_ONLY=False` |
| `meta_description` | 571 | **4,511** | filenames |
| `custom_extraction` | 4,847 | **4,847** | unchanged; crash fixed (§4.4) |
| `page_titles` | empty | **2,180** | filenames |
| `h1` | 570 | **1,291** | filenames |
| `url_issues` | empty | **939** | filenames |
| `content_issues` | empty | **626** | filenames |
| `canonicals` | 232 | **232** | unchanged |
| `overview_report` | **crash** | **4 sheets / 30 URL rows** | sheet-name sanitisation |

The nine that still render no rows, and which kind of nothing each one is:

| Service | Kind of nothing |
| :--- | :--- |
| `custom_search_ga4_gtm`, `custom_search_og_twitter`, `functional_internal_links` | `NOT_MEASURED` — 0 declared source files, no catalogue source exists (§6.3) |
| `duplicate_content`, `hreflang`, `lorem_ipsum`, `sitemaps`, `structured_data` | genuinely empty inputs **on this site** — verified by row-counting the source CSVs, and confirmed non-empty on other exports |
| `pagination` | **a real residual**, handed off (§6.2) |

### 2.2 `src/modules/seo/contracts/sources.py` (new, 68 lines)

`sources_for_categories()` and `sources_for_issues()` derive a service's input
filenames from `ISSUE_CATALOGUE.sf_sources`, in catalogue order, deduplicated on
first appearance. It exists so a filename can only reach a workbook by first
entering the catalogue — which is also where `ALLOWED_BUNDLE_FILENAMES` comes
from ([ADR 0018](../adr/0018-bundle-allow-list-derives-from-the-issue-catalogue.md)).
A file a service asks for is therefore, *by construction*, a file the upload
boundary accepts. No service hand-keeps a list any more.

### 2.3 `src/modules/seo/deliverables/masterfile_enrichment.py` (new, 237 lines)

Split out of `masterfile_base.py` so that file stays under the 400-line target
(it is now 350). Holds `url_column_for()`, the enrichment map builders, and
`NOT_MEASURED = "Not measured by this crawl"`. It is where the `nan`-URL defect
(§4.1) and the not-measured-is-not-zero rule (§3.1) are both stated.

### 2.4 `MasterfileService.INDEXABLE_ONLY: ClassVar[bool]`

A declared, per-service answer to "does this deliverable report on indexable
pages only?", defaulting to `True` and set `False` on exactly four services, each
with a docstring saying why. The row test reduces to
`not self.INDEXABLE_ONLY or indexability == "Indexable"`. A test pins the set to
exactly those four, so flipping one is a deliberate, reviewed act. See §3.3 and
[ADR 0020](../adr/0020-a-deliverable-declares-whether-it-reports-on-indexable-pages.md).

Verified on the committed tree:

| Service | `INDEXABLE_ONLY` | Declared source files |
| :--- | :--- | ---: |
| `directives` | `False` | 2 |
| `non_functional_internal_links` | `False` | 9 |
| `overview_report` | `False` | 95 |
| `response_codes` | `False` | 7 |
| the other 17 | `True` | 0–13 |

`overview_report`'s 95 is every allow-listed file except the spine; the allow-list
holds 96 including `internal_all.csv`.

### 2.5 The test fixture

`tests/modules/seo/deliverables/sf_export.py` (365 lines, not a `test_` module)
builds a synthetic export with **real filenames and real headers**. The headers
were observed in `RAE/rankuno-reports/` and retyped; **no RAE file was copied**,
per the standing rule in `test_diff_against_rae.py`. Each edge case that has
actually bitten this code has a named test: a UTF-8 BOM on the first header cell,
CRLF line endings, `QUOTE_ALL` including a header that embeds a doubled quote, a
URL absent from `internal_all.csv`, a `Non-Indexable` row, one URL appearing in
several issue files at once, and an `Address` cell containing
`=HYPERLINK("http://evil.example","click")`.

Assertions are on exact header tuples and exact URL lists. Counts are hand-derived
from the fixture, not computed by the same code under test.

---

## 3. Design decisions

### 3.1 Search Console and Analytics are optional and say so

`search_console_all.csv` and `analytics_all.csv` are genuine Screaming Frog
filenames from the `Search Console:All` / `Analytics:All` tabs, but
`export_manifest.py` does not request those tabs and `ALLOWED_BUNDLE_FILENAMES`
does not admit those files, so they can never arrive through the supported path.

They are now explicitly optional and render as `NOT_MEASURED`, which keeps the
two cases [ADR 0011](../adr/0011-deliverables-boundary-and-screaming-frog-input.md) §5
requires distinct: **map absent** → "not measured by this crawl"; **map present
but this URL not in it** → a measured `0`. A column of zeroes that actually means
"nobody looked" reads as "this page gets no traffic", which is a worse answer
than no answer.

Neither file was added to any manifest.
`test_the_enrichment_files_are_deliberately_outside_the_allow_list` pins that
they stay outside `ALLOWED_BUNDLE_FILENAMES`, so adding either becomes a visible
decision rather than a drift.

### 3.2 Filenames with no real counterpart were dropped, not mapped

RAE's own fallback aliases were checked against all 49 export folders on disk and
found in **zero** of them:

```
hreflang_no_index_return_links.csv          0/49
client_error_(4xx)_inlinks.csv              0/49
redirect_chains.csv                         0/49
success_(2xx)_inlinks.csv                   0/49
sitemaps_urls_in_multiple_sitemaps.csv      0/49
pagination_non200_pagination_urls.csv       0/49
content_readability_*.csv                   0/49
```

(Counts re-run by the scribe with `find RAE/rankuno-reports -maxdepth 3 -name …`.)
They were not adopted. Mapping a name to a plausible-looking neighbour is how the
original 37 invented names became invisible; a dropped name with a docstring
saying it was dropped is auditable, a silently remapped one is not.

Where a category was genuinely richer than the invented list, RAE's fuller set
*was* taken: `security` 3 → 12, `hreflang` 3 → 13,
`non_functional_internal_links` 1 → 9, `overview_report` 36 → 95.

### 3.3 `INDEXABLE_ONLY` is a declaration with no default answer

The alternative was a helper that each service calls or does not call. That is
what the code already had, in effect, and it failed silently: a service that
forgot produced a valid, empty, green workbook. Making it a `ClassVar` with a
default of `True` means the question is answered for every service, the answer is
greppable, and a test can assert the whole set at once. Recorded as
[ADR 0020](../adr/0020-a-deliverable-declares-whether-it-reports-on-indexable-pages.md)
because every future service has to answer it and the cost of answering wrong is
a workbook that looks fine and contains nothing.

### 3.4 `custom_extraction`'s filename was settled empirically, and the service is still unreachable

The file is `custom_extraction_all.csv`, present in **45 of 45** populated export
folders (4 of the 49 folders hold no CSVs at all — scribe-verified). But it is
not in `ALLOWED_BUNDLE_FILENAMES` and `Custom Extraction:All` is not in
`EXPORT_TABS`, so **the service cannot be reached through the supported bundle
path** and works only against a loose export directory. That is stated in the
module docstring rather than fixed by widening the allow-list, because widening it
is an ADR 0018 decision and not this cycle's (§6.3).

`custom_extraction` is also the one service exempt from the "no `.csv` literal"
rule (§4.7): Screaming Frog writes one `custom_extraction_*.csv` per configured
extractor, so its filenames are knowable only from the bundle. The exemption is
declared in `DYNAMIC_SOURCES` in the test, not implicit.

---

## 4. Bugs found and fixed

### 4.1 The `nan` URL defect

Twelve of the ninety-six allow-listed exports have **no `Address` column at all**.
They are edge lists with header `Type,Source,Destination,…`. Concatenating them
with page exports and then reading `Address` yields `nan` for every edge row, so
the workbook would have printed the literal string `"nan"` where a URL belongs.

The URL column is now resolved **per file, before concat**. The full set,
enumerated from the committed `url_column_for()`:

| Resolved column | Files |
| :--- | :--- |
| `Destination` — the page the issue is *about* | `canonicalised_inlinks.csv`, `http_urls_inlinks.csv`, `internal_blocked_by_robots_txt_inlinks.csv`, `internal_blocked_resource_inlinks.csv`, `internal_client_error_(4xx)_inlinks.csv`, `internal_no_response_inlinks.csv`, `internal_redirection_(3xx)_inlinks.csv`, `internal_server_error_(5xx)_inlinks.csv`, `nonindexable_canonical_inlinks.csv` |
| `Source` — the page carrying the offending markup | `form_url_insecure.csv`, `protocolrelative_outlinks.csv`, `unsafe_crossorigin_links.csv` |

`test_every_allow_listed_file_has_a_known_url_column` asserts `url_column_for()`
returns one of the three for **every** allow-listed name, so a new export file
cannot arrive without an answer.

### 4.2 A latent crash in the logger, in the debug path

```python
_logger.debug("masterfile_csv_absent", extra={"filename": filename})
```

`filename` is a reserved `LogRecord` attribute. `logging.makeRecord` raises
`KeyError: "Attempt to overwrite 'filename' in LogRecord"`. This sat at DEBUG
level in `masterfile_source.py` at two call sites, which means **turning on debug
logging to investigate a masterfile problem would have crashed the CSV reader** —
the failure mode was hidden precisely in the act of looking for it.

Worth knowing even without the raise: `JsonFormatter._RESERVED_ATTRS` excludes
`filename`, so the value would have been silently dropped anyway. This is the
second `extra=` defect in this codebase; the first was
[build-log 0078](0078-the-fields-that-never-left-the-call-site.md), where
`get_logger` dropped every caller field. The key is now `export`.

### 4.3 `masterfile_overview_report.py` crashed on any real bundle

`wb.create_sheet("Notes/Recommendations")` → `ValueError: Invalid character /
found in sheet title`. Unconditional: it fired for every input that got that far.

### 4.4 `masterfile_custom_extraction.py` passed a client-supplied name to `create_sheet` unfiltered

Four `create_sheet` call sites, three of which passed the extractor name — which
comes from the *filename in the uploaded bundle*, that is, from the client —
straight through with no sanitisation. Same class of defect as §4.3 with a worse
origin.

Both now route through `sanitize_sheet_name`, which **already existed in
`masterfile_base.py` and had exactly one reference in the whole tree: its own
definition.** A helper written for a rule that nothing enforced. The
`custom_extraction` fix additionally dedupes against `wb.sheetnames`, because
truncation to Excel's 31-character limit can make two distinct extractor names
collide.

### 4.5 A comment that described the opposite of the line beneath it

In `masterfile_response_codes.py`, verbatim from `81db178`:

```python
# Only include indexable=True, status=200, content_type=HTML URLs
# (but we're showing status codes, so include all status codes here)
# Filter: indexable=True, content_type=HTML
indexability = internal_data.get("indexability")
if indexability != "Indexable":
```

The comment states the exception. The next two lines implement its negation. The
service returned 0 rows against a 24,000-page export for exactly this reason.

### 4.6 The indexability filter could not match a row, by construction

The cause the brief did not anticipate, and the one that mattered most. Every
service dropped rows whose `internal_all.csv` `Indexability != "Indexable"`. For
three services that rule cannot match **any** row by definition — a `noindex`
page, a 4xx page, and an inlink to a broken page are all Non-Indexable *because
that is what the report is about*.

On the 24,000-page export the filter alone cost:

```
directives         10,309 -> 0
response_codes      7,756 -> 0
internal_links     51,965 -> 838
```

**Correct filenames alone would have left all three blank**, and the cycle would
have shipped looking like a success with three of its biggest services still
empty. Fixed as §2.4.

### 4.7 The test problem, which is the load-bearing part of this cycle

19 of 21 service test files asserted:

```python
assert isinstance(result, bytes)
assert len(result) > 0
```

against an **empty temporary directory**. An empty openpyxl workbook is several
thousand bytes, so both assertions hold perfectly for a workbook containing
nothing. That is why every defect above shipped green and stayed green through
two cycles that declared completion.

`len(result) > 0` now appears as an assertion **nowhere in `tests/`**.
Scribe-verified:

```
$ grep -rn "len(result) > 0" tests/
tests/modules/seo/deliverables/sf_export.py:4:*empty* temporary directory and assert `len(result) > 0`. An empty workbook is
tests/modules/seo/deliverables/test_masterfile_against_export.py:5:openpyxl workbook is several thousand bytes, so `len(result) > 0` held for
```

Two docstrings explaining why it was wrong, and no assertion.

The replacement makes the original drift unrepresentable rather than merely
tested-for. `tests/modules/seo/deliverables/test_masterfile_sources.py` asserts
that the union of every service's `SOURCE_FILES` **equals**
`ALLOWED_BUNDLE_FILENAMES` minus the spine — not a subset in either direction —
and that no service module, except the declared-dynamic `custom_extraction`,
contains a quoted `.csv` literal at all.

---

## 5. Corrections

### 5.1 Build-log 0104 specified the Response Codes exception and it was never implemented

[Build-log 0104](0104-masterfile-framework-and-phase-1-foundation.md), line 223,
verbatim:

> 5. **Status 200 + Indexable filter** (except Response Codes service shows all
>    status codes in affected URLs)

The specification was correct, it was published, and the code contradicted it
from the moment the service was written and kept contradicting it across 0105,
0107 and every cycle in between. The exception is now implemented as
`INDEXABLE_ONLY = False`. **This is a spec that was right and code that was
wrong, and nothing in the repository could tell the difference** — which is the
whole argument for §4.7's replacement tests.

### 5.2 The invented filenames were not RAE's vocabulary — that claim was wrong

Earlier in this session it was stated that the 37 invented CSV filenames came
from RAE using different names. **That is false.** RAE and
`src/modules/seo/contracts/catalogue.py` already agreed on the correct names.
The invented names were generated from the services' own module names —
`masterfile_page_titles.py` → `title_missing.csv`, `title_too_long.csv`,
`title_too_short.csv`, `title_duplicate.csv`, none of which any export has ever
contained. Fixing this was **porting constants that already existed in two
places, not designing new ones**.

The distinction matters for how much to trust the rest of the port: if the names
had been a genuine vocabulary mismatch, every other constant would be suspect. It
was a service inventing its own inputs, which is a narrower and more specific
failure.

### 5.3 `0d26e26`'s "Complete RAE masterfile parity" was false, and it is still not complete

Recorded first in [0107 §5](0107-a-directory-that-could-never-exist.md). Against a
real export, 4 of 21 produced rows. This cycle takes it to 12 of 21. Stating that
plainly rather than implying completion: **9 services still produce no rows**, and
§2.1 says which kind of nothing each one is. No entry should describe this
subsystem as done until that table is empty.

### 5.4 The reported net source-line change does not match the commit

The implementer's report gives a net source change of **−141 lines**. The commit
does not show that. Re-derived by the scribe with `git show --numstat`:

| Scope | Insertions | Deletions | Net |
| :--- | ---: | ---: | ---: |
| `src/` (25 files) | 747 | 601 | **+146** |
| `src/` excluding the two new modules | 442 | 601 | **−159** |
| `tests/` (26 files) | 1,311 | 125 | **+1,186** |

−141 is neither. The −159 figure is the closest reading — existing service
modules genuinely shrank, by 159 lines, once they stopped hand-keeping filename
lists — and the two new modules (`sources.py` 68, `masterfile_enrichment.py` 237)
add 305 back. The **+146** overall is the number to cite. Nothing about the
change's correctness depends on it; it is recorded because a published number
that is wrong is worse than one never published.

### 5.5 "No service module contains a `.csv` string literal at all" is overstated

`masterfile_custom_extraction.py` contains five, and does so legitimately:
`_CUSTOM_EXTRACTION_PREFIX`, the `.csv` suffix it strips, and docstring
references. The test exempts it explicitly through `DYNAMIC_SOURCES`, for the
reason in §3.4. The accurate claim is: **no service module except
`custom_extraction` contains a quoted `.csv` literal, and that exemption is
declared in the test rather than assumed.**

### 5.6 The README and ARCHITECTURE figures they carried are now stale

Both described "13 of 21 empty", "37 of 49 invented filenames" and
"`overview_report` crashes at `masterfile_overview_report.py:235`". All three
were true when written ([0107](0107-a-directory-that-could-never-exist.md)) and
are false now. Updated in this change to the measured 12-of-21 reality, not to
"complete".

---

## 6. Explicitly not done

### 6.1 The output shape — the largest gap

Services still emit a **flat URL list with no column naming which issue applied**,
and nothing deduplicates across source files. A URL present in both
`page_titles_missing.csv` and `page_titles_duplicate.csv` yields **two identical
rows** with nothing to distinguish them. RAE's equivalent is 18 columns with
per-issue flags.

`test_one_url_in_several_issue_files_yields_one_row_per_file` pins the *current*
behaviour deliberately, so the reshape cycle starts from an assertion that
already exists and fails loudly when the shape changes.

This is now unblocked for the first time: reshaping a workbook that contains no
data is not a reviewable exercise.

### 6.2 `pagination` still renders 0 rows where its input has data

`pagination_nonindexable.csv` is present in 45 of 45 populated exports
(scribe-verified) and has 15 rows on another export. `PAGINATION_NON_INDEXABLE`
is non-indexable by definition, so the §2.4 fix would apply — but the category's
other five issues concern indexable pages, so flipping `INDEXABLE_ONLY` for the
whole service would over-include rows in those five.

The correct fix is **per-issue**, not per-service, and per-issue filtering
requires the §6.1 reshape to have somewhere to record which issue a row came
from. Handed off rather than resolved by flipping a flag that would look right
and be wrong.

### 6.3 Four services are unreachable until the export manifest grows

| Service(s) | Needs export tab | → file | Present in real exports |
| :--- | :--- | :--- | :--- |
| `custom_extraction`, `custom_search_ga4_gtm`, `custom_search_og_twitter` | `Custom Extraction:All` | `custom_extraction_all.csv` | **45 of 45** |
| `functional_internal_links` | `Response Codes:Internal:Internal Success (2xx) Inlinks` | `internal_success_(2xx)_inlinks.csv` | **45 of 45** |

Both presence figures re-verified by the scribe against `RAE/rankuno-reports/`.
Closing this needs catalogue rows **plus** an ADR 0018 allow-list decision, which
is a security-boundary change and not a masterfile change.
`ALLOWED_BUNDLE_FILENAMES` was not widened and `export_manifest.py` was not
touched this cycle — the ADR 0018 boundary is intact.

### 6.4 `read_csv_safe` omits `low_memory=False`

RAE sets it. Real exports emit, reproducibly during the scribe's verification run:

```
DtypeWarning: Columns (0: Meta Keywords 1, 1: H1-2) have mixed types.
Specify dtype option on import or set low_memory=False.
```

The practical consequence is that a numeric column such as `Inlinks` can parse as
a string on a large file and as an integer on a small one, which is a difference
no fixture-sized test will ever show.

### 6.5 `_STATUS_GROUPS` in `masterfile_response_codes.py` is dead

Defined at line 35, never read. Left in place rather than deleted mid-cycle; it is
a one-line removal for whoever does §6.1.

---

## 7. Files changed

51 files, 2,058 insertions, 726 deletions, all under `src/modules/seo/` and
`tests/modules/seo/deliverables/`.

**New (2 source, 5 test):**

| File | Lines | Purpose |
| :--- | ---: | :--- |
| `src/modules/seo/contracts/sources.py` | 68 | Catalogue-derived source filenames (§2.2) |
| `src/modules/seo/deliverables/masterfile_enrichment.py` | 237 | URL-column resolution, enrichment maps, `NOT_MEASURED` (§2.3) |
| `tests/modules/seo/deliverables/sf_export.py` | 365 | Shared synthetic export fixture (§2.5) |
| `tests/modules/seo/deliverables/conftest.py` | 99 | Fixture wiring |
| `tests/modules/seo/deliverables/test_masterfile_against_export.py` | 281 | Edge cases, exact headers, exact URL lists |
| `tests/modules/seo/deliverables/test_masterfile_sources.py` | 134 | The drift tests (§4.7) |
| `tests/modules/seo/deliverables/test_masterfile_enrichment.py` | 159 | `url_column_for`, maps, `NOT_MEASURED` |

**Modified:** `masterfile_base.py` (220 changed lines, now 350 — under the
400-line target), `masterfile_source.py` (the §4.2 logger fix), and all 21
service modules. 19 service test files lost the `len(result) > 0` assertion.

Every file this cycle touched is under 400 lines. `rulebook.py` at 465 lines is
over the target, pre-existing, and untouched here.

---

## 8. Follow-ups

1. Reshape the output to RAE's per-issue column form (§6.1). Blocks §6.2.
2. Per-issue `INDEXABLE_ONLY` for `pagination` (§6.2), after 1.
3. ADR 0018 decision on `Custom Extraction:All` and
   `Response Codes:Internal:Internal Success (2xx) Inlinks` (§6.3).
4. `low_memory=False` in `read_csv_safe` (§6.4).
5. Delete `_STATUS_GROUPS` (§6.5).
6. Re-measure all 21 against a second and third real export. One site cannot
   distinguish "this service is broken" from "this site has no instances of this
   issue", and §2.1's middle row currently rests on that distinction.

---

## 9. The working tree changed under the implementing agent, twice

Recorded as fact, with no speculation about cause.

During this cycle the working tree was modified twice by something other than the
implementing agent:

1. Five commits appeared and `origin/main` advanced.
2. The tree was **switched off `main`** onto branch
   `fix/ui-reload-restores-view-and-crawl`.

The implementing agent issued no git write command of any kind. `git reflog`
attributes the checkout to another actor:

```
44e50fc HEAD@{3}: checkout: moving from main to fix/ui-reload-restores-view-and-crawl
```

Cycle numbers were consumed underneath the work twice, forcing renumbering
**0114 → 0115 → 0116**.

**This is the third such event.**
[Build-log 0112](0112-a-wizard-wired-to-the-wrong-crawler.md) records an
unattended push.

Why it matters, concretely: a gate result certifies a tree. If the tree changes
between the gate and the commit, the gate certified something that was not
committed, and no agent inside that tree can tell. It also silently consumes
cycle numbers, and a cycle number that is consumed after an agent has written it
into source is not free to change — 57 lines across `src/` and `tests/` cite
"build-log 0116" in docstrings, all written before this entry existed.

**Verified and worth stating**: the concurrent commits touched **zero** files
under `deliverables/`, `contracts/` or `screaming_frog_control/`, so this change
is not entangled with them. `0239a50` itself is a cherry-pick
(`git reflog`: `commit (cherry-pick)`), which is how the work was preserved
across the branch move.
