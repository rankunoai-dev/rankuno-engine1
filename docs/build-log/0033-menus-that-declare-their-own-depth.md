# Cycle 0033: Menus that declare their own depth

- **Date**: 2026-08-20
- **Scope**: Let a nav item that states its own top-level status be treated as
  one. Prompted by gep.com showing "Careers" nested under "Company" when the
  site has a Careers tab in its header.
- **Commit**: uncommitted at time of writing
- **Quality gate**: `1369 passed, 1 warning in 109.38s` / `Total coverage: 95.50%`

---

## 1. Gate results

```
PASSED: Format
All checks passed!
PASSED: Lint
Success: no issues found in 45 source files
PASSED: Type check
Required test coverage of 85.0% reached. Total coverage: 95.50%
1369 passed, 1 warning in 109.38s (0:01:49)
PASSED: Tests
 Test Files  4 passed (4)
      Tests  23 passed (23)
PASSED: UI Component Tests
ALL GATES PASSED.
```

---

## 2. Why nesting cannot answer this

gep.com's header renders its top-level tabs as elements that are not links:

```html
<a class="nav-link" id="careers-tab" data-bs-toggle="pill"
   data-bs-target="#careers" role="tab">Careers</a>      <!-- no href -->
<div title="Careers" class="primary-links hamburger-next-option">Careers</div>
```

`_NavCollector` derives depth from `<ul>` nesting, which is the only structure
normally present. Here it is absent by construction, and the site's hamburger
menu is **52 sibling `<ul class="site-map-menu">` lists** rather than one tree —
so there is no nesting relationship between the ten top-level items at all.

The parser therefore took the shallowest *real* link in each mega-menu panel as
a root. Inside the Company panel that is `/company`, and every link in the panel
— including `/careers`, which GEP genuinely does place in that dropdown — became
its child. The tree was a faithful reading of the markup the parser can see.

The giveaway was an inconsistency: `Contact Us` and `Careers` are siblings in
GEP's markup, both pills in the Company panel, and one became a root while the
other became a child. That is depth-inference reacting to markup noise.

---

## 3. Correcting the proposed plan before building it

An investigation was supplied proposing that `data-menu-level` / `aria-level` be
read as the depth. Measurement changed three of its claims and added a fourth
consideration it had not raised.

**The corpus is three sites, not eight.** The plan reported scanning gep,
kinsta, linear, rankuno, highradius, postman, stripe and infosys. Only gep,
kinsta and highradius have a stored homepage — the sidecar arrived in cycle
0026, and every earlier crawl kept no HTML. Five of the eight had nothing to
scan, so "0 explicit depth attributes found" was true of two other sites, not
seven.

**`aria-level` appears nowhere in the corpus, including gep.** Its handling is
implemented and tested, and it is unvalidated against a real site. Recorded as
speculative rather than presented as covered.

**The proposed mechanism does not work.** Measured on gep's homepage:

```
total <a> tags                : 609
  carrying data-menu-level    :  26   (level 0:10, 1:11, 2:5)
  of the 126 content links    :   0
```

Only section *labels* declare a depth. Using the attribute as the depth would
put 4% of anchors on an explicit scale and 96% on the nesting scale, then hand
both to `_build_tree`, which ranks entries by comparing their depths against
each other. That is incoherent, and it was the fifth breaking point.

**The de-duplication guardrail was unnecessary.** The plan required dedup by
normalised URL to stop `/careers` appearing twice. It cannot: `parse_navigation`
already de-duplicates by URL *before* the tree is built, keeping the first
occurrence. Measured after the change — 0 duplicate URLs on gep. The pre-existing
first-wins dedup is in fact the mechanism that hid the fix: the desktop menu
comes first in the document, claims `/careers` as Company's child, and discards
the hamburger's level-0 copy.

---

## 4. What landed

`ROOT_LEVEL_ATTRS` maps each attribute to the value it uses for the top level —
`0` for the vendor attributes, `1` for `aria-level`, which is 1-based by
specification. The attribute answers exactly one question: *is this a top-level
tab?* It never overrides depth generally.

`_promote_declared_roots` runs **after** the tree is built and lifts declared
nodes, with their children, to the root list.

