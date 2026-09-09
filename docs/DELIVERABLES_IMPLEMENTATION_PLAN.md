# Client Deliverables: Implementation Plan — Phase 0 and Phase 1

**Status**: APPROVED
**Date**: 2026-09-08

**ADR**: [0011 — Deliverables package boundary and Screaming Frog as an input format](adr/0011-deliverables-boundary-and-screaming-frog-input.md) (APPROVED)
**Origin**: evaluation of `RAE - Copy/` (build-logs 0068–0070 context; RAE review 2026-09-07/08)

This plan is the Step 3 artefact. Nothing in it has been built. Approving it
confirms the six decisions in §1 and authorises Phase 0 to start through the
`/do` sequence (§9). Phase 1 starts only after Phase 0's gate is green.

---

## 1. What approving this plan confirms

Four decisions were left open in review. Each has a proposed default below. Approve
as-is, or strike and replace a row; the plan is built to the row as approved.

| # | Decision | Proposed default | Why |
| :- | :--- | :--- | :--- |
| D1 | Resolving the 30 severity/priority disagreements between RAE's two catalogues | Three rules, applied mechanically: (a) where one table is silent the other wins — 10 rows; (b) the two never-scored rows take the dashboard value — 2 rows; (c) where both have an opinion, **stricter wins** — 18 rows | Every resolution is explainable to a client. The score table was systematically lenient; stricter-wins reverses that. Four wide-gap rows were reviewed by hand and the rule holds. |
| D2 | What the site score is | **Per-category penalty totals, no single site number, in Phase 2.** Phase 0 ships `Severity`/`Priority` enums only; weights are Phase 2. | RAE never defined a site score — its sheet lists per-row penalties nothing sums. Inventing one is a product decision that should not be buried in a port. Category totals are defensible and testable now. |
| D3 | The 10 Security issues whose source CSV exists on disk but is unwired in RAE | **Wire them.** | The data is there. Leaving them permanently "No" is the RAE failure mode this plan exists to stop. |
| D4 | Link edges | **`NOT_MEASURED` in Phase 0/1.** `AuditDataset.links` exists, defaults empty, and Internal Links issues declare `NOT_MEASURED` from the engine adapter. The Screaming Frog adapter does **not** fill them either: it leaves `links=()` and stamps `LINKS_NOT_RETAINED_NOTE` on the dataset (security-auditor finding 3 on P0-3: one `AuditLink` per edge of a 732 MB list is millions of ~1 KB objects). Corrected in build-log 0074; the earlier wording "fills them from `*_inlinks.csv`" was wrong. | Persisting edges changes the engine's memory model (CLAUDE.md §8: whole graph in RAM; RAE's infosys crawl had a 732 MB edge list). That is its own cycle with its own measurement, not a side effect of a contract. |

Two structural choices made in this plan that differ from the roadmap pasted in review:

| # | Choice | Instead of | Why |
| :- | :--- | :--- | :--- |
| S1 | Rulebook themes live on **`AuditPage`** in the dataset, applied by the deliverables package | adding `theme_1`, `theme_2`, `language`, `business_priority` to `FullPageIntelligenceProfile` | "The main engine must not be disturbed." The profile is the canonical Phase 1 contract (ADR 0002) and is mirrored into the UI by the contract exporter; touching it touches everything. Themes are a *deliverables* concern. If the tree view later wants them, that is a separate, small change. |
| S2 | The contract lives in **`src/modules/seo/contracts/`**, a sibling of `page_classifier` and `deliverables` | `src/core/` | `core` is domain-agnostic by rule (CLAUDE.md §5). An SEO issue catalogue is not. A sibling package that both modules import inward from gives the same isolation without polluting `core`. |

---

## 2. Scope

**In scope — Phase 0**: the `AuditDataset` contract; the issue catalogue as typed data;
the Screaming Frog adapter (CSV bundle → dataset); the engine adapter
(`PageClassificationOutput` → dataset) with honest coverage; the import-boundary
test; an opt-in differential check against the RAE archive.

**In scope — Phase 1**: the rulebook — `Rulebook` model, xlsx loader, most-specific-wins
classification, strict-by-default failure, themes applied to `AuditPage`.

**Explicitly out of scope** (later phases, separate approval):

- Workbook generation and the scoring weights (Phase 2).
- Any HTTP endpoint. Phase 0/1 are pure functions over files and models. The upload
  endpoint arrives with the first workbook in Phase 2, and re-runs Step 5 then.
