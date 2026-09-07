# Cycle 0071: Clickable page links in the tree

- **Date**: 2026-09-07
- **Scope**: Every crawled-page row in the virtualised tree renders its label
  as a real link that opens the page in a new tab; path-segment rows do not.
- **Commit**: uncommitted at time of writing
- **Quality gate**: UI `211 passed` / 20 files, `tsc` clean, `vite build` clean.
  Python gate not run (no Python files changed).

---

## 1. Gate results

Run from `rankuno-ui/` with node prepended to `PATH`.

```
=== npx vitest run src/components/tree/VirtualizedTree.test.tsx ===
 Test Files  1 passed (1)
      Tests  17 passed (17)
   Duration  2.06s
EXIT=0

=== npm test ===
 Test Files  20 passed (20)
      Tests  211 passed (211)
   Duration  20.02s
EXIT=0

=== npm run typecheck ===
> tsc --noEmit
EXIT=0

=== npm run build ===
dist/assets/index-CIjvGhjV.js             1,180.46 kB | gzip: 371.69 kB
dist/assets/synthetic-20000-CWU9lvCu.js  16,018.27 kB | gzip: 472.00 kB
(!) Some chunks are larger than 2000 kB after minification (pre-existing warning)
built in 16.91s
EXIT=0
```

`scripts/verify.ps1` was not run: nothing under `src/` or `tests/` changed.
`npm run contract` was not run: no contract field changed.

---

## 2. What landed

The request was "i want all these links clickable and opens into browser",
against a screenshot of the tree view with `L0`/`L3` rows and slug labels. The
labels looked like links and were not; a row click selected the node and
opened the inspector, which is not the same thing as reading the page.

`VirtualizedTree.tsx` now renders the label of a page row (`profile !== null`)
as `<a href={profile.url} target="_blank" rel="noreferrer noopener">`. A
synthetic path-segment row (`profile === null`, e.g. `/docs/` when the crawl
holds `/docs/guides/a/` but never fetched `/docs/` itself) keeps the plain
`<span>`; a dead link would be worse than none. Row selection, the twisty,
shift-click and the whole-branch control are unchanged.

`design-system.css` gains one `.tlink` rule beside `.tlbl`: the anchor inherits
the row's text colour and shows an underline in `--l1f` only on hover or
`:focus-visible`. Twenty thousand underlined blue rows would have turned the
tree into a wall of links and drowned the level chips that are each row's
primary identity.

The `title` attribute (`Open <url> in a new tab`) carries the affordance; there
is no external-link icon.

### Workflow change

This was the first cycle run through the prompt-generator flow added to
`CLAUDE.md` section 10 in the same working session: `prompt-generator` turned
the request into a scoped brief, `ui-engineer` implemented against it, and
`docs-scribe` wrote this entry. The roster and its scaffolding landed
uncommitted alongside the UI change:

- `.claude/agents/` — 11 role agents plus `prompt-generator`
- `.claude/skills/do/SKILL.md` — the `/do` sequence
- `.claude/hooks/prompt_router.py` — registered as a `UserPromptSubmit` hook
- `docs/AGENT_ROSTER.md` and `docs/standards/AGENT_HANDOFF_PROTOCOL.md`
- `CLAUDE.md` section 10
- `.gitignore` narrowed so `.claude/` agents, skills and hooks are tracked
  while `settings*.json` and the scheduled-tasks lock stay ignored

Custom agents are not visible to a Claude Code session that was already open
when their definition files were written. This cycle therefore ran on
general-purpose agents that were handed the definition files as instructions;
the next new session is the first that will pick the roster up by name.

---

## 3. Design decisions

### 3.1 The row stops being a `<button>`

The row was `<button className="vrow">`. An `<a>` inside a `<button>` is
invalid HTML, and browsers repair it by splitting the button around the anchor,
which breaks the row in ways that vary by engine. The row is now
`<div role="button" tabIndex={0}>` with `onClick -> setFocus` and a hand-wired
`onKeyDown` for Enter and Space — the two things a real button gave for free.

