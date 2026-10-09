import { ConfigProvider, theme as antTheme } from "antd";
import { useMemo, type ReactNode } from "react";
import { useThemeStore } from "./store/useThemeStore";
import { token, type ThemeName } from "./styles/tokens";

/**
 * antd is themed to match `design-system.css`, not to its own taste.
 *
 * `ConfigProvider` takes values rather than `var()` references, so the palette
 * is spelled out a second time. `styles/tokens.ts` is that mirror and
 * `styles/tokens.test.ts` parses `design-system.css` and fails if a value stops
 * matching the token it is named by, for both themes. The stylesheet remains the
 * one place a colour is chosen.
 *
 * The algorithm follows the theme: `darkAlgorithm` in dark, `defaultAlgorithm`
 * in light. antd once ran `darkAlgorithm` over a light palette and painted dark
 * islands inside a white dashboard; the algorithm and the palette are now
 * switched by the same store, so they cannot disagree.
 */
function buildTheme(name: ThemeName) {
  const t = (key: Parameters<typeof token>[0]): string => token(key, name);
  return {
    algorithm: name === "dark" ? antTheme.darkAlgorithm : antTheme.defaultAlgorithm,
    token: {
      colorPrimary: t("--primary"),
      // antd derives its own hover from `colorPrimary` by lightening it, which on
      // a fill carrying white text moves the wrong way: #df212a is 4.79:1 under
      // white and anything lighter drops below AA. Both states are pinned to
      // darker shades instead.
      colorPrimaryHover: t("--primary-hover"),
      colorPrimaryActive: t("--primary-hover"),
      colorInfo: t("--primary"),
      // Seeds, and antd generates a ten-step ramp from each. The seeds have to
      // be dark enough to pass as text (light enough, in dark), which makes the
      // generated ramp muddy at the pale end, so the three surfaces antd takes
      // off that end are pinned instead of derived.
      colorError: t("--danger"),
      colorErrorBg: t("--danger-bg"),
      colorErrorBorder: t("--danger-line"),
      colorSuccess: t("--ok"),
      colorSuccessBg: t("--ok-bg"),
      colorSuccessBorder: t("--ok-line"),
      colorWarning: t("--warn"),
      colorWarningBg: t("--warn-bg"),
      colorWarningBorder: t("--warn-line"),
      colorBgBase: t("--bg"),
      colorBgContainer: t("--panel"),
      colorBgElevated: t("--panel"),
      colorBorder: t("--line"),
      colorText: t("--ink"),
      colorTextSecondary: t("--dim"),
      colorTextTertiary: t("--faint"),
      borderRadius: 4,
      fontFamily: t("--sans"),
      fontSize: 13,
    },
    components: {
      Tree: { nodeSelectedBg: t("--primary-bg"), nodeHoverBg: t("--bg") },
      Drawer: { colorBgElevated: t("--panel") },
    },
  };
}

export function ThemedConfigProvider({ children }: { children: ReactNode }): JSX.Element {
  const themeName = useThemeStore((state) => state.theme);
  const config = useMemo(() => buildTheme(themeName), [themeName]);
  return <ConfigProvider theme={config}>{children}</ConfigProvider>;
}
