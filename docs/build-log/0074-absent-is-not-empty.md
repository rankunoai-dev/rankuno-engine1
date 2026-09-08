# Cycle 0074: Absent is not empty — a Screaming Frog export becomes an `AuditDataset`

- **Date**: 2026-09-08
- **Scope**: Phase 0 work items P0-3 (Screaming Frog adapter) and P0-5 (synthetic
  Screaming Frog fixture bundle) of `docs/DELIVERABLES_IMPLEMENTATION_PLAN.md`,
  under ADR 0011 (APPROVED). A new package `src/modules/seo/deliverables/`, a
  `UrlNormalizer` seam in `contracts/`, and two contract changes the previous
  cycle handed over (§2.4).
- **Commit**: uncommitted at time of writing (HEAD `e71e506`)
- **Quality gate**: `1964 passed, 1 skipped, 1 warning`, coverage 93.86%; UI
  `232 passed` / 21 files. `ALL GATES PASSED.` (§1.1)

**Cycle number.** The index and the directory both ended at 0073 when this entry
was written, so this cycle took 0074. Plan P1-5 still says "build-log 0073" for
a later cycle; that number is now this plan's previous cycle and P1-5's entry
will take whatever is free when it lands (0073 §5.5 said the same).

**This cycle was interrupted and resumed.** The first feature-builder session
wrote the contract changes, the `UrlNormalizer` protocol, the fixture bundle,
the adapter, and the `_bundle.py` split, then the process died before any test
was written or run. A second feature-builder session re-verified every binding
condition of the brief against the code it found (all met; it changed nothing
under `src/`), wrote the 106 tests, and ran the gate. The design decisions in §3
are therefore reconstructed from the code and its docstrings by the second
session and by docs-scribe, not from the first session's reasoning, which was
lost with the process. Where a docstring states a reason it is quoted; where it
does not, §3 says so.

---

## 1. Gate results

### 1.1 Final gate run, as reported by the second feature-builder (`scripts/verify.ps1`, no `-Fix`)

```
=== Format ===
282 files already formatted
PASSED: Format

=== Lint ===
All checks passed!
PASSED: Lint

=== Type check ===
PASSED: Type check

=== Tests ===
TOTAL    7667    379   1920    138    94%
Required test coverage of 85.0% reached. Total coverage: 93.86%
1964 passed, 1 skipped, 1 warning in 177.78s (0:02:57)
PASSED: Tests

=== UI Component Tests ===
 Test Files  21 passed (21)
      Tests  232 passed (232)
PASSED: UI Component Tests

ALL GATES PASSED.
```

The hand-off supplied the stage lines above and the `TOTAL` row; the per-file
coverage rows were not supplied and are not reproduced. Docs-scribe did not
re-run the full gate; it re-ran the targeted tests (§1.2) and `drift_check.py`
(§1.3).

Two earlier runs of the same gate in this cycle were red. The Format and Lint
failures were in `tests/integrations/test_gsc_token_manager.py`,
`tests/integrations/test_gsc_client.py` and `tests/core/test_config.py`; the UI
failure was in `rankuno-ui/src/components/layout/LiveCrawlModal.test.tsx`. All
four belong to the other session's uncommitted set (git status at the start of
this cycle) and were fixed by that session while this cycle was running. No file
of this cycle was involved and no action was taken here. As in 0073 §1.4, the
green result depends on that session's uncommitted edits being committed with
it.

The one skip is `test_symlinked_file_in_directory_is_refused`: `os.symlink`
raises `WinError 1314` because this account lacks
`SeCreateSymbolicLinkPrivilege`. The one warning is Starlette's httpx
deprecation notice from `fastapi/testclient.py`, present since cycle 0012.

### 1.2 This cycle's tests alone (docs-scribe run, 2026-09-08)

```
pytest tests/modules/seo/test_screaming_frog_adapter.py
       tests/modules/seo/test_screaming_frog_adapter_errors.py
       tests/modules/seo/test_screaming_frog_bundle.py
       tests/modules/seo/test_audit_contract.py -o addopts="" -q
106 passed, 1 skipped in 0.83s

SKIPPED [1] tests\modules\seo\test_screaming_frog_bundle.py:316:
  symlink creation needs a privilege this account lacks: 22

--cov=src/modules/seo/deliverables --cov=src/modules/seo/contracts
Name                                                     Stmts   Miss Branch BrPart  Cover   Missing
src\modules\seo\deliverables\_bundle.py                    154      7     42      1    96%   100, 194-195, 213-214, 237-238
src\modules\seo\deliverables\screaming_frog_adapter.py     171      3     50      4    97%   204-205, 254->252, 257, 292->294
TOTAL                                                      595     10    112      5    98%
6 files skipped due to complete coverage.
```