- Driving Screaming Frog via CLI, and `.seospider` import (ADR 0011 §3).
- LLM chat (Phase 4; needs an `LLMClient` provider first — CLAUDE.md §8).
- Persisting link edges in the crawler (D4).
- Any change to `FullPageIntelligenceProfile`, the UI, or `page_classifier` beyond
  one new file that *reads* its output (S1).

---

## 3. Architecture

```
src/modules/seo/
├── contracts/                 NEW  — imported by page_classifier, deliverables, api
│   ├── audit.py                    AuditDataset, AuditPage, AuditLink, Coverage,
│   │                               IssueCategory, Severity, Priority
│   └── catalogue.py                IssueId (StrEnum) + ISSUE_CATALOGUE (typed rows)
├── page_classifier/
│   └── audit_export.py        NEW  — PageClassificationOutput → AuditDataset
└── deliverables/              NEW  — never imports page_classifier
    ├── screaming_frog_adapter.py   CSV bundle → AuditDataset
    └── rulebook.py                 Phase 1
```

**The dependency rule, and its enforcement.** `page_classifier` and `deliverables`
both import `contracts`. Neither imports the other. `tests/modules/seo/test_import_boundary.py`
parses every module's imports with `ast` and fails the build on a violation. This is
the mechanism behind "separate but connected": the isolation is a test, not a convention.

**The contract** (shape; exact fields are Phase 0 work item P0-1):

```python
class AuditDataset(StrictModel):
    source: Literal["engine", "screaming_frog"]
    site: str  # hostname, via normalize_url
    produced_at: datetime
    pages: tuple[AuditPage, ...]  # spine; url is the normalised key
    issues: Mapping[IssueId, frozenset[str]]  # issue → member URLs (normalised)
    coverage: Mapping[IssueId, Coverage]  # MEASURED | NOT_MEASURED — every IssueId
    links: tuple[AuditLink, ...] = ()  # empty means "not retained"
    notes: tuple[str, ...] = ()  # adapter caveats, e.g. denominator semantics
```

Three invariants, each a validator and a test:

1. `coverage` has a key for **every** `IssueId`. An adapter cannot forget a category.
2. Every URL in every `issues` set is in `pages` **or** the dataset carries a note
   saying the adapter admits external URLs for that issue (inlinks destinations).
3. An issue marked `NOT_MEASURED` has an **empty** set. "Not measured" and "measured,
   none found" are different values and cannot be confused.

**Catalogue.** `ISSUE_CATALOGUE` is a tuple of `IssueSpec(StrictModel)` rows —
`id`, `category`, `label`, `severity`, `priority`, `sf_sources: tuple[str, ...]`.
`Severity` and `Priority` are enums, so RAE's twelve blank strings are unrepresentable.
`IssueId` is a `StrEnum` in the same module; a test asserts a 1:1 match between enum
members and catalogue rows. Labels are cleaned (`Structured Data`, `Custom Search`,
`Readability`, `X-Frame-Options`); a `RAE_LABELS: Mapping[IssueId, str]` table keeps the
original spellings for the differential check only.

---

## 4. Phase 0 — work items

