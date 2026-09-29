import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "../../store/useAuthStore";
import { useCrawlStore } from "../../store/useCrawlStore";
import { useNoticeStore } from "../../store/useNoticeStore";
import { useUiStore } from "../../store/useUiStore";
import { crawl, crawlJob, discovery } from "../../test/factories";
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

/**
 * The dismissible banners, and the one banner that is not.
 *
 * `NoticeStack.test.tsx` covers dismissal itself. What is pinned here is the
 * judgement call the shell makes: the error banner keeps no close button,
 * because it is the only banner carrying a recovery action and the only one
 * with no crawl to scope a dismissal to.
 */
describe("DashboardShell — dismissing the safety banners", () => {
  beforeEach(() => {
    window.localStorage.clear();
    useNoticeStore.setState({ dismissed: {} });
    useUiStore.setState({ view: "visualizer", lastEngineView: "visualizer" });
    useCrawlStore.setState({
      adapter: null,
      result: null,
      jobs: [],
      activeJobId: null,
      liveJobs: {},
      status: "idle",
      error: null,
      reconciliation: null,
      grouping: "path",
      includeDefaulters: false,
    });
    useAuthStore.setState({
      token: null,
      orgId: null,
      expiresAt: null,
      loggingIn: false,
      loginError: null,
    });
  });

  /**
   * The banner stack alone.
   *
   * The printable report is always mounted beside the dashboard — it is
   * revealed by `@media print`, not by a render — and it says its own version
   * of "this is a partial view of the site". A document-wide query therefore
   * finds two, and would keep passing if the banner disappeared entirely.
   */
  function stack(): HTMLElement {
    const app = document.querySelector(".rk-app");
    if (!app) throw new Error("the dashboard did not render");
    return app as HTMLElement;
  }

  /** A loaded crawl that stopped at its page ceiling. */
  function loadTruncatedCrawl(jobId: string): void {
    useCrawlStore.setState({
      activeJobId: jobId,
      status: "succeeded",
      jobs: [crawlJob({ id: jobId, truncated: true })],
      result: crawl({ discovery: discovery({ truncated: true }) }),
    });
  }

  it("closes the partial-crawl warning against the crawl it describes", () => {
    loadTruncatedCrawl("job-a");
    render(<DashboardShell />);

    const message = /partial view of the site, not the whole of it/;
    expect(within(stack()).getByText(message)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Dismiss the partial crawl notice" }));

    expect(within(stack()).queryByText(message)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /1 hidden notice/ })).toBeInTheDocument();
    expect(useNoticeStore.getState().dismissed["job-a"]).toEqual(["truncated"]);
  });

  it("says it again for a different crawl", () => {
    /* The difference between "this site has 405 pages" and "I looked at 405
       pages of this site". A dismissal on one crawl cannot answer for
       another. */
    useNoticeStore.setState({ dismissed: { "job-a": ["truncated"] } });
    loadTruncatedCrawl("job-b");

    render(<DashboardShell />);

    expect(
      within(stack()).getByText(/partial view of the site, not the whole of it/),
    ).toBeInTheDocument();
  });

  it("keeps the recovery action out of reach of a close button", () => {
    /* The judgement call. "Render partial tree" is the only way back for a
       failed job that left a checkpoint on disk, and a recovery path behind a
       × is worse than the clutter it would save. The banner also fires for a
       rejected submission, which has no job row — so the only dismissal
       available to it would be a global one, which this design refuses. */
    useCrawlStore.setState({
      error: "The crawl failed after 1,204 pages.",
      activeJobId: "job-a",
      jobs: [crawlJob({ id: "job-a", status: "failed" })],
    });

    render(<DashboardShell />);

    expect(screen.getByText("The crawl failed after 1,204 pages.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Dismiss/i })).toBeNull();
  });
});
