import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { useThemeStore } from "../../store/useThemeStore";
import { ThemeToggle } from "./ThemeToggle";

beforeEach(() => {
  useThemeStore.setState({ theme: "light" });
});

describe("ThemeToggle", () => {
  it("is a named button whose pressed state is the theme", () => {
    render(<ThemeToggle />);
    const button = screen.getByRole("button", { name: "Dark theme" });
    expect(button).toHaveAttribute("aria-pressed", "false");
  });

  it("switches the store and the pressed state on click", () => {
    render(<ThemeToggle />);
    const button = screen.getByRole("button", { name: "Dark theme" });

    fireEvent.click(button);
    expect(useThemeStore.getState().theme).toBe("dark");
    expect(button).toHaveAttribute("aria-pressed", "true");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");

    fireEvent.click(button);
    expect(useThemeStore.getState().theme).toBe("light");
    expect(button).toHaveAttribute("aria-pressed", "false");
  });

  it("does not carry its state by colour alone: the icon changes", () => {
    render(<ThemeToggle />);
    const button = screen.getByRole("button", { name: "Dark theme" });
    expect(button.querySelector(".anticon-sun")).not.toBeNull();
    fireEvent.click(button);
    expect(button.querySelector(".anticon-moon")).not.toBeNull();
  });

  it("is a real button, focusable and enabled", () => {
    render(<ThemeToggle />);
    const button = screen.getByRole("button", { name: "Dark theme" });
    button.focus();
    expect(button).toHaveFocus();
    expect(button).not.toBeDisabled();
    expect(button.tagName).toBe("BUTTON");
  });
});