Applied afterwards rather than during the walk because depth is a *position in a
stream* to `_build_tree`: forcing an entry to 0 mid-stream closes every open
level above it, so promoting `/careers` in place would have made the rest of the
Company dropdown its siblings instead of Company's children. Rebuilding one
branch afterwards moves one node and disturbs nothing else.

Promotion runs before `_prune_unlinked_leaves`, so a parent left childless and
linking nowhere is removed in the same pass.

---

## 5. Measured before and after

Every stored homepage, re-parsed on both sides of the change:

| | |
| :--- | ---: |
| sidecars compared | 11 |
| **node-for-node identical** | **9** (kinsta, highradius) |
| changed | 2 (both gep.com) |

gep.com, roots 5 → 11, and the node count is **unchanged at 165** — nothing
gained, nothing lost, six nodes moved from depth 1 to depth 0 with their
children following them up:

```
BEFORE: Contact Us, Company, Solutions, Industries, Knowledge Bank
AFTER : + Careers, GEP in Africa, GEP Quantum Intelligence,
          GEP E-Invoicing, Strategy, Managed Services
```

`Careers` is now a root and `Campus Connect` moved from depth 2 to depth 1
beneath it. Duplicate URLs after promotion: **0**.

---

## 6. Bugs found and fixed

### The dedup comment stated an assumption that is false on gep

```python
# The same destination appears in both a desktop and a mobile menu on
# most sites. Keeping the first occurrence keeps the desktop
# hierarchy, which is the one with real nesting.
```

True in general, and precisely wrong here: gep's desktop tabs carry no `href`,
so the copy with "real nesting" is the one that cannot express the top level.
The line is not changed — first-wins is still right for every other site — but
it no longer decides the outcome alone.

### The first fragment extracted for analysis was the wrong container

Diagnosis initially parsed "the hamburger menu" and got one root with twelve
children, which looked like evidence that the hamburger was also mis-nested. It
was not: the extractor had matched the *first* `site-map-menu`, a nested panel,
rather than the outermost. Corrected, the real finding emerged — there is no
outermost. There are 52 sibling lists. Recorded because the wrong fragment
produced a plausible, wrong conclusion.

---

## 7. Explicitly not done

- **`aria-level` is untested against a real site.** No page in the corpus uses
  it. The 1-based handling is unit-tested in both directions, and both tests
  were written from the specification rather than from an observed page.
- **Only three sites can be measured at all.** kinsta and highradius are proven
  unchanged. The other fourteen crawled sites have no stored homepage, so their
  "no change" rests on the guard — `_promote_declared_roots` returns its input
  untouched when nothing is declared — rather than on a measurement. That is an
  argument, not evidence, and it is worth saying which one it is.
- **Stored results are not re-parsed.** Existing gep jobs keep the old tree until
  someone runs `POST /jobs/{id}/reparse` with the homepage sidecar.
- **Partners is still nested under Company, and that is correct.** GEP's top bar
  shows a Partners tab, but its menu data files `/company/partners` under
  Company at no declared level. The tree now reflects what the site states; the
  discrepancy is the site's.
- **Promoted roots are appended, not inserted in document order.** Document
  order is not recoverable at that point and inventing one would be a guess.
  `Careers` therefore appears after `Knowledge Bank` rather than between
  `Knowledge Bank` and `Partners`.
- **No attempt to read the pill tabs themselves.** `data-bs-target="#careers"`
  plus a panel `id` would associate a label with a panel, which cycle 0025
  already does for fragment IDs. Not extended here: the declared level solved
  this case with far less machinery.

---

## 8. Files changed

| File | Change |
| :--- | :--- |
| `src/modules/seo/page_classifier/nav_tree_parser.py` | `ROOT_LEVEL_ATTRS`, `_declares_root`, `_promote_declared_roots`, collector capture |
| `tests/modules/seo/test_nav_tree_parser.py` | `TestDeclaredRootLevels` — 10 tests |

## 9. Follow-ups

- Reparse the stored gep.com jobs so the dashboard shows the corrected tree.
- Find a site using `aria-level` in its header and confirm the 1-based handling
  against real markup.
- Consider storing the homepage for older crawls on demand, so a corpus-wide
  before/after becomes possible for parser changes at all.
