# Cycle 0151: A dark glassmorphism theme for the whole UI, light left as it was

- **Date**: 2026-10-09
- **Scope**: UI_CHANGE. A light/dark theme (dark is translucent glass) for all of `rankuno-ui`, via a token override on `<html data-theme>`. Request: "implement a dark mode glassmorphism UI".
- **Commit**: uncommitted at time of writing
- **Quality gate**: UI only. `tsc --noEmit` exit 0; full vitest `Test Files 57 passed (57), Tests 759 passed (759)`. Implementer's run, not re-executed by the scribe. Python gate not run (no Python changed).

Numbering note: 0150 is on disk, so this is 0151.

## 1. Gate results

Implementer's runs, from `rankuno-ui`:

```
tsc --noEmit                      exit 0
vitest run src/styles src/store src/components/layout src/ThemedConfigProvider.test.tsx
  Test Files  17 passed (17)
  Tests       239 passed (239)
vitest run (full)
  Test Files  57 passed (57)
  Tests       759 passed (759)
npm run contract                  UI contract is up to date.
npm run build                     built in 14.23s (only the existing >2000 kB chunk warning)
drift_check (implementer)         PASSED: no drift detected across 248 markdown files.
```

759 is 698 original plus 61 new. The `ScreamingFrogView` flake did not occur. In the built CSS
`backdrop-filter: var(--glass-filter)` appears 28 times plus 2 mask uses; the built
`index.html` contains the pre-paint script. Scribe's own drift_check output is in section 7.

## 2. What landed

All under `rankuno-ui/`. No Python, adapter, generated-contract or `dist/` edits.

New:

- `src/store/useThemeStore.ts`: `light` / `dark`. Key `rankuno.theme`, stored as `{theme}` like `rankuno.ui`. First visit follows `prefers-color-scheme`; nothing is written until the user toggles. Storage and `matchMedia` are try/catch'd; a wrong-shape stored value is ignored. Sets `data-theme` on `<html>`.
- `src/ThemedConfigProvider.tsx`: the antd `ConfigProvider` moved out of `main.tsx`; `darkAlgorithm` / `defaultAlgorithm`, values from the token mirror per theme.
- `src/components/layout/ThemeToggle.tsx`: antd text Button, `aria-label` "Dark theme", `aria-pressed`, sun/moon icon swap so state is not colour-only.
- `src/styles/glass.css`: dark only. Glass for antd modal, drawer, popover, select and dropdown overlays and masks; transparent table body; faint header lift; filled danger buttons use `--danger-fill`.
- Tests: `useThemeStore.test.ts`, `prepaintScript.test.ts`, `ThemeToggle.test.tsx`, `ThemedConfigProvider.test.tsx`.

Modified:

- `index.html`: inline pre-paint script before fonts and bundle, own try/catch.
- `main.tsx`, `App.tsx` (imports `glass.css`; loading screen uses `--app-backdrop`).
- `index.css`: `color-scheme: dark` in dark; `html`/`body`/`#root` use `--app-backdrop`.
- `styles/design-system.css`: seam tokens in `:root`, the dark block, fallbacks, print override, toggle placement, glass on panels.
- `styles/tokens.ts` and `tokens.test.ts`: `CSS_TOKENS_DARK`, `token(name, theme = "light")`. The existing `CrawlJobsView` call is unchanged.
- `HeaderBar.tsx` and `HeaderBar.test.tsx`: the toggle on all three header variants (engine, Launch, Screaming Frog).
- `login.css`, `jobs.css`, `screaming-frog.css`, `audit.css`, `tree-overlay.css`: hard-coded colours replaced by tokens; glass added.

## 3. Design decisions

Recorded in [ADR 0036](../adr/0036-the-ui-is-themed-by-overriding-tokens-on-the-root-element.md).

- **Additive override, not a second stylesheet.** `:root[data-theme="dark"]` reassigns the same custom properties, so no component names a theme.
- **The seam resolves to the old values in light.** `--glass-filter: none`, `--glass-bg: var(--panel)`, `--glass-border: var(--line)`. New literal tokens (`--node-bg`, `--stage-bg`, `--stage-dot`, `--wire`, `--hits-shadow`, `--card-shadow`, `--row-divider`, `--line-soft`, `--on-fill`, `--ok-fill`, `--glass-mask-filter`) have as light value the literal they replaced.
- **Dark look.** Translucent glass, 1px translucent borders, inner highlight plus drop shadow, `blur(18px) saturate(150%)`, a layered red/indigo/teal radial backdrop on `#0b101c`. Brand red `--primary` unchanged.
- **Blur is budgeted.** `backdrop-filter` only on header, rail, KPI cards, the two `.card` panels, notice-restore strip, search-hits dropdown, login card, Screaming Frog launcher and dispatch cards, full-screen tree panels, antd overlays and masks. Never on tree rows, table rows, `.au-card` (repeats down a list; translucent only) or focus-graph nodes (20,000-node tree).
- **Fallbacks.** `@supports not (backdrop-filter / -webkit-backdrop-filter)`: solid `--panel`, opaque rail. `prefers-reduced-transparency`: solid, no blur. `prefers-contrast: more`: solid, stronger borders, brighter text. `@media print` forces the light tokens.
- **Pre-paint script duplicates the store's rule** so there is no light flash; `prepaintScript.test.ts` pins the two together.
- **Default is follow-OS on first visit.** A user with an OS dark preference sees dark immediately, without clicking.
- Alternatives (antd-only, a CSS-in-JS dependency, a separate dark stylesheet) are in the ADR.

## 4. Bugs found and fixed

