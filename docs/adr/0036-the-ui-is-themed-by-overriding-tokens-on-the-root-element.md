# ADR 0036: The UI is themed by overriding the same custom properties on the root element

- **Status**: Accepted
- **Date**: 2026-10-09
- **Deciders**: AI Lead, Lead AI Systems Engineer (user request: "implement a dark mode glassmorphism UI")
- **Related**: [build-log 0151](../build-log/0151-dark-mode-glassmorphism-theme.md)

---

## Context

`rankuno-ui` styled itself with custom properties in `design-system.css`, but several
stylesheets (`login.css`, `jobs.css`, `screaming-frog.css`, `audit.css`, `tree-overlay.css`)
carried hard-coded colours, and antd components took their colours from a `ConfigProvider` in
`main.tsx`. A dark theme had to reach all three without forking any component, and the light
theme (what users have today) had to stay as it was. The tree views hold up to 20,000 nodes,
so a visual effect that costs per element could not be applied freely.

## Decision

1. **Theme by additive token override.** A `:root[data-theme="dark"]` block reassigns the
   same custom properties the light theme defines. Components never name a theme. The
   attribute is set on `<html>` by `src/store/useThemeStore.ts` (`light` / `dark`).
2. **A neutral glass seam in `:root`.** `--glass-bg`, `--glass-filter`, `--glass-border`,
   `--app-backdrop` and related tokens resolve, in light, to the value each surface already
   had (`--glass-filter: none`, `--glass-bg: var(--panel)`, `--glass-border: var(--line)`).
   Literals that used to be hard-coded became tokens whose light value is that literal
   (`--node-bg`, `--stage-bg`, `--stage-dot`, `--wire`, `--hits-shadow`, `--card-shadow`,
   `--row-divider`, `--line-soft`, `--on-fill`, `--ok-fill`, `--glass-mask-filter`). "Light is
   unchanged" therefore rests on the seam resolving to the old literals.
3. **A TypeScript mirror held to the CSS by test.** `styles/tokens.ts` gains `CSS_TOKENS_DARK`,
   typed `Record<CssTokenName, string>`, and `token(name, theme = "light")`. `tokens.test.ts`
   holds the mirror to both CSS blocks. `ThemedConfigProvider.tsx` takes antd's values from
   the mirror (`darkAlgorithm` / `defaultAlgorithm`), so antd and CSS cannot drift apart.
4. **Blur only on panels and overlays.** `backdrop-filter` is applied to the header, rail, KPI
   cards, the two `.card` panels, the notice-restore strip, the search-hits dropdown, the login
   card, the Screaming Frog launcher and dispatch cards, the full-screen tree panels, and antd
   overlays and masks. It is never applied to tree rows, table rows, `.au-card` (audit cards
   repeat down a list; translucent only) or focus-graph nodes.
5. **Print is forced light.** `@media print` re-asserts the light value of every token
   `report.css` uses, so PDF and print output stay light whatever the screen theme.
6. **A pre-paint inline script.** `index.html` sets `data-theme` before fonts and the bundle
   load, so a dark user does not see a light flash. It duplicates the store's resolution rule
   (stored `{theme}` under `rankuno.theme`, else `prefers-color-scheme`, light on any failure).
   The duplication is deliberate, because the script must run before the bundle; the rule is
   pinned by `prepaintScript.test.ts`.
7. **Default is follow the OS on first visit.** Nothing is written to storage until the user
   toggles. A wrong-shape stored value is ignored. Storage and `matchMedia` access are in
   try/catch.
8. **Fallbacks.** `@supports not (backdrop-filter / -webkit-backdrop-filter)` gives a solid
   `--panel` and an opaque rail. `prefers-reduced-transparency` gives solid surfaces and no
   blur. `prefers-contrast: more` gives solid surfaces, stronger borders and brighter text.
9. **Filled buttons and badges use fill tokens.** White on the dark `--ok` measured 1.85:1, so
   `--ok-fill` (#177a44, 5.38:1) and `--danger-fill` (#c93a30, 5.08:1) carry filled states.

## Alternatives considered

- **antd-only theming.** Would leave every custom stylesheet light. Rejected.
- **A CSS-in-JS or theming dependency.** A second styling system beside the CSS files, a new
  dependency, and a rewrite of every stylesheet. Rejected.
- **A separate dark stylesheet.** Duplicates every rule and drifts from the light one. Rejected
  in favour of overriding the variables the rules already use.

## Consequences

- A component restyled with a hard-coded colour silently opts out of the dark theme. The
  convention is to add a token, with its light value equal to the old literal.
- The glass effect on a dark gradient is subtle; retuning backdrop strength is open.
- An OS-dark user previously saw the GSC integrated report dark inside a light app. With
  `data-theme="light"` now set explicitly, it is light. This is the only known light-theme
  behaviour change besides the new header button.

## Known limitations

- Modals, drawers, popconfirms, login, report print preview, the full-screen tree, hover and
  focus states and narrow widths were not viewed; coverage there is by CSS only.
- No pixel diff of the light theme was taken.
- Contrast was computed for text on opaque `--panel`, worst-case glass over one bright
  backdrop (#46304f), chips and fills. Translucent header and rail text across every gradient
  position and antd-derived colours (disabled, placeholder, Alert text) were not computed.
- Level chips (white on `--l1f`) are 3.47:1 in both themes. Pre-existing and unchanged.
- `src/constants/colors.ts` is generated and was not tokenised.
