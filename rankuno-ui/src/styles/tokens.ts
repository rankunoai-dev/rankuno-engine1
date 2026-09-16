/**
 * The slice of `design-system.css` that has to exist as a JavaScript value.
 *
 * Two places cannot use `var()`. antd's `ConfigProvider` takes colours, not
 * references, and antd's `Progress` assembles its gradient in JS. Both
 * therefore need a second copy of the palette, and a second copy drifts: the
 * previous one carried a comment asking the next reader to keep it in step by
 * hand, which is a request rather than a mechanism.
 *
 * The mechanism is `tokens.test.ts`. It parses `:root` out of
 * `design-system.css` and fails if any value here disagrees with the custom
 * property it is keyed by. The stylesheet stays authoritative; this file is a
 * mirror that cannot go stale quietly.
 *
 * Keyed by CSS custom property name on purpose. A name like `PRIMARY` would
 * have to be matched to a token by eye, and would be the same hand-maintained
 * link this module exists to remove.
 */

export const CSS_TOKENS = {
  "--bg": "#f5f5f6",
  "--panel": "#ffffff",
  "--line": "#e6e6e6",
  "--ink": "#1d2635",
  "--dim": "#595a5c",
  "--faint": "#6e6e6e",
  "--primary": "#df212a",
  "--primary-hover": "#b3151d",
  "--primary-bg": "#fdecec",
  "--danger": "#b42318",
  "--danger-bg": "#fdeaea",
  "--danger-line": "#f0b4b4",
  "--ok": "#14713f",
  "--ok-bg": "#e8f5ec",
  "--ok-line": "#a8d5b8",
  "--warn": "#8a6300",
  "--warn-bg": "#fffbe6",
  "--warn-line": "#e6cf94",
  "--progress-from": "#df212a",
  "--progress-to": "#f37f5e",
  // Not a colour, but the same problem: antd takes a font stack by value, and a
  // second copy of it drifts exactly the way the palette did. The test below
  // compares the raw declaration text, so this string is the stylesheet's.
  "--sans": '"Montserrat", "Segoe UI", system-ui, -apple-system, sans-serif',
} as const;

export type CssTokenName = keyof typeof CSS_TOKENS;

/**
 * The value of a design token, for the two call sites that cannot write
 * `var(--name)`. Everywhere else, use the custom property in CSS.
 */
export function token(name: CssTokenName): string {
  return CSS_TOKENS[name];
}
