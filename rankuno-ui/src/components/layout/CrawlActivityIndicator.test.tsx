import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CrawlActivityView, CrawlDataAdapter } from "../../adapters/adapterInterface";
import { useAuthStore } from "../../store/useAuthStore";
import { useCrawlStore } from "../../store/useCrawlStore";
import { useUiStore } from "../../store/useUiStore";
import { CrawlActivityIndicator } from "./CrawlActivityIndicator";
import { HeaderBar } from "./HeaderBar";

/**
 * The header's org-wide crawl count.
 *
 * Real timers: each case needs only the first, immediate fetch, so `waitFor`
 * is enough and the polling cadence is covered in `useCrawlActivity.test.ts`.
 */

const NOOP = (): void => {};

function serve(activity: CrawlActivityView | Error): void {
  const getCrawlActivity =
    activity instanceof Error
      ? vi.fn().mockRejectedValue(activity)
      : vi.fn().mockResolvedValue(activity);
  useCrawlStore.setState({ adapter: { getCrawlActivity } as unknown as CrawlDataAdapter });
}

/** Renders, then lets the first fetch land inside `act`. */
async function mount(ui: JSX.Element): Promise<void> {
  await act(async () => {
    render(ui);
  });
}

const status = () => screen.findByRole("status");

beforeEach(() => {
  useAuthStore.setState({ token: "token" });
  useCrawlStore.setState({ result: null, jobs: [], activeJobId: null, liveJobs: {} });
  useUiStore.setState({ view: "visualizer", lastMode: "engine", lastEngineView: "visualizer" });
});

afterEach(() => {
  // Still mounted here (the DOM sweep runs after this hook), so the store
  // writes that end the session must be inside `act`.
  act(() => {
    useAuthStore.setState({ token: null });
    useCrawlStore.setState({ adapter: null });
  });
});

describe("CrawlActivityIndicator", () => {
  it("is muted when nothing is running", async () => {
    serve({ rankuno_active: 0, rankuno_cap: 5, sf_active: 0 });
    await mount(<CrawlActivityIndicator />);

    const el = await status();
    expect(el).toHaveAttribute("aria-label", "Rankuno 0/5 · Screaming Frog 0 active");
    expect(el).toHaveClass("crawlact-idle");
    expect(el).toHaveAttribute("aria-live", "polite");
  });

  it("shows Rankuno crawls independently of Screaming Frog", async () => {
    serve({ rankuno_active: 3, rankuno_cap: 5, sf_active: 0 });
    await mount(<CrawlActivityIndicator />);

    const el = await status();
    expect(el).toHaveAttribute("aria-label", "Rankuno 3/5 · Screaming Frog 0 active");
    expect(el).toHaveClass("crawlact-running");
  });

  it("shows Screaming Frog crawls independently of Rankuno", async () => {
    serve({ rankuno_active: 0, rankuno_cap: 5, sf_active: 2 });
    await mount(<CrawlActivityIndicator />);

    const el = await status();
    expect(el).toHaveAttribute("aria-label", "Rankuno 0/5 · Screaming Frog 2 active");
    expect(el).toHaveClass("crawlact-running");
  });

  it("warns, in words as well as colour, when the server is at capacity", async () => {
    serve({ rankuno_active: 5, rankuno_cap: 5, sf_active: 0 });
    await mount(<CrawlActivityIndicator />);

    const el = await status();
    expect(el).toHaveClass("crawlact-full");
    expect(el.getAttribute("aria-label")).toContain("Server at capacity");
    expect(screen.getByText("FULL")).toBeInTheDocument();
  });

  it("explains capacity in the tooltip using the server's cap", async () => {
    serve({ rankuno_active: 3, rankuno_cap: 3, sf_active: 0 });
    await mount(<CrawlActivityIndicator />);

    fireEvent.mouseEnter(await status());
    await waitFor(() =>
      expect(
        screen.getByText(
          "Server is at capacity (3 concurrent crawls). New crawls will wait or be refused until one finishes.",
        ),
      ).toBeInTheDocument(),
    );
  });

  it("reads the cap from the response rather than assuming one", async () => {
    serve({ rankuno_active: 1, rankuno_cap: 12, sf_active: 0 });
    await mount(<CrawlActivityIndicator />);

    const el = await status();
    expect(el).toHaveAttribute("aria-label", "Rankuno 1/12 · Screaming Frog 0 active");
    expect(el).toHaveClass("crawlact-running");
    expect(el.textContent).not.toContain("/5");
  });

  it("treats an active count above the cap as full", async () => {
    serve({ rankuno_active: 6, rankuno_cap: 5, sf_active: 0 });
    await mount(<CrawlActivityIndicator />);
    expect(await status()).toHaveClass("crawlact-full");
  });

  it("renders nothing when the endpoint fails", async () => {
    const getCrawlActivity = vi.fn().mockRejectedValue(new Error("boom"));
    useCrawlStore.setState({ adapter: { getCrawlActivity } as unknown as CrawlDataAdapter });
    await mount(<CrawlActivityIndicator />);

    await waitFor(() => expect(getCrawlActivity).toHaveBeenCalled());
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("renders nothing when logged out", async () => {
    useAuthStore.setState({ token: null });
    serve({ rankuno_active: 1, rankuno_cap: 5, sf_active: 1 });
    await mount(<CrawlActivityIndicator />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});

describe("CrawlActivityIndicator in the header", () => {
  it.each(["visualizer", "jobs", "launch", "screaming-frog"] as const)(
    "is present on the %s view",
    async (view) => {
      useUiStore.setState({ view });
      serve({ rankuno_active: 1, rankuno_cap: 5, sf_active: 0 });
      await mount(<HeaderBar navParsed onNewCrawl={NOOP} onPrint={NOOP} />);

      expect(await status()).toHaveAttribute(
        "aria-label",
        "Rankuno 1/5 · Screaming Frog 0 active",
      );
    },
  );
});
