import { MoonOutlined, SunOutlined } from "@ant-design/icons";
import { Button, Tooltip } from "antd";
import { useThemeStore } from "../../store/useThemeStore";

/**
 * The light/dark switch.
 *
 * A toggle button rather than a Switch: the control is an icon, and a Switch
 * with no visible label is read by a screen reader as an unnamed control. The
 * accessible name is fixed ("Dark theme") and `aria-pressed` carries the state,
 * which is the pattern for a two-state button; swapping the label as well would
 * announce the state twice, and backwards for some readers. The icon changes
 * with the state too, so the state is never carried by colour alone.
 */
export function ThemeToggle(): JSX.Element {
  const theme = useThemeStore((state) => state.theme);
  const toggleTheme = useThemeStore((state) => state.toggleTheme);
  const isDark = theme === "dark";

  return (
    <Tooltip title={isDark ? "Switch to light theme" : "Switch to dark theme"}>
      <Button
        className="theme-toggle"
        size="small"
        type="text"
        aria-label="Dark theme"
        aria-pressed={isDark}
        icon={isDark ? <MoonOutlined /> : <SunOutlined />}
        onClick={toggleTheme}
      />
    </Tooltip>
  );
}
