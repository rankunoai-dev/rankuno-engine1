# Cycle 0020: Media URLs stop entering the graph as pages

- **Date**: 2026-08-12
- **Scope**: Enforce the non-page suffix filter at `SiteGraph.add()` so sitemap
  and CMS discovery are screened, not only DOM links; plus the graph-layout and
  PDF-export work carried over from the previous session; plus the Step 8
  gap-register refresh.
- **Commit**: uncommitted at time of writing
- **Quality gate**: `1050 passed, 1 warning in 37.67s` / `Total coverage: 95.62%`

## 1. Gate results

Re-run at the close of the cycle, after the §2 documentation changes. Pasted
verbatim:

```
149 files already formatted
PASSED: Format
All checks passed!
PASSED: Lint
Success: no issues found in 41 source files
PASSED: Type check
Required test coverage of 85.0% reached. Total coverage: 95.62%
1050 passed, 1 warning in 37.67s
PASSED: Tests
ALL GATES PASSED.
```

Frontend, run from `rankuno-ui/`:

```
tsc --noEmit    TSC_EXIT=0
vite build      VITE_EXIT=0    ✓ 3021 modules transformed, built in 10.59s
```

Step 8 drift audit:

```
PASSED: no drift detected across 65 markdown files.
  - all relative links resolve
  - all domain modules documented
  - all skill directories populated
```

An earlier draft of this entry recorded the test run as `41.08s`, and an
intermediate run reported `39.10s` over 148 formatted files. The numbers above
are from the run that closed the cycle. The timing differences are wall-clock
noise on the same 1,050 tests; the 148→149 file count is a source file written
by a concurrent session between the two runs, not a file this cycle added.

`vite build` warns that two chunks exceed 2000 kB — `synthetic-20000` is a
16 MB fixture bundle. It is a warning, not a failure, and the fixture is
deliberately large: it is the 20,000-URL dataset the dashboard is tuned against.
Code-splitting it is a follow-up, not a gate blocker.

## 2. What landed

### `url_rules.NON_PAGE_SUFFIXES` and `is_crawlable_url()`

The suffix list moved out of `discovery_parsers.py` and became public in
`url_rules.py`, with `is_crawlable_url()` in front of it. It belongs there
because it is a property of a URL *string* — the same category as
`is_faceted_filter` and `normalize_url` — and because three discovery paths now
need it rather than one.

The predicate tests `parts.path`, not the whole URL, so `?download=report.jpg`
stays a page and `/hero.jpg?w=800` does not. An unparseable URL returns `True`:
it is not media, and refusing it here would remove it from the reporting that
exists to make malformed links visible.

### `SiteGraph.add()` enforces it

The filter runs at the graph boundary rather than in each discovery path,
because `add()` is the one function sitemap, CMS, DOM and seed ingestion all
pass through. A path added later inherits the screen without anyone remembering
to wire it.

The crawl root is exempt. An operator who types a URL ending in a media suffix
should get a report that says the site produced nothing, not an empty graph with
no explanation in it.

### `media_skipped` on the graph, the report, the CLI and the printed PDF

Counted rather than silently dropped. On an image-heavy WordPress site this is
the difference between "the sitemap listed 400 pages" and "the sitemap listed
400 entries, 300 of which were uploads", and a reader who cannot see the number
has no way to distinguish them. `DiscoveryReport.media_skipped` regenerated the
TypeScript contract, and the printed report carries it beside the sitemap count.

### Carried over from the previous session

`FocusGraphStage` lane sizing (expanded lane sized to its wrapped row count,
capped at the exact remaining height budget, row spacing derived from the
*measured* lane height), `clampX`/`columnsFor` to stop sibling cards overlapping
and clipping under the lane tab, and the print-to-PDF report.

### `CLAUDE.md` §8 gap register, rewritten

The register had drifted badly enough to be actively misleading — see §5. What
changed:

- `state_store.py` moved out of "does not exist" into a new **Closed in the
  cycle-0020 audit** subsection, with the superseded "an interrupted crawl loses
  its work" claim explicitly marked superseded rather than deleted.
- The "Phase 1 — not started, only `schemas.py` exists" line was replaced with
  the actual shipped inventory, including the two filename mismatches that let
  the entry survive so long.
- Ruling #2 in §7 kept its claim that the governed pipeline has no checkpoint
  step — that is still true — but now says so precisely, and names
  `CrawlCheckpointer` as a crawl-level facility so the two are not conflated.
  Verified before editing: there is no step or checkpoint machinery in
  `base_tool.py`.