| ID | Item | Files | Acceptance |
| :- | :--- | :--- | :--- |
| P0-1 | Contract models — **done, build-log 0073** | `contracts/audit.py` | The three invariants above each have a failing-then-passing test. `extra="forbid"` holds. Round-trips through JSON. |
| P0-2 | Catalogue as data — **done, build-log 0073** | `contracts/catalogue.py` | 110 RAE rows → cleaned rows after D1/D3. Test: enum ↔ rows 1:1; no blank severity/priority possible; every `sf_sources` filename matches the reference export listing (fixture, see P0-5); the D1 resolutions are asserted row-by-row so a future edit is deliberate. |
| P0-3 | Screaming Frog adapter — **done, build-log 0074** (streaming zip/bundle guards added, build-log 0077) | `deliverables/screaming_frog_adapter.py` | Input: a directory or zip of SF CSVs. Reads `Address` (and for inlinks, `Source` only — **not** `Destination`, see §7). `utf-8-sig`. Header-only files → `MEASURED` with empty set. **Absent** file → `NOT_MEASURED`. No size threshold (RAE's 100-byte skip dropped real one-row files). Any read error raises; nothing is `except: pass`. |
| P0-4 | Engine adapter — **done, build-log 0079** | `page_classifier/audit_export.py` | Fills what the profile supports today: Sitemaps (all four, gated on a sitemap having been read), Directives/Noindex, Canonicals/Canonicalised, Response Codes via `indexability == NOT_A_PAGE` + `redirect_chain` (4xx/5xx read from `indexability_reason`, test-bound — D-B), URL Issues (string rules over `url`). Everything else `NOT_MEASURED`: 16 measured / 94 not. Test: a fixture crawl produces the expected sets, and **every** other `IssueId` is `NOT_MEASURED` with an empty set. *Correction (0079 §5.1): this row originally said "Canonicals/Canonicalised + Missing". `CANONICALS_MISSING` is **not** measurable — the profile folds "no canonical declared" into `canonical_url = url` — and is `NOT_MEASURED` by operator ruling D-A.* |
| P0-5 | Fixtures — **done, build-log 0074** | `tests/fixtures/deliverables/` | A synthetic SF bundle (~15 CSVs with real header rows, 5–10 URLs) and a file listing of the real export's 115 filenames. No RAE data enters the repo. |
| P0-6 | Import boundary — **done, build-log 0079** | `tests/modules/seo/test_import_boundary.py` | `ast`-based; fails on `page_classifier ↔ deliverables` in either direction, and on `contracts` importing either. Relative imports resolved; the detector is self-tested against violating sources. Absorbs the one-direction test from P0-3. |
| P0-7 | Differential check (opt-in) — **done, build-log 0081** | `scripts/diff_against_rae.py` | Reads `Settings.rae_archive_dir: Path | None` (via `get_settings()`, never `os.environ`). Skips cleanly if unset. For each crawl folder: our SF adapter's sets vs RAE's `load_url_set` semantics, reporting differences and matching them against a known-differences list (§7). **Not part of the gate.** |
| P0-8 | Docs | build-log (next free number — cycle numbers are claimed at write time, never pre-assigned; this cycle landed as 0073), ADR 0011 → APPROVED, `ARCHITECTURE.md` + `README.md` rows | `drift_check.py` green. |

Effort: roughly three to four working days under the gate, one engineer.

---

## 5. Phase 1 — rulebook

| ID | Item | Files | Acceptance |
| :- | :--- | :--- | :--- |
| P1-1 | Models | `deliverables/rulebook.py` | `RuleType` enum (`CONTAINS`, `STARTS_WITH`, `ENDS_WITH`, `EXACT`, `REGEX`, `FALLBACK`); `Rule`, `Rulebook` as `StrictModel`. Regex rules compiled at load; a bad pattern is a load error, not a runtime one. |
| P1-2 | Loader | same | `Rulebook.from_xlsx(path)`: sheet `Rulebook`, header row auto-detected within the first 5 rows by a cell equal to `URL Pattern`; tolerant of the `Language`/`Languuage`/`Lang` header variants RAE documents; fallback row detected by rule type `—`, `-`, `Fallback`, or pattern `No match`. Missing file raises `RulebookMissingError` by default; `lenient=True` returns an empty rulebook **and** appends a note to the dataset. |
| P1-3 | Classification | same | `classify(url) → Classification(theme_1, theme_2, language, priority)`. All matching rules collected; `EXACT` wins, then longest pattern; case-insensitive except `REGEX`; row order irrelevant. Test the documented shadowing case: `/services` must not beat `/services/annotation-services`. |
| P1-4 | Application | `deliverables/rulebook.py` (`apply_rulebook(dataset, rulebook) → AuditDataset`) | Returns a new dataset with `AuditPage.theme_1/theme_2/language/business_priority` set. Unmatched → fallback row; no fallback → theme `Others`, priority `N/A` — **never** `Low`. Hostname for lookup comes from `normalize_url`, `www.` stripped. |
| P1-5 | Docs | build-log (next free number) | Corrections section records that the pasted roadmap's profile fields were **not** added, and why (S1). |

Effort: one to two days.

---

## 6. Step 5 — security and cost audit

Answered for Phase 0/1 as scoped. Re-run in Phase 2 when an upload endpoint exists.

| # | Question | Answer |
| :- | :--- | :--- |
| 1 | Target hosts and volume | **None.** Phase 0/1 make no network calls. Inputs are local files and in-memory models. |
| 2 | Rate-limit key | N/A — no outbound requests. |
| 3 | Worst-case spend | **$0.** No LLM, no API. `CostLedger` untouched. |
| 4 | Idempotency | Pure functions; same input → same dataset. `RiskClass.READ`. |
| 5 | Circuit breaker | N/A — no upstream. |
| 6 | PII and minimisation | SF exports can carry anything a site publishes, including URLs with query strings. The adapter keeps URLs only, drops every other column, and logs counts — never URLs — at `INFO`. Rulebook files are operator-authored and may name clients; they are read, never logged. |
| 7 | Input sanitisation and injection | Every CSV row passes through a `StrictModel` row type. Regex rules from rulebooks are compiled with a length cap and tested against catastrophic-backtracking patterns. Formula injection is a **Phase 2** concern (no cell is written in Phase 0/1) and is recorded there as a hard requirement: `write_string` for every text cell. |
| 8 | Credentials | None introduced. `rae_archive_dir` is a path, not a secret, and is optional. |

**Governance note carried from review.** Driving Screaming Frog as a subprocess would
bypass `UrlSafetyPolicy`, `robots.py`, the rate limiter, and `BaseAPIClient` — every
mandatory control in CLAUDE.md §1.5 and §5. That path is **not** in this plan, and
ADR 0011 §3 records that it may not be added without its own ADR.

---

## 7. Verification

**Gate** (Step 7, both phases):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify.ps1
.\.venv\Scripts\python.exe scripts\drift_check.py
```

**Differential check** (P0-7) — what it can and cannot prove:

- **Issue membership is Screaming Frog's, not RAE's.** RAE reads CSVs into sets. So the
  CSVs are the oracle for `issues`, and matching RAE's sets validates our reader, not
  RAE's judgement.
- **Known differences** — deliberate, asserted as such, never "fixed" to match:
  1. Inlinks issues: RAE unions `Source ∪ Destination`, flagging the broken target in an
     *inlinks* column. We take `Source` only. The 4xx URL is already in the 4xx issue.
  2. RAE skips files under 100 bytes. We do not; a one-row file is data.
  3. RAE reads only the filenames in its `csvs` column; we read the ten Security files
     it never wired (D3). Those issues will be non-empty for us and empty for RAE.
  4. Labels: we compare by `IssueId` through `RAE_LABELS`, so spelling fixes do not
     register as differences.
- **Not covered:** scoring and workbook layout. There is no RAE site score to compare
  against, and its overview sheet has fourteen identified defects (RAE review, deep
  read §11). Phase 2 treats the RAE workbook as a regression reference with a
  known-differences list, not as truth.

---

## 8. Breaking points carried from the RAE review — and what this plan does about each

| RAE failure | Where it bit | This plan |
| :--- | :--- | :--- |
| Missing input → "0 issues" | `crawl_overview.csv` absent → perfect score; 26 catalogue entries permanently blank, rendered as clean | Invariant 3: `NOT_MEASURED` ⇒ empty set, and the two are distinct values. Coverage mandatory for every `IssueId`. |
| `except Exception: pass` around reads | Encoding errors became "no issues" | No bare excepts in `deliverables`. Ruff `BLE001`/`S110` enforced by the gate. |
| Missing rulebook → every page `Low` | Silent, in client output | `RulebookMissingError` by default; lenient mode stamps a note on the dataset. |
| Two catalogues, 30 disagreements | Same workbook, two severities per issue | One catalogue (D1). Enum-typed. |
| Copy-pasted helpers across 21 builders | A column rename breaks 21 files | One reader in the adapter; builders (Phase 2) read the dataset, never CSVs. |
| Source filenames hard-coded and partly wrong | 10 Security issues unwired | P0-2 validates every `sf_sources` name against a real export listing. |
| Domain never normalised | Five spellings of one client | `normalize_url` at the boundary, in both adapters and the rulebook lookup. |
| Formula injection unguarded | `ws.write` everywhere | Phase 2 requirement, recorded now in §6. |
| Denominator inherited from SF | Internal 4xx spread diluted by external URLs | Phase 2: denominator declared per category; `notes` on the dataset carry the semantics. |

---

## 9. Sequencing and routing

Phase 0 is dispatched through the `/do` sequence (CLAUDE.md §10) with this document as
the brief:

1. `security-auditor` — confirms §6 (fast; nothing touches the network).
2. `feature-builder` — P0-1 → P0-6 in that order, each behind a green gate.
   P0-3 and P0-4 may proceed in parallel once P0-1 and P0-2 are merged.
3. `test-engineer` — P0-7 and the boundary test's negative cases.
4. `docs-scribe` — P0-8: build-log entry (landed as 0073), ADR 0011 to APPROVED, drift check.

Phase 1 repeats the same sequence after Phase 0's gate is green, with `feature-builder`
on P1-1 → P1-4 and `docs-scribe` on P1-5.

Phase 2 (workbook engine, first four masterfiles, scoring, upload endpoint) gets its own
plan and its own Step 3 stop.
