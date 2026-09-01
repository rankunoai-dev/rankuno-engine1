# Cycle 0046: A download per section, and a section count that raised a question

- **Date**: 2026-08-21
- **Scope**: Per-section CSV export on the recommendations panel, a count on the
  Sections heading, and the mismatch that counting exposed.
- **Commit**: uncommitted at time of writing
- **Quality gate**: `1530 passed` Python / `103 passed` UI / `Total coverage: 90.12%`

---

## 1. Gate results

```
PASSED: Format
PASSED: Lint
Success: no issues found in 51 source files
PASSED: Type check
Required test coverage of 85.0% reached. Total coverage: 90.12%
1530 passed, 1 warning in 130.37s (0:02:10)
PASSED: Tests
 Test Files  11 passed (11)
      Tests  103 passed (103)
PASSED: UI Component Tests
```

Frontend: `tsc --noEmit` exit 0, `vite build` exit 0 (20.00s).

Coverage fell from 95.84% to 90.12% within this cycle. Nothing here removed a
test; the denominator grew as parallel work landed new performance modules. It
is above the 85% floor and is recorded rather than explained away.

---

## 2. Design decisions

### 2.1 One download per section, because each section has a different owner

The panel had a single `Download CSV` covering every recommendation kind. The
kinds are not one job: *earning clicks with no internal link* is work for a
content team, *earning clicks from deep in the navigation* is an
information-architecture change, and *ranking off page one beside a linked
sibling* is a linking decision. Handing any one owner the combined file means
they filter it before starting.

Each section heading now carries its own `Download N`, and the whole-report
button stays where it was.

### 2.2 Built in the browser, and the reason is not convenience

A `?kind=` parameter on `/jobs/{id}/opportunities.csv` was the obvious
alternative and is the wrong one. Capping happens in `opportunity_scorer`
**before anything is stored**, so the sidecar on disk holds the same top-N per
kind that the panel already received. A server route would re-serve this exact
list from disk while implying it had gone back to a fuller source.

The client rows *are* the server rows. Building the file where the data already
is keeps one definition of the list.

### 2.3 The header order matches the whole-report CSV

`kind, score, url, section, clicks, impressions, position,
inbound_internal_links, reason` — same order as the server's file, so a section
export and the whole-report export concatenate without reconciliation.

### 2.4 Two different truncations, kept apart in the wording

The section can be short of the full finding count for two unrelated reasons,
and the earlier single message conflated them:

* **Shown here vs in the file** — the table displays a window; the download has
  every scored row. `showing N here · all M in the download`.
* **Beyond the scoring ceiling** — those rows were scored, counted, and
  *discarded* before the response was built. No download can produce them, and
  the button's title says so: *"…are not stored anywhere."*

A reader who cannot tell these apart will go looking for a file that does not
exist.

---

## 3. The section count, and what it exposed

The count asked for on the `Sections` heading is one line. Verifying it against
the visualizer was not, and the answer is worth more than the count.

**The panel's sections and the visualizer's tabs are not the same list.**

| | Panel `Sections` | Visualizer tabs |
| :--- | ---: | ---: |
| gep.com (8,139 pages) | **30** | **36** |
| highradius.com (8,827 pages) | **31** | **31** |

Both are grouped from `breadcrumb_path`, but `navTree.buildNavTree` prepends the
**URL locale** to a localised page's trail while `aggregator.section_path_of`
does not. So the visualizer splits `/de-de/…` into its own tab and the panel
rolls those pages up under whatever breadcrumb they publish — which is itself
translated.

Measured, not asserted:

* gep.com — only in the visualizer: `de`, `de-de`, `es-es`, `fr-fr`, `it-it`,
  `jp-ja`, `zh-cn`. Only in the panel: `Home`.
* highradius.com — **the same count, 31 against 31, and different sets.** Only
  in the visualizer: `de`, `en-gb`, `fr`, `lp-demo`. Only in the panel:
  `Accueil`, `Startseite`, `EN`, `Conformité des frais bancaires`.

An equal count with unequal membership is worse than an obvious mismatch,
because it survives a glance. The heading now states the grouping rule beside
the count rather than leaving the two lists to be assumed identical.

---

## 4. Bugs found and fixed

**No fix shipped this cycle. One bug found and left in, deliberately.**

`localeOf` in `navTree.ts` treats **`lp-demo` as a locale**. Its `REGIONAL`
pattern is `^[a-z]{2}[-_][a-z]{2,4}$`, and `lp-demo` matches it — `lp` + `-` +
`demo`. Highradius' landing-page prefix is therefore rendered as a language
tab in the visualizer, sitting beside `de`, `fr` and `en-gb` as though it were
one.

Not fixed here because the fix is a judgement call this cycle has no mandate
for: the pattern exists precisely to catch region-qualified locales by shape
without a list, and tightening it to a known-region list, or requiring the first
half to be a known language, changes which tabs a stored crawl produces. That is
the visualizer's grouping semantics, and it deserves its own cycle rather than a
correction attached to an export feature.

`de` and `fr` appearing alongside `de-de` and `fr-fr` on gep.com is a second
symptom of the same area — two spellings of one language becoming two tabs — and
is left with it.

---

## 5. Corrections

**This entry was drafted as cycle 0043 and renumbered twice.** Parallel sessions
claimed 0043 and 0044 while it was being written; the buttons entry beside it
moved from 0039 to 0043 to 0045 for the same reason. No published number was
changed — only unpublished drafts — but it is recorded because the index is the
only thing keeping these ordered and it was briefly wrong.

**A test failure reported mid-run in this cycle was not real.** The
`PerformancePanel` suite failed on `149 beyond the scoring ceiling were not
kept` while a parallel session was editing that file; the test passed in
isolation immediately after and passes in the full run above. Recorded because
the first instinct was to change the assertion, which would have papered over a
passing test.

---

## 6. Explicitly not done

- **The scoring ceiling is unchanged.** 50 per kind, applied in the scorer. The
  other 152 of gep.com's 202 `ranking off page one` findings are not on disk and
  no download can produce them. Raising the cap means re-running the scorer over
  a stored export, which is a server change.
- **The two section lists are not reconciled**, only labelled. Making them agree
  means choosing which is right — locale-split tabs describe how the site is
  indexed, breadcrumb rollup describes how it is signposted — and both are
  defensible. Naming the difference is what this cycle does.
- **`localeOf` is not fixed.** See §4.
- **No `.xlsx`.** Unchanged from cycle 0036 §2.4.
- **The section count is of what the panel lists**, i.e. depth-1 rows, not the
  928 trail prefixes in the rollup. Deeper sections remain the tree's job.

---

## 7. Files changed

```
rankuno-ui/src/components/jobs/PerformancePanel.tsx   per-section export,
                                                      section count + note
rankuno-ui/src/components/jobs/jobs.css               .perf-download-sm
rankuno-ui/src/components/jobs/PerformancePanel.test.tsx  +5 tests
```

---

## 8. Follow-ups

1. **Decide the locale question** (§4, §6). It changes tab counts on every
   stored multilingual crawl, so it wants a decision before more reports go out.
2. **Re-score from a stored export**, so the scoring ceiling can be raised
   without a fresh upload.
3. **One export for the whole audit** — still open from cycle 0036.
