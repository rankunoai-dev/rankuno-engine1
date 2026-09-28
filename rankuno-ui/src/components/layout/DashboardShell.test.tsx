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

/**
 * What the visualizer says while a crawl is on its way.
 *
 * Added with the reload restore: a restored crawl is re-fetched by id on boot,
 * and until it lands `result` is `null` — which used to render "No crawl
 * loaded". Showing the empty state during a fetch is both wrong and exactly the
 * complaint the restore was written to answer, one screen along.
 */
describe("DashboardShell — the visualizer while a crawl is loading", () => {
  beforeEach(() => {
    useUiStore.setState({ view: "visualizer", lastEngineView: "visualizer" });
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

  it("announces the wait instead of claiming nothing is loaded", () => {
    useCrawlStore.setState({ status: "running", activeJobId: "job-older" });

    render(<DashboardShell />);

    const loading = screen.getByText("Loading the crawl…");
    // Live-announced, so the wait reaches a screen reader and is not carried
    // by the spinner graphic alone.
    expect(loading.closest('[role="status"]')).not.toBeNull();
    expect(screen.queryByText(/Select one above/)).not.toBeInTheDocument();
  });

  it("resolves to the failure message rather than spinning for ever", () => {
    useCrawlStore.setState({ status: "failed" });

    render(<DashboardShell />);

    expect(screen.queryByText("Loading the crawl…")).not.toBeInTheDocument();
    expect(screen.getByText(/This crawl failed and produced no result/)).toBeInTheDocument();
  });

  it("still says nothing is loaded when nothing is on its way", () => {
    render(<DashboardShell />);

    expect(screen.queryByText("Loading the crawl…")).not.toBeInTheDocument();
    expect(screen.getByText(/No crawl loaded\. Select one above/)).toBeInTheDocument();
  });
});
