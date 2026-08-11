# Cycle 0015: The navigation dashboard, and a WAF option that did not work

- **Date**: 2026-08-11
- **Scale**: Port the reference dashboard into `rankuno-ui`; make browser mode
  actually reach blocked sites.
- **Commit**: uncommitted at time of writing
- **Quality gate**: 949 tests, 95.66% coverage, `mypy --strict` clean

---

## 1. Gate results

```
=== Format ===      PASSED   All checks passed!
=== Lint ===        PASSED   All checks passed!
=== Type check ===  PASSED   Success: no issues found in 41 source files
=== Tests ===       PASSED   949 passed in 18.71s
                             Required test coverage of 85.0% reached. Total coverage: 95.66%
ALL GATES PASSED.
```

Frontend: `npx tsc --noEmit` exit 0, `npx vite build` exit 0. Main bundle
**1,225 kB → 752 kB**, because React Flow is no longer reachable.

---

## 2. Correction: the WAF option shipped non-functional

Cycle 0014 added `browser_headers` and this log recorded it as built. It was
**unreachable and ineffective**, and the operator found it by crawling
infosys.com and getting the same blocked-crawl failure the option was added to
solve.

Two independent defects:

1. **`BROWSER_USER_AGENT` was defined, exported in `__all__`, and referenced by
   nothing.** `browser_headers` sent only `Accept` and `Accept-Language`; the
   product token stayed `RankunoBot`. Every edge this option exists for filters
   on the user agent, so the toggle could not have worked on any of them. A
   `grep` for the constant returns its definition and its export — and no use.

2. **`user_agent` was never exposed in the crawl form.** So the manual route was
   closed too. The field existed on `PageClassificationInput` and on
   `DEFAULT_CRAWL_REQUEST`; no control wrote to it.

Neither had a test. The 0014 tests covered `browser_headers` reaching the
fetcher, not the fetcher doing anything with it — the gap between "the wiring is
connected" and "the feature works", which a gate cannot see.

### Fixed

`browser_headers=True` now sends `BROWSER_USER_AGENT`, unless an explicit
`user_agent` was given — an operator who named an identity meant it, and
silently replacing it would make the audit log disagree with what was sent.
robots.txt is matched against whatever token is actually sent: presenting one
identity and obeying another's rules is incoherent.

The form now exposes `user_agent`, with the placeholder reflecting what browser
mode will substitute.

### Verified live, both paths

```
=== default token (RankunoBot) ===
status : failed — all 3 requests to https://www.infosys.com/ were refused

=== browser mode ===
status : partial
result : total_urls 40 | pages_fetched 38 | sitemaps 0 | refusals 2
nav    : dom | links 5
tabs   : ['Home', 'Navigate your next', 'Investors', 'Infosys Knowledge Institute', 'Careers']
```

The A/B is the point: same URL, same budget, one variable.

Two things that measurement does **not** say. `sitemaps 0` with `refusals 2` —
infosys.com still refuses the sitemap probes, so this crawl is DOM-only. And
`nav links 5` is a thin menu for a site that size, consistent with a
largely client-rendered header; the five tabs found are real but not the whole
navigation.

---

## 3. The dashboard port

Ported from the supplied reference HTML into React 18 + TypeScript.

* `styles/design-system.css` — the token ramp, one colour set per navigation
  depth plus OTHERS.
* `lib/dashboardModel.ts` — flattens a crawl result into an index-addressed node
  array. Flat because the virtual list, the search index and the graph all
  address nodes by position thousands of times a second while scrolling.
* `store/useDashboardStore.ts` — open set, focus, filters, child paging. The
  flattened view-model is rebuilt on filter or tree change, never per scroll
  frame.
* `components/tree/VirtualizedTree.tsx` — the windowing arithmetic from the
  reference, ~25 rows in the DOM. Roots open, everything else collapsed:
  expanding 20,000 nodes by default produces a 20,000-row view-model on first
  paint for a list nobody has scrolled.
* `components/graph/FocusGraphStage.tsx` — swimlanes, SVG bezier wires, child
  pager. Lane geometry is **measured** after layout rather than computed,
  because lanes are flex children whose heights change when one expands; wires
  are re-measured on the `flex` transition's settle or they visibly miss.
* `components/inspector/NodeInspector.tsx`, `metrics/KpiMetricStrip.tsx`,
  `layout/NavigationRail.tsx`, `layout/DashboardShell.tsx`.

Every tree walk is iterative. Recursion over 20,000 nodes overflows the stack,
and that failure is a blank screen with no error.

### Deliberately not reproduced from the reference

| Reference | Built instead | Why |
| :--- | :--- | :--- |
| Per-page "WAF status" | Confidence, consensus method, link counts, orphan flag | The reference computes it as `n.i % 7`. The engine has no per-page block status — only a crawl-level `fetch_failures`. |
| Fixed R0–R3 resolver chips | Chips derived from methods present | Layers 2 and 3 have no implementation, so three of four chips would filter to nothing forever. A control that looks functional and is not is worse than none. |
| `$0.00` LLM spend | `summary.llm_spend_usd` + real escalation rate | A hard-coded zero keeps reading zero after Layer 3 starts costing money. |
| Cascade step "Skipped · $0.00" | "not implemented" | "Skipped" implies the cascade declined to use a layer that exists. |
| Four resolver chips | Five methods | The engine also emits `WEIGHTED_CONSENSUS`, which the reference had no slot for. |

The AntD safety banners were kept rather than dropped in the port: truncation,
synthetic data, zero-fetch and blocked-crawl each cost a cycle to make visible
(build-logs 0012 and 0013).

---

## 4. Explicitly not done

* **60fps at 20,000 nodes is unverified.** No browser automation here. The
  in-app evidence is the tree footer's live `DOM rows: N / total`, which should
  read ~25 while scrolling the `synthetic-20000` fixture. If it climbs,
  virtualization is broken.
* **Six components are now orphaned**: `ReactFlowGraph`, `DirectoryPane`,
  `SplitPaneLayout`, `PageDetailDrawer`, `HeaderBar` are imported by nothing, and
  `@xyflow/react` is reachable only from the dead `ReactFlowGraph`. Left in place
  pending a decision; this is dead code plus an unused dependency.
* **Still no frontend tests.** `rankuno-ui` has no test runner, which is exactly
  why §2's defect reached the operator instead of a gate.
* **Dashboard and Audit rail entries are `disabled`** with a title saying so,
  rather than live controls that do nothing.
* **No live 20k crawl.** The largest real result remains 600 URLs.
