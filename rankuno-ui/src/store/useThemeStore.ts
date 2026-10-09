import { create } from "zustand";

/**
 * Every theme, as a value and not a type alone — the same shape as `RAIL_VIEWS`
 * in `useUiStore`, for the same reason: a string out of `localStorage` has to
 * be checked against the real set, and a hand-kept second list goes stale.
 */
export const THEMES = ["light", "dark"] as const;

export type Theme = (typeof THEMES)[number];

/**
 * Same prefix and shape as `useUiStore`'s `rankuno.ui`. The inline script in
 * `index.html` reads this key before first paint and must agree with it; a
 * test pins that.
 */
export const THEME_STORAGE_KEY = "rankuno.theme";

/** What is kept in `localStorage`: the operator's choice, nothing else. */
interface StoredTheme {
  theme: Theme;
}

function isTheme(value: unknown): value is Theme {
  return typeof value === "string" && (THEMES as readonly string[]).includes(value);
}

/** The stored choice, or `null` when there is none or it cannot be trusted. */
function readStoredTheme(): Theme | null {
  try {
    const raw = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredTheme> | null;
    return isTheme(parsed?.theme) ? parsed.theme : null;
  } catch {
    // Storage disabled, or the value is not JSON. Either way there is no choice.
    return null;
  }
}

/** The OS preference, `light` when the browser cannot say. */
function systemTheme(): Theme {
  try {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  } catch {
    return "light";
  }
}

/**
 * The theme to open with: the operator's earlier choice if there is one,
 * otherwise whatever the OS asks for. Exported so the rule can be tested
 * without re-importing the store.
 */
export function resolveInitialTheme(): Theme {
  return readStoredTheme() ?? systemTheme();
}

function writeStoredTheme(theme: Theme): void {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, JSON.stringify({ theme } satisfies StoredTheme));
  } catch {
    // Private mode or a full quota. The theme still applies for this session;
    // it only fails to survive a reload.
  }
}

/** Reflect the theme on <html>, which is where every token selector looks. */
function applyTheme(theme: Theme): void {
  document.documentElement.setAttribute("data-theme", theme);
}

interface ThemeState {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
}

/*
 * Light or dark, for the whole app.
 *
 * Separate from `useUiStore` on purpose: that store is rail navigation and is
 * subscribed to by most of the shell, and a theme flip should not be able to
 * re-render anything that only cares which view is open.
 *
 * Nothing is written to storage until the operator chooses. A first visit
 * follows the OS, and a stored value would turn that default into a decision
 * the operator never made — an OS switched to dark next month would be ignored.
 * The subscription below is therefore the only writer, and it fires on change,
 * not on load.
 */
export const useThemeStore = create<ThemeState>((set, get) => ({
  theme: resolveInitialTheme(),
  setTheme: (theme) => set({ theme }),
  toggleTheme: () => set({ theme: get().theme === "dark" ? "light" : "dark" }),
}));

// Idempotent with the pre-paint script, and the only thing that sets the
// attribute where that script did not run (tests, or a blocked inline script).
applyTheme(useThemeStore.getState().theme);

useThemeStore.subscribe((state, previous) => {
  if (state.theme === previous.theme) return;
  applyTheme(state.theme);
  writeStoredTheme(state.theme);
});