- Real gaps that were *missing* from the register were added: Layers 2 and 3 are
  protocols only, the ADR 0005 cost-model finding from cycle 0007, whole-graph
  RAM residency, and the checkpoint limitations from cycle 0019 §6.
- The golden-corpus line now carries the real number — 13 labels, 1 of 6
  archetypes — instead of "no golden test corpus yet", which stopped being true
  at cycle 0009 and understated the ≥98% claim's status by implying the
  framework was missing rather than the coverage.

## 3. Design decisions

**The filter is a suffix test, not `pathlib`.** The plan specified
`pathlib.Path(urlparse(url).path).suffix.lower()`. On Windows `Path` resolves to
`WindowsPath`, which treats a backslash as a separator and parses drive letters
— neither is true of a URL path, and the engine's primary development target is
Windows. `str.endswith(tuple)` is OS-independent, already had tests, and handles
the `/v1.0/details` case identically.

**One list, not two.** The plan proposed a new `NON_HTML_MEDIA_EXTENSIONS`
constant beside the sitemap parser. Every one of its fourteen entries was
already in `_NON_PAGE_SUFFIXES`. Two lists covering the same concept drift the
first time either is edited, so the existing one was promoted instead.

**`.pdf` is deliberately still crawlable.** The plan's prose named `.pdf` as a
target; its enumerated list did not. A whitepaper or datasheet is an indexable,
ranking asset, and an SEO audit that cannot see them is missing real surface.
They do classify poorly — the pipeline parses HTML — but the answer to that is a
document page type, not hiding them from discovery. Flagged rather than assumed:
if these turn out to be noise on HighRadius, reversing it is one line.

**`.txt` remains absent** for the reason recorded in cycle 0010: `llms.txt` is a
Phase 7 input.

## 4. Bugs found and fixed

### The filter existed and was only wired to one of three paths

`_NON_PAGE_SUFFIXES` has been correct since cycle 0004. `_is_page_link` applied
it inside `extract_page_links` — the DOM-link path — and nothing applied it to
`document.locations` from a sitemap or to `parse_wordpress_records` output. A
WordPress `attachment-sitemap.xml` therefore put one graph node per uploaded
image straight into the report, each one fetched and then classified UNKNOWN at
0.0 confidence. This is the same failure mode as `allbirds.com/agents.md` in
cycle 0010; that fix addressed the symptom on the path that had a screen, and
did not notice that two paths had none.

### Spec bug: the proposed fix would have broken all multi-sitemap discovery

The plan placed the filter inside the `<loc>` extraction loop in
`parse_sitemap`. That loop serves **both** document kinds, and a
`<sitemapindex>`'s locations are the child sitemaps — `page-sitemap.xml`,
`post-sitemap.xml`. `.xml` is on the non-page list. Applied there, the filter
would have discarded every child sitemap and reduced WordPress discovery to
zero, which is most of the sites this engine crawls. It would also have looked
like a *success*: the crawl still completes, the DOM path still finds pages, and
the only symptom is a much smaller graph.

`test_a_sitemap_index_is_still_traversed` exists specifically to fail if anyone
moves the filter back there.

### Ruff `D301` on the new docstring

The docstring contained an escaped backslash while explaining Windows path
separators, which requires an `r` prefix. Reworded rather than prefixed — the
prose reads better without it.

## 5. Corrections

Cycle 0010 §7 described the `agents.md` fix as closing the non-page problem;
that was true for the path it examined and incomplete for the crawl as a whole.
It is recorded here rather than edited there.

### `CLAUDE.md` §8 had been wrong for eleven cycles

The register that exists to stop the agent overclaiming was itself the most
inaccurate document in the repository, and it fails in the *dangerous*
direction: §8 is the file an agent reads to learn what not to claim, so a stale
entry there suppresses working features rather than inventing missing ones.

Specifically wrong at the start of this cycle:

- **"`src/core/state_store.py` — does not exist."** It has existed since cycle
  0012 and is at 98% coverage. The same bullet added "until it does, an
  interrupted crawl loses its work" — which cycle 0019 §4 had *already*
  corrected once, in a build-log entry, without the register being updated.
  That is the correction mechanism working and then not being propagated.
