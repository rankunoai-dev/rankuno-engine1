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
  "--bg": "#f5f6f8",
  "--panel": "#ffffff",
  "--line": "#e6e9ef",
  "--ink": "#1d2635",
  "--dim": "#5c6b83",
  "--faint": "#98a4b8",
  "--blue": "#1677ff",
  "--blue-bg": "#e6f4ff",
  "--progress-from": "#00f2fe",
  "--progress-to": "#4facfe",
} as const;

export type CssTokenName = keyof typeof CSS_TOKENS;

/**
 * The value of a design token, for the two call sites that cannot write
 * `var(--name)`. Everywhere else, use the custom property in CSS.
 */
export function token(name: CssTokenName): string {
  return CSS_TOKENS[name];
}
