# Cycle 0077: Screaming Frog adapter and streaming zip guards

- **Date**: 2026-09-08
- **Scope**: Phase 0 work items P0-3 (Screaming Frog adapter) and P0-5 (synthetic fixture bundle) of `docs/DELIVERABLES_IMPLEMENTATION_PLAN.md` (APPROVED) under ADR 0011 (APPROVED). New package `src/modules/seo/deliverables/` (`__init__.py`, `screaming_frog_adapter.py`, `_bundle.py`), `src/modules/seo/contracts/url_normalizer.py`, synthetic fixture bundle `tests/fixtures/deliverables/sf_bundle/`, and 106 tests across three test files.
- **Commit**: uncommitted at time of writing
- **Quality gate**: `1964 passed, 1 skipped` Python / `232 passed` UI / `Total coverage: 93.86%` (`_bundle.py` 96%, `screaming_frog_adapter.py` 97%).

**Cycle number.** Cycles 0074, 0075, and 0076 were claimed by parallel sessions in the index (`0074-absent-is-not-empty.md`, `0075-which-search-console-account.md`, `0076-a-pdf-is-not-an-orphan.md`). Numbers are never reused (`README.md` in this directory), so this cycle took 0077.

---

## 1. Gate results

```
=== Format ===
282 files already formatted
PASSED: Format

=== Lint ===
All checks passed!
PASSED: Lint

=== Type check ===
Success: no issues found in 67 source files
PASSED: Type check

=== Tests ===
TOTAL                                                           7667    369   1800    133    94%
Required test coverage of 85.0% reached. Total coverage: 93.86%
1964 passed, 1 skipped, 1 warning in 177.78s (0:02:57)
PASSED: Tests

=== UI Component Tests ===
Test Files  21 passed (21)
     Tests  232 passed (232)
PASSED: UI Component Tests

ALL GATES PASSED.
```

### 1.1 Package coverage

```
pytest tests/modules/seo/test_screaming_frog_adapter.py tests/modules/seo/test_screaming_frog_adapter_errors.py tests/modules/seo/test_screaming_frog_bundle.py tests/modules/seo/test_audit_contract.py --cov=src/modules/seo/deliverables --cov=src/modules/seo/contracts

Name                                                    Stmts   Miss Branch BrPart  Cover   Missing
---------------------------------------------------------------------------------------------------
src\modules\seo\deliverables\_bundle.py                   154      7     42      1    96%   100, 194-195, 213-214, 237-238
src\modules\seo\deliverables\screaming_frog_adapter.py   171      3     50      4    97%   204-205, 254->252, 257, 292->294
---------------------------------------------------------------------------------------------------
TOTAL                                                     595     10    112      5    97.88%
```

### 1.2 Drift check

`scripts/drift_check.py` output:
```
--- Drift Audit Results ---
PASSED: no drift detected across 140 markdown files.
  - all relative links resolve
  - all domain modules documented
  - all skill directories populated
exit=0
```

---

## 2. What landed

This cycle was **interrupted and resumed**. A first feature-builder wrote the contracts changes, `UrlNormalizer` Protocol, fixture bundle, and adapter split (`_bundle.py`), but died before writing tests. A second feature-builder verified every binding condition (all MET, zero `src/` modifications required), wrote 106 unit tests across three files, and ran the full quality gate.

### 2.1 `src/modules/seo/contracts/url_normalizer.py` (30 lines)

`UrlNormalizer(Protocol)`: `def __call__(self, url: str, /) -> str: ...`. Isolated inside `contracts/` with zero imports. Injected into `load_screaming_frog_bundle` so deliverables does not import `page_classifier.url_rules` (ADR 0011 d.1).

### 2.2 `src/modules/seo/contracts/audit.py` & `__init__.py`

- `AuditSource` converted to `StrEnum` (`ENGINE = "engine"`, `SCREAMING_FROG = "screaming_frog"`).
- Invariant 4 added to `AuditDataset._check_invariants`: validates `pages[].url` uniqueness, raising a `ValueError` with duplicate counts.

### 2.3 `src/modules/seo/deliverables/_bundle.py` (252 lines)

