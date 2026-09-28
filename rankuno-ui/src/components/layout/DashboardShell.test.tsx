import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "../../store/useAuthStore";
import { useCrawlStore } from "../../store/useCrawlStore";
import { useUiStore } from "../../store/useUiStore";
import { DashboardShell } from "./DashboardShell";

/**
 * The route from the Launch chooser into the engine.
 *
 * `LaunchView` and `NavigationRail` are tested on their own; this file exists
 * because the failure it guards against is a wiring one and lives nowhere
 * else. The chooser now shows no engine tabs, so the *only* way into the
 * engine is a control on the engine card — and the shell is what decides
 * whether that control also opens the crawl form.
 *
 * Fixture mode is the state under test throughout: `adapter: null` means no
 * `startJob` and no `previewDispatch`, which is exactly when both primary
 * buttons are disabled and a wrong answer here leaves the application with no
 * way into it at all.
 */

/** What the rail offers, in order — the rail only, not the whole page. */
function railItems(): (string | undefined)[] {
  const rail = screen.getByRole("navigation", { name: "Primary" });
  return Array.from(rail.querySelectorAll("button"), (button) => button.textContent?.trim());
}

describe("DashboardShell — entering the engine from Launch", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useUiStore.setState({ view: "launch", lastEngineView: "visualizer" });
    useCrawlStore.setState({
      adapter: null,
      result: null,
      jobs: [],
      activeJobId: null,
      liveJobs: {},
      status: "idle",
      error: null,
    });
    useAuthStore.setState({
      token: null,
      orgId: null,
      expiresAt: null,
      loggingIn: false,
      loginError: null,
    });
  });

  it("shows the chooser with no engine destinations beside it", () => {
    render(<DashboardShell />);

    expect(railItems()).toEqual(["Launch"]);
    expect(screen.getByRole("heading", { name: /rankuno engine crawl/i })).toBeInTheDocument();
  });

  it("opens the engine without opening the crawl form", () => {
    render(<DashboardShell />);

    fireEvent.click(screen.getByRole("button", { name: /open the engine/i }));

    // In the engine, on the view last used — and no form in the way. The form
    // used to open on arrival, so "look at the crawl that already finished"
    // meant opening it and cancelling.
    expect(useUiStore.getState().view).toBe("visualizer");
    expect(screen.queryByText("Start a live crawl")).not.toBeInTheDocument();
    expect(railItems()).toEqual([
      "Launch",
      "Visualizer",
      "Crawl jobs",
      "Dashboard",
      "Audit",
      "GSC Accounts",
    ]);
  });

  it("gives the chooser a working way in even when no crawl can be started", () => {
    /* The trap: with no engine reachable both primary buttons are disabled.
       A Launch-only rail plus two dead buttons is an application with no
       entrance. Reading stored results asks nothing of the engine. */
    render(<DashboardShell />);

    expect(screen.getByRole("button", { name: /start an engine crawl/i })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: /set up a screaming frog crawl/i }),
    ).toBeDisabled();

    const open = screen.getByRole("button", { name: /open the engine/i });
    expect(open).toBeEnabled();
    fireEvent.click(open);

    expect(useUiStore.getState().view).toBe("visualizer");
  });

  it("returns to a chooser still free of engine destinations", () => {
    render(<DashboardShell />);

    fireEvent.click(screen.getByRole("button", { name: /open the engine/i }));
    fireEvent.click(screen.getByRole("button", { name: /^launch$/i }));

    expect(useUiStore.getState().view).toBe("launch");
    expect(railItems()).toEqual(["Launch"]);
  });
});
