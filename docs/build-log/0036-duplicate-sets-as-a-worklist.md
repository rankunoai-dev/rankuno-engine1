# Cycle 0036: 1,920 URLs is not the number to hand anyone

- **Date**: 2026-08-20
- **Scope**: Make the duplicate-URL finding downloadable, with each page's copies
  clustered rather than listed flat.
- **Commit**: uncommitted at time of writing
- **Quality gate**: `1388 passed` Python / `57 passed` UI / `Total coverage: 95.48%`

---

## 1. Gate results

```
PASSED: Format
PASSED: Lint
Success: no issues found in 45 source files
PASSED: Type check
Required test coverage of 85.0% reached. Total coverage: 95.48%
1388 passed, 1 warning in 100.51s (0:01:40)
PASSED: Tests
 Test Files  7 passed (7)
      Tests  57 passed (57)
PASSED: UI Component Tests
```

Frontend: `tsc --noEmit` exit 0, `vite build` exit 0 (11.94s).

An earlier draft of this entry recorded `1372 passed` at `95.22%`. That was the
count *before* `tests/modules/seo/test_canonical_capture.py` was added in this
same cycle — the gate had not been re-run after it landed. The figures above are
from the run that closed the cycle. Noted rather than silently replaced: a
pasted number that was never produced is the failure this section exists to
prevent.

---

## 2. Design decisions

### 2.1 The row is the cluster, not the URL

Reported live from gep.com: *1,920 URLs serving 262 pages*. The card showed five
grouped example lines and then `+ 257 more`.

A table of 1,920 rows would be the wrong instrument even though it is the larger
number. The analyst does not decide 1,920 things; they decide **262**, and each
decision is *which member of this set survives*. Flattening the set loses exactly
the relationship the finding is about, so the drill-down is one row per page with
the copies behind an expander.

`Finding` gained `groups?: FullPageIntelligenceProfile[][]` alongside cycle
0035's `pages?`. `AuditView` picks the drill-down by which one is present — a
finding whose unit of work is a cluster renders `DuplicateTable`, one whose unit
is a page renders `OrphanTable`, and one with neither renders as it always did.

Sorted largest cluster first. A page reachable at seven addresses is a worse
problem than one reachable at two, and the report should open on it.

### 2.2 The survivor is a suggestion, and `rel=canonical` is deliberately not used

`canonical_url` is on the profile and was the obvious input. It is the wrong one:
**a site that had set `rel=canonical` correctly would not have produced this
finding**, so trusting it would recommend keeping whichever address the site has
already lost track of.

Ranked instead on evidence the crawl gathered for itself:

1. **inbound internal links, descending** — the copy the site links to most is
   the one already holding the signal, so redirecting *to* it preserves the most.
2. shortest path
3. no query string
4. alphabetical — so the choice is stable between runs rather than a function of
   crawl order. Tested explicitly (`suggestedSurvivor([a,b]) === suggestedSurvivor([b,a])`).

The column header carries a tooltip saying it is a suggestion and why; the CSV
writes `keep (suggested)` rather than `keep`.

### 2.3 Breadcrumb disagreement is a column, because it changes the cost

The finding's action text already told the analyst the duplicates disagree about
their own parent section. It did not say *which* ones. Where the trails agree, a
canonical tag settles the set. Where they disagree, the site is also publishing
two answers to "what section is this in?", and picking a survivor picks one of
those answers too — a content decision, not a redirect.

### 2.4 CSV, not `.xlsx`

The request was for an Excel sheet. Neither side of this project can write one:
`openpyxl` is an optional read-side dependency (cycle 0031, and
`screaming_frog_reconciler` is explicit that building on an undeclared package
would fail a clean checkout), and the UI has five runtime dependencies, none of
them a spreadsheet library.

CSV opens natively in Excel and needs no dependency. The clustering the request
asked for is carried by a `group` column: one row per URL, ordered by cluster, so
sorting or filtering on that column in a spreadsheet keeps a page's addresses in
one block. Columns: `group`, `action`, `url`, `inbound_internal_links`,
`page_type`, `breadcrumb`, `breadcrumbs_disagree`.

---

## 3. Bugs found and fixed

**The toggle label paired the wrong two numbers.** Cycle 0035 wrote
`See all ${finding.count}`. For a grouped finding `count` is clusters, so beside
a title reading *"1,920 URLs serving 262 pages"* the button read `See all 262`
and invited exactly the misreading the title was phrased to avoid. Now
`See all 262 sets`.

**The export button counted the wrong thing too**, for the same reason, and now
reads `Export CSV (1,920 URLs)` — the URL total, since that is the file's length.

---

## 4. Corrections

**No correction to a previously published number this cycle.** The 1,920 / 262
figures in §2.1 are the operator's report from a live gep.com crawl and are
reproduced here rather than recomputed; §5 records what could not be verified.

---

## 5. Explicitly not done

- **A real `.xlsx` is not written.** See §2.4. If a true workbook is wanted —
  frozen header, one sheet per finding, column widths — it needs a declared
  dependency and is its own decision.
- **`normalize_url` does not fold percent-encoding, and it should.** Verified
  during this cycle: `procurement%E2%80%91ai-agents` and
  `procurement‑ai-agents` (a raw U+2011 non-breaking hyphen) produce **different
  normalization keys**, so the graph holds both and the audit reports them as a
  duplicate pair. That pair — visible in the reported gep.com output — is
  **our artefact, not GEP's defect**, and it is currently being sent to a client
  as a finding about their site. Not fixed here: normalization is the dedup key
  for the entire engine and changing it moves every count in every stored crawl,
  which is a cycle with its own HITL review, not a change to slip into an export
  feature.
- **The duplicate *detection* is unchanged.** Grouping is still last-segment plus
  ancestry match. Locale-prefixed pairs (`/case-studies/jp/…`) and `?page=0`
  variants group correctly; nothing was tuned.
- **No server-side export.** Both drill-downs build their CSV in the browser
  from data already loaded, for the reason given in build-log 0035 §3.4.
- **Not verified against a stored gep.com crawl.** The logic is tested against
  fixtures shaped like the reported output; the 262 clusters themselves were not
  re-derived from a stored result.

---

## 6. Files changed

```
rankuno-ui/src/lib/audit.ts                          Finding.groups,
                                                     suggestedSurvivor
rankuno-ui/src/components/audit/DuplicateTable.tsx   new — the cluster worklist
rankuno-ui/src/components/audit/AuditView.tsx        picks drill-down by shape;
                                                     label disambiguated
rankuno-ui/src/components/audit/audit.css            member list + hint styles
rankuno-ui/src/components/audit/DuplicateTable.test.tsx  new — 14 tests
```

---

## 7. Follow-ups

1. **Fold percent-encoding in `normalize_url`** (§5). This one is producing a
   false finding in a client-facing report right now.
2. **One export for the whole audit**, rather than per finding — an analyst
   sending a report wants every finding in one file.
3. **Carry `groups` on the pagination finding too**; `?page=2` variants are the
   same shape of decision.