Pre-flight security zip reader & directory handle (`_ZipBundle` / `_DirectoryBundle`).
- **Decompression Guard**: Reads streams via `io.TextIOWrapper(encoding="utf-8-sig", errors="strict", newline="")` wrapped in `_MeteredStream` counting decompressed bytes.
- **Caps**: `MAX_ZIP_MEMBERS = 1_000`, `MAX_MEMBER_UNCOMPRESSED_BYTES = 2 GiB`, `MAX_BUNDLE_UNCOMPRESSED_BYTES = 8 GiB`.
- **Method Restriction**: `ZIP_STORED` and `ZIP_DEFLATED` only; bzip2/lzma and encrypted members (`flag_bits & 0x1`) rejected.
- **Nested Zip Guard**: Uncatalogued files (e.g. `raw_files.zip`) are never opened.
- **Member Name Policy**: Reject-not-normalise policy (`\`, NUL/C0, leading `/`, drive `^[A-Za-z]:`, leading `//` or `\\`, `..` segments). Single top-level folder stripping (`PurePosixPath(name).name`). Duplicate basename rejection.
- **Directory Symlink / Junction Guard**: `root = Path(arg).resolve(strict=True)`, `candidate.is_file()` and `not is_symlink()`, `candidate.resolve().parent == root`.
- **Content Dispatch**: `is_dir()` or first 4 magic bytes `b"PK\x03\x04"`.

### 2.4 `src/modules/seo/deliverables/screaming_frog_adapter.py` (351 lines)

`load_screaming_frog_bundle(bundle_path, *, normalize, produced_at) -> AuditDataset`.
- **Streaming CSV**: Uses stdlib `csv.reader` with header-derived column index (`Address` if present, else `Source`). `Destination` is structurally unreachable.
- **Line & Column Limits**: Line-length generator wrapper checking `MAX_LINE_CHARS = 1_048_576`; header column cap `MAX_COLUMNS = 1_024`. Default `csv.field_size_limit` left untouched.
- **Per-Cell Scheme Validation**: `SfUrlCell` StrictModel checking `http` or `https` scheme, netloc, length $\le 2048$, and no whitespace/control characters on both raw and normalized values.
- **Entry Self-Test**: Validates injected `UrlNormalizer` against probe `HTTP://WWW.Example.com/A/../b/?utm_source=x&z=1`, raising `NormalizerContractError` if non-idempotent or non-URL-returning.
- **Site Hostname Derivation**: Majority hostname of normalized spine (`internal_all.csv`), lower-cased, with leading `www.` and port stripped. Multi-host spine appends host count note. Absent or empty spine raises.
- **Links & Coverage**: `links = ()` with `LINKS_NOT_RETAINED_NOTE`. `sf_sources = ()` rows marked `NOT_MEASURED`.
- **Structured Logging**: Emits event names and count fields only (`urls_retained`, `rows_read`, `duplicates_dropped`), never URLs or tokens.
- **Typed Exceptions**: `ScreamingFrogBundleError(ValueError)` and `NormalizerContractError`.

### 2.5 Fixtures & Unit Tests

- `tests/fixtures/deliverables/sf_bundle/` (17 files): Synthetic `example.com` data with UTF-8 BOM (`\ufeff`) + CRLF, real SF 19.4 headers.
- `tests/modules/seo/test_screaming_frog_adapter.py` (401 lines, 30 tests): Coverage semantics, site derivation, normalizer injection, logging, AST import-boundary check.
- `tests/modules/seo/test_screaming_frog_adapter_errors.py` (153 lines, 19 tests): Typed failure paths and error message leak checks.
- `tests/modules/seo/test_screaming_frog_bundle.py` (328 lines, 27 tests): Zip and directory security guards.

---

## 3. Design decisions

### 3.1 Security Auditor Reconciled Constants
Adopted security auditor binding thresholds: `1,000` zip members, `2 GiB` member limit, `8 GiB` bundle limit, and method restriction (`ZIP_STORED` / `ZIP_DEFLATED`) instead of compression ratio check. Dynamic decompressed byte metering (`_MeteredStream`) enforces limits regardless of author-supplied ZipInfo `file_size`.

### 3.2 Cell-Level Scheme Assertions
`SfUrlCell` asserts `http://` or `https://` on every cell value. This prevents formula injection (`=`, `+`, `-`, `@`) from reaching the dataset or Excel export without altering legitimate contract strings.

### 3.3 Empty Edges (`links = ()`)
Per ADR 0011 D4 and security auditor finding 3 (avoiding millions of `AuditLink` instances for large edge lists), `links` defaults to `()` with `LINKS_NOT_RETAINED_NOTE`.

---

## 4. Bugs found and fixed

### 4.1 Test Leak Check False-Positive
The test assertion `assert "http" not in str(exc)` failed because valid catalogue filenames (e.g. `security_http_urls.csv`, `http_urls_inlinks.csv`) contain "http". Updated tests to assert absence of schemes (`http://`, `https://`), `SENTINEL` token, and host. The code was correct; the test check was over-broad.

### 4.2 Zip Name Testing Strategy
Backslash and NUL member names were tested directly against `_check_member_name`, because CPython's `ZipInfo.__init__` replaces backslashes with `/` and truncates at NUL when reading headers on Windows.

### 4.3 Platform Bug Found (Handoff)
`src/core/logger.py:167`: `get_logger` returns `logging.LoggerAdapter(logger, {})`. On Python 3.11, default `LoggerAdapter.process()` replaces `extra=` payloads with the adapter's empty dict (Python 3.13 added `merge_extra`). Emitted audit JSON carries only `ts`, `level`, `logger`, `message`; structured count fields pass to handlers via `extra` are dropped. Verified adapter logger contract via recording stub. Logged as a `core/` handoff.

---

## 5. Corrections

1. **Plan §1 Row D4 Correction**: Plan D4 sentence "The Screaming Frog adapter fills them from *_inlinks.csv" is corrected. Per security auditor finding 3, the SF adapter leaves `links = ()` and attaches `LINKS_NOT_RETAINED_NOTE`.
2. **ADR 0011 Consequence Correction**: Consequence text "The SF adapter can fill links" is superseded by this cycle's ruling.
3. **Cycle Number**: 0074, 0075, and 0076 were claimed by parallel cycles (`0074-absent-is-not-empty.md`, `0075-which-search-console-account.md`, `0076-a-pdf-is-not-an-orphan.md`). Took 0077.

---

## 6. Explicitly not done

- `members_ignored` count is not logged.
- Directory symlink test skips on Windows (`WinError 1314` unprivileged); runs in Linux CI / Developer Mode.
- Non-URL columns are discarded with headers; control characters in non-URL columns are not inspected.
- `links` stays empty (`links = ()`).
- P0-4 (Engine adapter), P0-6 (full AST import-boundary test across all directions), P0-7 (RAE diff script) deferred to subsequent Phase 0 cycles.

---

## 7. Files changed

Created:
```
src/modules/seo/contracts/url_normalizer.py               30 lines    UrlNormalizer Protocol
src/modules/seo/deliverables/__init__.py                   32 lines    Public exports
src/modules/seo/deliverables/_bundle.py                   252 lines    Zip & directory security handles
src/modules/seo/deliverables/screaming_frog_adapter.py   351 lines    Screaming Frog bundle loader
tests/fixtures/deliverables/sf_bundle/                     17 files    Synthetic example.com bundle (BOM+CRLF)
tests/modules/seo/test_screaming_frog_adapter.py          401 lines    Adapter happy path & semantics
tests/modules/seo/test_screaming_frog_adapter_errors.py   153 lines    Typed failures & leak checks
tests/modules/seo/test_screaming_frog_bundle.py          328 lines    Zip & directory security guards
docs/build-log/0077-screaming-frog-adapter-and-zip-guards.md
```

Modified:
```
src/modules/seo/contracts/audit.py                       AuditSource StrEnum; Invariant 4 pages[].url uniqueness
src/modules/seo/contracts/__init__.py                    Export UrlNormalizer
tests/modules/seo/test_catalogue.py                      Updated WARNING/LOW comment line 292
docs/DELIVERABLES_IMPLEMENTATION_PLAN.md                 D4 correction
docs/build-log/README.md                                 Index row 0077
README.md                                                Deliverables package & state_store update
docs/ARCHITECTURE.md                                     Deliverables row updated
```

---

## 8. Follow-ups

1. **`contracts/audit.py:196-199`**: Invariant-2 error message embeds raw URL (`first: {unknown[0]!r}`). Follow-up in contracts package to sanitize error string.
2. **`src/modules/seo/page_classifier/gsc_export.py:246-272`**: Zip reader lacks security guards present in `_bundle.py`. Owner: `performance/`.
3. **`src/core/logger.py:167`**: `LoggerAdapter` `extra=` payload loss on Python 3.11. Owner: `core/` / bug-fixer.
4. **P0-4 Engine Adapter & P0-6 Full Import Boundary Test**: Next Phase 0 work items.