- **"Phase 1 `signals.py`, `pipeline.py`, `tool.py`, `tree_visualizer.py` — not
  started. Only `schemas.py` exists."** All four capabilities shipped, across
  cycles 0002–0006. This one survived so long partly because it was
  *unfalsifiable by search*: two of the four names never existed. Anyone
  checking `signals.py` or `pipeline.py` found nothing and read that as
  confirmation, when the code had shipped as `signal_parsers.py` and
  `cascading_pipeline.py`. A gap register keyed on filenames rather than
  capabilities will do this again.
- **"No golden test corpus yet."** The corpus and evaluation harness landed in
  cycle 0009. The true gap is coverage — 13 labels, 1 of 6 archetypes — and the
  ≥98% accuracy claim remains unverified for that reason, not for the stated
  one. The conclusion happened to be right; the reasoning was wrong, which is
  worse, because the wrong reason points at the wrong fix.

Ruling #2's checkpoint claim was checked and **left standing**: the governed
pipeline genuinely has no checkpoint step. It was reworded, not corrected.

No verification was performed against the register in this cycle beyond reading
the source tree and confirming absences directly — `circuit_breaker.py` and any
idempotency module were confirmed absent by search before being left in place.

## 6. Explicitly not done

- **PDFs are not classified.** They enter the graph and will classify as UNKNOWN
  or on URL patterns alone. A `DOCUMENT` page type is not implemented.
- **No content-type verification.** The screen is on the URL string only. A page
  served at an extensionless URL with `Content-Type: image/jpeg` still enters the
  graph. Doing better means fetching first, which is the cost this filter exists
  to avoid.
- **`media_skipped` has no UI banner.** It appears in the printed report and the
  CLI output, not as an on-screen alert. It is not a failure, so it does not
  warrant one.
- **Nodes already stored in existing checkpoints are not re-filtered.** A crawl
  checkpointed before this change and recovered afterwards will still show its
  media URLs.
- **`drift_check.py` does not verify the §8 gap register.** It checks links,
  module documentation and skill directories, and it passed on 64 files
  throughout the eleven cycles the register spent claiming shipped modules did
  not exist. Keeping §8 honest is a manual step, which is precisely why it
  rotted. A check that asserts every `src/**/*.py` named in §8 as absent is in
  fact absent would have caught the `state_store.py` line immediately — but not
  the `signals.py` line, which named a file that never existed. That one needs
  capability-level assertions, and is not attempted here.
- **The rest of §8 was not re-verified.** Only the entries this cycle touched
  were checked against the tree. The remaining bullets are inherited on trust,
  and the same rot may exist in them.
- **No `git mv` to `0020-graph-chokepoint-media-filtering.md`.** The cycle was
  requested under that name, but a 0020 entry already existed and was already
  indexed; two files sharing a cycle number breaks the numbering rule in this
  directory's README. This entry was extended instead.

## 7. Files changed

| File | Change |
| :--- | :--- |
| `src/modules/seo/page_classifier/url_rules.py` | `NON_PAGE_SUFFIXES`, `is_crawlable_url()` |
| `src/modules/seo/page_classifier/discovery_parsers.py` | List and `_is_page_link` removed; delegates |
| `src/modules/seo/page_classifier/discovery.py` | Filter in `SiteGraph.add()`; `media_skipped` on graph and report |
| `scripts/run_crawl.py` | Prints `media skipped` |
| `rankuno-ui/src/types/schema.ts` | Regenerated |
| `rankuno-ui/src/components/report/CrawlReport.tsx` | Media/sitemap KPI row |
| `rankuno-ui/src/components/layout/DashboardShell.tsx` | Report moved outside `.rk-dash` |
| `rankuno-ui/src/components/report/report.css` | Print height/colour reset |
| `rankuno-ui/src/components/graph/FocusGraphStage.tsx` | Lane sizing, card wrapping |
| `rankuno-ui/src/styles/design-system.css` | Lane `min-height` + transition |
| `tests/modules/seo/test_url_rules.py` | `TestIsCrawlableUrl` |
| `tests/modules/seo/test_discovery.py` | `TestNonPageFiltering` |
| `CLAUDE.md` | §8 gap register rewritten; §7 ruling #2 reworded |
| `docs/build-log/README.md` | Index row 0020 |

Not committed: `.claude/settings.json`, an auto-generated tool permission
containing an absolute path to one developer's home directory. It is machine
state, not project configuration.

## 8. Follow-ups

- Decide whether `.pdf` should become a `DOCUMENT` page type or be excluded.
- Consider filtering on `Content-Type` for extensionless media, if it is ever
  observed in a real crawl. It has not been yet.