- **White on the dark `--ok` was 1.85:1.** It would have broken the running-crawl rail badge. `--ok-fill` (#177a44) was introduced for filled states: white on it is 5.38:1. Likewise white on `--danger-fill` #c93a30 is 5.08:1, and white on `--primary` 4.79:1.
- **Hard-coded colours in five stylesheets** (`login.css`, `jobs.css`, `screaming-frog.css`, `audit.css`, `tree-overlay.css`) would have stayed light inside a dark app. Replaced by tokens.

Contrast, computed by the implementer with a WCAG formula in node:

| Case | --ink | --dim | --faint | --text-muted | --primary-ink | --ok | --warn | --danger |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Dark text on opaque `--panel` | 14.50 | 8.71 | 6.53 | 6.68 | 7.59 | 9.26 | 9.60 | 7.52 |
| Glass at 0.58 alpha over bright `#46304f` | 12.25 | 7.37 | 5.52 | 5.65 | 6.41 | n/c | n/c | 6.36 |

Chips (text on own tinted background): ok 7.72, warn 8.02, danger 6.81, primary 7.13; l0 / l1 / l2 / l3 / oth 8.64 / 7.20 / 7.99 / 7.47 / 6.75. Status chips keep their text labels, so they are not colour-only. (n/c = not computed.)

## 5. Corrections

- **A behaviour change in light.** An OS-dark user previously got the GSC integrated report in dark inside a light app (its `GscIntegratedReport.module.css` follows `prefers-color-scheme`). With `data-theme="light"` now set explicitly, it is light, matching the rest of the app. This is the only known light-theme behaviour change besides the new header button.
- **"Light is unchanged" is a claim from reading the diff, not a measurement.** See section 6.
- No earlier entry was found false by this cycle.

## 6. Explicitly not done

Not viewed (CSS-only coverage):

- Modals and drawers, popconfirms, login, report print preview, the full-screen tree, hover and focus states, and narrow widths. Print is an `@media print` override re-asserting light values for every token `report.css` uses; it was never actually printed.

Not verified:

- **No pixel diff of the light theme.** "Light is unchanged" rests on the token seam resolving to the prior literals as read in the diff. Only the Launch screen was viewed in light (it looked normal, with the new toggle at top-right).
- Viewed in dark, via headless Chrome `--screenshot` of a scratch copy of `dist/` served by a temporary `python http.server` (ports 8765/8766, stopped afterwards). The engine was down, so the app ran in fixture mode: Launch, Visualizer (header, rail, KPI strip, tree, focus graph, search), Crawl jobs, Audit, Screaming Frog, GSC accounts (error state only).
- **Not investigated:** the jobs screenshot showed a fixture-mode banner, "Failed to fetch dynamically imported module .../synthetic-500...". The implementer guesses the scratch server or virtual time; that is unverified.
- **Contrast not computed, not claimed:** translucent header and rail text across every gradient position; antd-derived colours (disabled, placeholder, Alert text).
- **Known sub-AA, pre-existing, unchanged:** level chips, white on `--l1f`, 3.47:1 in both themes.

Left alone:

- `src/constants/colors.ts` (19 literals) is not tokenised. It is a generated "DO NOT EDIT" file from `scripts/export_ui_contract.py`, and grep found no importer in `src/`.
- Design-system leftovers: `.src-menu`, `.src-breadcrumb`, `.src-mixed`, `.src-none`, level-chip text colours on fills (`.p0`/`.p2`/`.p3`/`.ln0 .tab`), and the `--stream-*` console colours (already dark).
- `GscIntegratedReport.module.css` keeps its own dark values; its old `prefers-color-scheme` branch is now redundant. Decision pending.
- `GscIntegratedReport.example.tsx` inline hexes untouched.
- Pre-existing undefined variables `--text`, `--hover-light`, `--focus` in the KPI toggle, not touched.
- The glass effect is subtle on a dark gradient; retuning backdrop strength is an optional follow-up.

## 7. Files changed

```
NEW  rankuno-ui/src/store/useThemeStore.ts            (+ useThemeStore.test.ts, prepaintScript.test.ts)
NEW  rankuno-ui/src/ThemedConfigProvider.tsx          (+ .test.tsx)
NEW  rankuno-ui/src/components/layout/ThemeToggle.tsx (+ .test.tsx)
NEW  rankuno-ui/src/styles/glass.css
MOD  rankuno-ui/index.html, src/main.tsx, src/App.tsx, src/index.css
MOD  rankuno-ui/src/styles/design-system.css, tokens.ts, tokens.test.ts
MOD  rankuno-ui/src/components/layout/HeaderBar.tsx, HeaderBar.test.tsx
MOD  rankuno-ui/src/components/{auth/login,jobs/jobs,screaming-frog/screaming-frog,audit/audit,tree/tree-overlay}.css
NEW  docs/adr/0036-the-ui-is-themed-by-overriding-tokens-on-the-root-element.md
NEW  docs/build-log/0151-dark-mode-glassmorphism-theme.md
MOD  docs/build-log/README.md, docs/ARCHITECTURE.md, README.md
```

Drift check, scribe's run:

```
Running Architecture & Documentation Drift Audit...

--- Drift Audit Results ---
PASSED: no drift detected across 251 markdown files.
  - all relative links resolve
  - all domain modules documented
  - all skill directories populated
```

## 8. Follow-ups

1. View modals, drawers, popconfirms, login, the full-screen tree, hover/focus and narrow widths in dark.
2. Take a light-theme screenshot comparison against the previous build to turn "unchanged" from a reading into a measurement.
3. Decide whether to remove the redundant `prefers-color-scheme` branch in `GscIntegratedReport.module.css`.
4. Investigate the fixture-mode "Failed to fetch dynamically imported module" banner.
5. Optionally retune backdrop strength.