Alternatives considered: keep the button and open the page from the inspector
(does not answer the request — the user pointed at the labels); make the whole
row a link (loses selection as a distinct intention, and shift-click would
have to fight the browser's own link handling).

Every dependent of the row being a button was checked before the change:
the `.rk-dash button` reset (font, cursor, background, border — all of which
`.vrow` already sets), the focus ring from the generic `.rk-dash :focus-visible`
(which matches the `div` just as well), and no test or CSS selector targets
`button.vrow`. Two stale comments in the file that said "the row itself is a
button" were corrected to "the row carries the button role".

### 3.2 A click on the link does not move the selection

The anchor's `onClick` calls `stopPropagation`, so opening a page does not also
select its row. Reading a page and pointing at a row are different intentions
— the same split the twisty already makes between expanding and selecting.

### 3.3 Enter on the link navigates

The row's `onKeyDown` returns early unless `event.target === event.currentTarget`.
Without that guard Enter on the focused anchor would bubble to the row, be
`preventDefault`-ed, and select the row instead of following the link.

Keyboard result: Tab reaches the row and then the link; Enter or Space on the
row selects; Enter on the link opens the page.

### 3.4 Virtualisation untouched

Same per-row element count (the label is one element either way), so the
windowed DOM budget and the footer counts are unchanged.

---

## 4. Bugs found and fixed

None in the shipped code. Two things were wrong on the way, one in the brief
and one in a test:

* **The brief pointed at the wrong type.** It named `lib/tree.ts` / `TreeNode`
  as the row's data. The row actually renders `DashNode` from
  `src/lib/dashboardModel.ts`. Both carry the same `profile` field, so no extra
  change was needed, but a reader following the brief would have looked in
  the wrong file.
* **A test asserted the wrong baseline.** The first draft of "does not move the
  selection when the link is clicked" asserted `focus === null` after the
  click and failed with `0`. `useDashboardStore.setModel` seeds `focus` to
  `roots[0]` (`src/store/useDashboardStore.ts:211`), so `null` was never the
  starting state. The assertion became "focus unchanged and not equal to the
  page's own index". The code was right; the test was corrected.

---

## 5. Corrections

None to earlier entries.

---

## 6. Explicitly not done

- **No link on section or bucket headings, or on synthetic segments.** By
  design: there is no page behind them. A heading that opened a directory
  listing, or a 404, would teach the user not to trust the links.
- **No external-link icon.** The `title` tooltip carries the affordance. An
  icon on every one of 20,000 rows costs width in the one column the label
  needs.
- **Python gate not run.** No file under `src/` or `tests/` changed.
- **`npm run contract` not run.** No contract field changed; nothing in
  `src/` (Python), the API contract, or `lib/tree.ts` was touched.
- **No screenshot.** As in cycle 0070: no browser driver is installed in this
  project, so the hover and focus states are asserted by class and attribute,
  not seen.
- **`README.md` and `docs/ARCHITECTURE.md` unchanged.** Neither describes tree-row
  behaviour; nothing in them became stale. Neither links to
  `docs/AGENT_ROSTER.md` yet either — see §8.

---

## 7. Files changed

```
rankuno-ui/src/components/tree/VirtualizedTree.tsx       row is div[role=button]; label is <a> on page rows; 2 comments corrected
rankuno-ui/src/styles/design-system.css                  .tlink beside .tlbl
rankuno-ui/src/components/tree/VirtualizedTree.test.tsx  describe("page links"), +5 tests
```

Nothing in `src/` (Python), the API contract, or `rankuno-ui/src/lib/tree.ts`
was touched.

Landed in the same session, outside the UI change (see §2, "Workflow change"):
`.claude/agents/*.md`, `.claude/skills/do/SKILL.md`,
`.claude/hooks/prompt_router.py`, `docs/AGENT_ROSTER.md`,
`docs/standards/AGENT_HANDOFF_PROTOCOL.md`, `CLAUDE.md` section 10, `.gitignore`.

---

## 8. Follow-ups

1. **Link `docs/AGENT_ROSTER.md` from `README.md` and `docs/ARCHITECTURE.md`.**
   `ARCHITECTURE.md` section 4 indexes `skills/`; the `.claude/agents/` roster
   is the same kind of surface and is currently reachable only from
   `CLAUDE.md` section 10.
2. **Run a cycle under a fresh session** so the roster is exercised by agent
   name rather than by pasting definition files into general-purpose agents.
3. **The button-reset regression test** from cycle 0070 §7 is still open; this
   cycle added one more element whose styling depends on being outside that
   reset.
