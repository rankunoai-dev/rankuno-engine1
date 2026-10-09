import { render } from "@testing-library/react";
import { theme as antTheme } from "antd";
import { beforeEach, describe, expect, it } from "vitest";
import { ThemedConfigProvider } from "./ThemedConfigProvider";
import { useThemeStore } from "./store/useThemeStore";
import { CSS_TOKENS, CSS_TOKENS_DARK } from "./styles/tokens";

/**
 * The antd algorithm follows the theme store, and the values it is given are
 * the mirrored token sets rather than antd's own.
 */

interface Probe {
  id: number | string;
  bgContainer: string;
  text: string;
  /** Not seeded by us, so it only differs if the algorithm does. */
  fillQuaternary: string;
}

function probeUnder(): Probe {
  const seen: { value: Probe | null } = { value: null };
  function Child(): null {
    const { theme, token } = antTheme.useToken();
    seen.value = {
      id: theme.id,
      bgContainer: token.colorBgContainer,
      text: token.colorText,
      fillQuaternary: token.colorFillQuaternary,
    };
    return null;
  }
  const { unmount } = render(
    <ThemedConfigProvider>
      <Child />
    </ThemedConfigProvider>,
  );
  // Unmounted so the next probe is the only subscriber to the store.
  unmount();
  if (!seen.value) throw new Error("probe did not render");
  return seen.value;
}

beforeEach(() => {
  useThemeStore.setState({ theme: "light" });
});

describe("ThemedConfigProvider", () => {
  it("gives antd the light palette in light", () => {
    const light = probeUnder();
    expect(light.bgContainer).toBe(CSS_TOKENS["--panel"]);
    expect(light.text).toBe(CSS_TOKENS["--ink"]);
  });

  it("gives antd the dark palette and the dark algorithm in dark", () => {
    const light = probeUnder();
    useThemeStore.setState({ theme: "dark" });
    const dark = probeUnder();

    expect(dark.bgContainer).toBe(CSS_TOKENS_DARK["--panel"]);
    expect(dark.text).toBe(CSS_TOKENS_DARK["--ink"]);
    expect(dark.id).not.toBe(light.id);
    // A derived colour: only the algorithm can have moved it.
    expect(dark.fillQuaternary).not.toBe(light.fillQuaternary);
  });
});