Collected per file (pytest counts parametrised cases; the hand-off's "30 / 19 /
27" counted differently and does not sum to 106):

| File | Collected | `def test_` functions |
| :--- | ---: | ---: |
| `test_screaming_frog_adapter.py` | 27 | 26 |
| `test_screaming_frog_adapter_errors.py` | 19 | 16 |
| `test_screaming_frog_bundle.py` | 38 | 25 |
| `test_audit_contract.py` (20 from 0073 + 3 new) | 23 | 23 |

The uncovered lines are the symlink refusal path in `_bundle.py` (never
executed on this workstation, §6) and defensive branches in the adapter's spine
hostname loop.

### 1.3 Drift check

```
Running Architecture & Documentation Drift Audit...

--- Drift Audit Results ---
PASSED: no drift detected across 140 markdown files.
  - all relative links resolve
  - all domain modules documented
  - all skill directories populated
```

(Run after this entry and the index row existed; identical to the pre-edit
baseline. The count does not move because `drift_check.py` enumerates with
`git ls-files "*.md"`, which returns the 140 *tracked* markdown files; this
entry, 0072, 0073, ADR 0011 and the plan are untracked and are therefore not
scanned for broken links at all until they are added to the index. The links
*to* this entry from `README.md`, `docs/ARCHITECTURE.md` and the build-log
index are in tracked files and were resolved. This entry contains no relative
markdown links of its own.)

---

## 2. What landed

### 2.1 `src/modules/seo/deliverables/screaming_frog_adapter.py` (351 lines)

`load_screaming_frog_bundle(path, *, normalize, produced_at=None) -> AuditDataset`
with `source=AuditSource.SCREAMING_FROG`. The module docstring states the three
stances that distinguish it from the RAE reader it replaces, and they are the
whole point of P0-3:

- **Absent is not empty.** A catalogue file that is not in the bundle gives that
  issue `Coverage.NOT_MEASURED`. A file that is present with only a header row
  gives `MEASURED` with an empty set. Both are values a workbook must show.
- **Nothing is skipped by size.** RAE dropped files under 100 bytes and lost
  real one-row findings (a `form_url_insecure.csv` with one row is 87 bytes).
- **Nothing fails silently.** Every read, parse, encoding, or guard failure is
  one typed `ScreamingFrogBundleError(ValueError)` carrying a filename and a rule
  string; there is no path to "no issues".

The spine is `internal_all.csv` (`SPINE_FILE`); every `Address` in it becomes an
`AuditPage` keyed by the injected normaliser. Each of the 110 catalogue rows is
then read by its `sf_sources` filenames. The URL column is chosen by header:
`Address` if present, else `Source`, so for edge-list files (`*_inlinks.csv`,
`form_url_insecure.csv`, `unsafe_crossorigin_links.csv`) the `Destination`
column is structurally unreachable, not merely ignored — plan §7's "Source only"
rule holds by construction.

`site` is the majority hostname of the normalised spine with `www.` and any
port stripped; if the spine holds more than one hostname a note
`"site: N hostnames in spine; majority chosen"` is added. The hostname strip is
documented in the code as what binds this adapter, the engine adapter (P0-4)
and the rulebook lookup to one spelling.

Every URL cell passes through `SfUrlCell(StrictModel)`: absolute `http(s)`
with a host, no whitespace or control character, at most `MAX_URL_LENGTH`
(2048, reused from `contracts.audit`). The scheme check is what makes deferring
formula escaping to Phase 2 safe for URL fields — a cell starting with `=` or
`@` cannot pass. Control characters are checked explicitly because Python's
`csv` does not raise on NUL.

Reading is a streaming `csv.reader` over a `TextIOWrapper` with `utf-8-sig`
(strict, not `errors="replace"`), not pandas, behind a line-length generator
(`MAX_LINE_CHARS`), a column cap (`MAX_COLUMNS`) and a row cap
(`MAX_ROWS_PER_FILE`). The injected normaliser is self-tested on entry with
`NORMALIZER_PROBE`: the result must be an absolute `http(s)` URL and the function
must be idempotent on it, else `NormalizerContractError`
(a `ScreamingFrogBundleError` subclass). Logs carry counts and catalogue
filenames only, never a URL or cell value — but see §4.3 for what actually
reaches the log output.

`links` is always `()`, and the dataset carries `LINKS_NOT_RETAINED_NOTE`
(`"links: edges not retained by the screaming_frog adapter (ADR 0011 D4 deferred)"`).
See §3.2 and §5.

Constants as shipped:

| Name | Value | Where |
| :--- | :--- | :--- |
| `SPINE_FILE` | `"internal_all.csv"` | adapter |
| `MAX_ROWS_PER_FILE` | 20,000,000 | adapter |
| `MAX_LINE_CHARS` | 1,048,576 | adapter |
| `MAX_COLUMNS` | 1,024 | adapter |
| `NORMALIZER_PROBE` | `"HTTP://WWW.Example.com/A/../b/?utm_source=x&z=1"` | adapter |
| URL cell cap | `contracts.audit.MAX_URL_LENGTH` = 2048 | reused |
| `MAX_ZIP_MEMBERS` | 1,000 | `_bundle.py` |
| `MAX_MEMBER_UNCOMPRESSED_BYTES` | 2 GiB (`2 * 1024**3`) | `_bundle.py` |
| `MAX_BUNDLE_UNCOMPRESSED_BYTES` | 8 GiB (`8 * 1024**3`) | `_bundle.py` |

### 2.2 `src/modules/seo/deliverables/_bundle.py` (252 lines)

`open_bundle(path) -> Bundle`, where `Bundle` is a protocol with
`open_text(name) -> IO[str] | None` (`None` means absent) and `close()`. Two
implementations: a directory and a zip. The adapter never globs; it asks for
catalogue names. Refused before a byte is parsed, each with its own rule string:
member-name traversal, absolute names, forbidden characters, empty names;
symlink members (by external attributes) and symlinked or non-regular files in a
directory bundle (`unsafe-path`); duplicate basenames across sub-directories;
more than `MAX_ZIP_MEMBERS`; nested archives; encrypted or non-deflate/stored
members; and size. A member's declared `file_size` is a fast refusal only — the
guard is a counting wrapper around the decompressing stream, because a zip
header can lie. Members are streamed, never read whole, never extracted to disk.

### 2.3 `src/modules/seo/contracts/url_normalizer.py` (30 lines)

`UrlNormalizer` is a `Protocol` with `__call__(self, url: str, /) -> str`.
Positional-only so any `(str) -> str` qualifies whatever it names its argument.
It lives in `contracts/` because both adapters must be keyed by the same
function and neither may import the other or `page_classifier` (ADR 0011 d.1);
in production both are handed `page_classifier.url_rules.normalize_url`, whose
extra parameters are keyword-only with defaults, so it satisfies the protocol
without a wrapper.

### 2.4 Contract changes (`contracts/audit.py`, `contracts/__init__.py`)

Both were 0073 §8.2 follow-ups, taken here because the adapter depends on them:

- `AuditSource` is now a `StrEnum` (`ENGINE = "engine"`,
  `SCREAMING_FROG = "screaming_frog"`) rather than a `Literal`, so an adapter
  names itself by member. JSON round-trip is unchanged (test
  `test_source_is_a_str_enum`).
- **Invariant 4**: `pages[].url` must be unique. The validator docstring gives
  the reason: a page counted twice would inflate every denominator in Phase 2.
  Failing-then-passing tests `test_invariant_4_*`.

`contracts/__init__.py` re-exports `UrlNormalizer` and `MAX_URL_LENGTH`.

### 2.5 Fixture and tests

- `tests/fixtures/deliverables/sf_bundle/` — 17 files, a synthetic
  `example.com` export: `internal_all.csv` plus 16 catalogue files chosen to
  cover header-only, one-row, edge-list (`Source`/`Destination`), and D3
  security shapes. Written with a BOM and CRLF and the real Screaming Frog 19.4
  header rows so `utf-8-sig` and the header-based column choice are exercised
  by a file, not a string literal. No real client data.
- `test_screaming_frog_adapter.py` — the fixture end to end (directory and zip
  of the same files agree), coverage semantics, `Source`-only, site derivation
  (`www.`, port, mixed case, majority host), normaliser injection and contract
  errors, and an `ast` test that neither adapter module imports anything named
  `page_classifier`. Every hostile input carries `?token=SENTINEL` so a leak of
  a cell value into an exception or log is a string match.
- `test_screaming_frog_adapter_errors.py` — missing spine, wrong header, bad
  UTF-8, NUL, over-long line, too many columns, over-long URL, non-URL cells
  (`=1+1`, `ftp://`, scheme-relative, empty host), a normaliser that raises, one
  that is not idempotent, one that returns a non-URL; and that every message is
  clean.
- `test_screaming_frog_bundle.py` — every `_bundle.py` refusal through a real
  archive or directory, except two shapes tested against the guard directly
  (§4.2).
- The adapter's "counts only" logging contract is verified through a recording
  stub logger, not real output (§4.3).

---

## 3. Design decisions

### 3.1 Streaming `csv.reader` behind a counting decompressor, not pandas

The Step 5 audit for P0-3 set memory, not speed, as the constraint: an export
of a large site is hundreds of megabytes across files, and a zip member's
declared size is attacker-controlled. Reading rows one at a time bounds memory
by one row (with the caveat in §6), and counting bytes as they are decompressed
is the only place the size ceiling is actually enforced. pandas would have
loaded each file whole and offered no hook between decompression and parsing.

### 3.2 `links` is never filled

The plan's D4 text said the SF adapter would fill `links` from `*_inlinks.csv`.
The security-auditor's finding 3 on the P0-3 brief ruled it out: one
`AuditLink` per edge on RAE's 732 MB infosys edge list is millions of ~1 KB
Pydantic objects, which contradicts §3.1 and CLAUDE.md §8's memory stance. The
adapter leaves `links=()` and stamps `LINKS_NOT_RETAINED_NOTE`, so a Phase 2
reader can tell "not retained" from "site has no internal links". This is
binding for this cycle; §5 records the corrections it forces.

### 3.3 URL column chosen by header, so `Destination` cannot be read

Rather than a per-file rule listing which files are edge lists, the reader
looks for `Address` and, failing that, `Source`. Any file with both takes
`Address`; a file with `Source` and `Destination` takes `Source`. No code path
reads a column named `Destination`. This is stronger than the plan's §7 wording
("we take `Source` only") because it does not depend on a filename list being
right, which 0073 §4.3–4.4 showed filename lists are not.

### 3.4 Typed error with a rule string, and message hygiene

`ScreamingFrogBundleError(filename, rule)` makes every refusal assertable by
rule rather than by message text, and keeps messages to catalogue filenames,
rules and counts. The tests treat `"http://"`, `"https://"`, `"SENTINEL"` and
the fixture host as leak markers (§4.1 for why not the bare word `http`).

### 3.5 Normaliser self-test on entry

An adapter that trusted its normaliser would produce a dataset whose keys
silently disagree with the engine adapter's. The probe checks the two properties
the contract needs — an absolute `http(s)` result and idempotence — once, before
any file is opened, and the failure is its own subclass so a caller can tell
"your normaliser is wrong" from "your bundle is wrong".

### 3.6 Why `_bundle.py` is a separate module

The first session split it out; the docstring gives the reason: everything
hostile a bundle can do is refused in one place, with one error type, before
the adapter parses a byte. It also keeps the adapter under the 400-line target
(351 lines) with the guards at 252. Whether the first session had further
reasons is not recoverable (interruption note above).

---

## 4. Bugs found and fixed

### 4.1 Test defect: the "no `http` in the message" assertion was unsatisfiable

The first draft of the leak check asserted that `str(exc)` did not contain the
substring `http`. Two catalogue filenames — `security_http_urls.csv` and
`http_urls_inlinks.csv` — contain it, and catalogue filenames are exactly what
error messages are permitted to carry. The test was wrong; the code was right.
The markers are now `"http://"`, `"https://"`, `"SENTINEL"` and `"example.com"`
(`LEAK_MARKERS` in `test_screaming_frog_adapter.py`), with a docstring recording
why.

### 4.2 Test approach: two member-name shapes cannot reach the guard through a real archive

Backslash and NUL in a zip member name are tested by calling
`_bundle._check_member_name` directly, because `zipfile.ZipInfo.__init__`
rewrites both when the central directory is read — backslash to `/` on
Windows, and truncation at the first NUL — before any guard runs. A test that
built a real archive with those names passed on Windows for the wrong reason
and would not prove the guard on Linux. Every other hostile shape (traversal,
absolute, control characters, empty, nested archive, duplicate basename,
symlink attribute, size lie) is tested through a real archive.

### 4.3 Platform bug found, **not fixed**: `get_logger` drops every `extra=` field on Python 3.11

`src/core/logger.py:167` returns `logging.LoggerAdapter(logger, {})`. On
Python 3.11 (this workstation runs 3.11.9) the default `LoggerAdapter.process()`
sets `kwargs["extra"] = self.extra`, **replacing** the caller's dict with the
adapter's empty one; the `merge_extra` option that changes this arrived in
3.13. Docs-scribe confirmed it independently:

```
log = get_logger("probe"); log.info("probe", extra={"rows": 5})
-> {"ts": "2026-09-08T10:42:48.294575+00:00", "level": "INFO",
    "logger": "rankuno.probe", "message": "probe"}
```

No `rows` field. This is not specific to this adapter: every `extra=` payload
anywhere under `src/` — the guardrail audit trail, crawl telemetry counts, and
every count this adapter logs — is discarded before a `LogRecord` exists. The
adapter's logging contract is therefore verified through a recording stub
(which sees the call's `extra`), not through real output. Handed to `core`
(§8.4). The brief's acceptance criterion "log records carry counts" is met at
the call site and cannot be met at the output until this is fixed.

---

## 5. Corrections

1. **Plan §1, row D4** said "The Screaming Frog adapter fills them from
   `*_inlinks.csv`". It does not and will not in Phase 0 (§3.2). The row has
   been reworded in this cycle to say the adapter leaves `links=()` and stamps
   `LINKS_NOT_RETAINED_NOTE`, citing this entry.
2. **ADR 0011, Consequences**, "The SF adapter can fill `links`; the engine
   adapter declares Internal Links `NOT_MEASURED`". The first clause is
   superseded by §3.2: neither adapter fills `links` in Phase 0. The ADR's
   decision text is unchanged and the ADR file is not edited; this entry is the
   record. If a later cycle measures the cost and retains edges, that cycle
   should say so in its own entry and, if the ruling changes, in a new ADR.
3. **Build-log 0073 §2.3** described `AuditSource` as a `Literal` and listed
   "three invariants". As of this cycle `AuditSource` is a `StrEnum` and there
   are four invariants (§2.4). 0073 is not edited; it was accurate when written.
4. **The feature-builder brief's acceptance criterion** "log records carry
   counts" is unverifiable against real output (§4.3). It is met at the call
   site only.
5. **The hand-off's per-file test counts** (30 / 19 / 27) do not match pytest's
   collection (27 / 19 / 38); the total of 106 passed + 1 skipped is correct
   (§1.2 table).
6. **The hand-off's path for the GSC zip reader**,
   `src/modules/seo/page_classifier/gsc_export.py`, does not exist. The module
   is `src/modules/seo/performance/gsc_export.py` (§8.2).
7. **`README.md` status table** said "`deliverables/` does not exist". Corrected
   in this cycle. **`docs/ARCHITECTURE.md`** "Planned, not yet implemented" row
   listed P0-3 as unbuilt and the tree described `audit.py` as "three invariant
   validators"; both corrected.

---

## 6. Explicitly not done

- **`links` is not retained** (binding, §3.2). `AuditDataset.links` exists and
  stays `()` from this adapter.
- **P0-4 (engine adapter, `page_classifier/audit_export.py`), P0-6
  (`tests/modules/seo/test_import_boundary.py`), P0-7
  (`scripts/diff_against_rae.py`) and P0-8 beyond this entry** are not started.
  Only a Screaming Frog export can produce an `AuditDataset` today. The ast test
  in this cycle covers one direction only — `deliverables -> page_classifier`. It
  does not cover `contracts -> {page_classifier, deliverables}` or
  `page_classifier -> deliverables`; ADR 0011 decision 1's "a test enforces it"
  is still P0-6 and still unwritten.
- **No `members_ignored` count is logged.** The brief permitted, not required, a
  count of zip members outside the catalogue vocabulary. Not emitted.
- **The symlink refusal has never executed green on this workstation.** The
  test skips (§1.1); the code path is the uncovered `_bundle.py:100`. It will
  run on Linux CI. Until then the refusal is reviewed, not tested.
- **Only URL cells are validated.** A control character or formula-like value in
  a non-URL column is discarded with the column and never surfaced. Phase 2,
  which writes cells to a workbook, must not assume this adapter cleaned them.
- **Peak memory for one pathological line is bounded by the file cap, not
  `MAX_LINE_CHARS`.** The line-length generator bounds what reaches `csv`, but
  `TextIOWrapper` buffers a whole line before the generator sees it, so a single
  line with no newline for 2 GiB is held in memory up to
  `MAX_MEMBER_UNCOMPRESSED_BYTES` before refusal. Noted, not fixed; a fix needs a
  chunked reader below the text layer.
- **No `-Fix` on the gate**, and no change to any file of the other session's
  uncommitted set (`server.py`, `config.py`, `gsc_*` integrations and their
  tests, the reconciler and its tests, `bare_url_list.py`, `rankuno-ui/**`,
  build-logs 0058/0060/0061/0069/0072, `rae_defects_and_fixes.xlsx`). Nothing
  under `RAE - Copy/` was opened. Build-log 0073 was not edited.
- **`CLAUDE.md` §8 was not edited** by docs-scribe. The logger defect (§4.3)
  belongs in the known-gaps register so nobody reads structured log fields as
  working; adding it is a one-line change for the operator, recorded in the
  README status table and ARCHITECTURE planned table in the meantime.
- **`core/logger.py` was not fixed** (§4.3, §8.4). Out of scope for a
  `modules/seo` cycle; a `core` change needs its own gate and its own entry.

---

## 7. Files changed

Created:

```
src/modules/seo/deliverables/__init__.py                  32 lines   re-exports, boundary docstring
src/modules/seo/deliverables/screaming_frog_adapter.py   351 lines   load_screaming_frog_bundle, SfUrlCell, constants
src/modules/seo/deliverables/_bundle.py                  252 lines   open_bundle, Bundle, ScreamingFrogBundleError, guards
src/modules/seo/contracts/url_normalizer.py               30 lines   UrlNormalizer Protocol
tests/fixtures/deliverables/sf_bundle/                     17 files  synthetic example.com export, BOM + CRLF, SF 19.4 headers
tests/modules/seo/test_screaming_frog_adapter.py         401 lines   27 collected
tests/modules/seo/test_screaming_frog_adapter_errors.py  153 lines   19 collected
tests/modules/seo/test_screaming_frog_bundle.py          328 lines   38 collected, 1 skips on Windows
```

Modified (the whole `contracts/` package is still untracked since 0073;
"modified" is relative to 0073's hand-off):

```
src/modules/seo/contracts/audit.py          AuditSource -> StrEnum; invariant 4 (pages[].url unique); 188 -> 201 lines
src/modules/seo/contracts/__init__.py       exports UrlNormalizer, MAX_URL_LENGTH; 44 -> 46 lines
tests/modules/seo/test_audit_contract.py    +3 tests (invariant 4 x2, StrEnum round trip)
tests/modules/seo/test_catalogue.py:292     comment: "confirmed by the operator 2026-09-08" (closes 0073 §8.1)
```

Documentation (this cycle's Step 8):

```
docs/build-log/0074-absent-is-not-empty.md          this entry
docs/build-log/README.md                            index row
docs/DELIVERABLES_IMPLEMENTATION_PLAN.md            §1 row D4 reworded (§5.1)
README.md                                           contracts/ row updated; deliverables/ row added; core/logger.py extra= row added
docs/ARCHITECTURE.md                                url_normalizer.py and deliverables/ in the tree; planned table row for P0-4/6/7 and the logger defect
```

No ADR was added. ADR 0011 already records the seam and the Screaming Frog
input decision; the one departure from its consequence text (§5.2) narrows what
the adapter does rather than changing a ruling, and is recorded here.

---

## 8. Follow-ups

1. **`contracts/audit.py:196-199`** (contracts owner): the invariant-2 message
   embeds a raw URL (`first: {unknown[0]!r}`). Every other message in the
   contract and the adapter carries counts only; this one should too, or the
   adapter's leak tests will fail the moment an unknown URL reaches the
   validator through a note-less issue.
2. **`src/modules/seo/performance/gsc_export.py:246-272`** (performance owner):
   `_from_archive` reads each member whole with `archive.read(name)`, trusts
   `file_size` for its only size check, and has none of the member-name,
   symlink, nested-archive or count guards `_bundle.py` has. Same threat model,
   older code.
3. **P0-6** before anything imports `contracts/` from `page_classifier`; the
   direction is still a docstring promise plus one one-way ast test.
4. **`src/core/logger.py:167`** (core, **HIGH**): `LoggerAdapter(logger, {})`
   silently drops every `extra=` field on Python 3.11 (§4.3). Either subclass
   `LoggerAdapter` with a `process()` that merges, or return the plain logger,
   and add a test that reads real emitted JSON. Until then, no structured log
   field in this repository should be described as working, and `CLAUDE.md` §8
   should say so.
5. **Chunked reader below `TextIOWrapper`** if the one-line memory bound in §6
   matters for hosted deployment (not blocking for local, ADR 0004).
6. **Plan P1-5** still names "build-log 0073"; that entry number is taken.
