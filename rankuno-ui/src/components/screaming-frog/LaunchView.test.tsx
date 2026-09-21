import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { LaunchView } from "./LaunchView";

/**
 * The opening screen's one job is to keep two different crawlers apart.
 *
 * The tests below are about what it *says*, not how it looks: which job list
 * each crawler's results land in, and — when a mode cannot run one of them —
 * that the reason is on screen rather than expressed by a control quietly
 * going missing.
 */
describe("LaunchView", () => {
  function renderView(overrides: Partial<Parameters<typeof LaunchView>[0]> = {}) {
    const onEngineCrawl = vi.fn();
    const onScreamingFrog = vi.fn();
    render(
      <LaunchView
        onEngineCrawl={onEngineCrawl}
        onScreamingFrog={onScreamingFrog}
        canStartEngineCrawl
        canDispatchScreamingFrog
        {...overrides}
      />,
    );
    return { onEngineCrawl, onScreamingFrog };
  }

  it("offers both crawlers and routes each to its own flow", () => {
    const { onEngineCrawl, onScreamingFrog } = renderView();

    fireEvent.click(screen.getByRole("button", { name: /start an engine crawl/i }));
    expect(onEngineCrawl).toHaveBeenCalledTimes(1);
    expect(onScreamingFrog).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /set up a screaming frog crawl/i }));
    expect(onScreamingFrog).toHaveBeenCalledTimes(1);
  });

  it("says where each crawler runs and where its results appear", () => {
    renderView();

    expect(screen.getByRole("heading", { name: /rankuno engine crawl/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /screaming frog crawl/i })).toBeInTheDocument();
    expect(screen.getByText(/runs on the server/i)).toBeInTheDocument();
    expect(screen.getByText(/runs on your pc/i)).toBeInTheDocument();
    // The two job systems are the thing most likely to be conflated, so the
    // Screaming Frog card states outright that its runs are not in that table.
    expect(screen.getByText(/not\s+Crawl jobs/i)).toBeInTheDocument();
  });

  it("disables the engine crawl in fixture mode, with the reason on screen", () => {
    renderView({ canStartEngineCrawl: false });

    expect(screen.getByRole("button", { name: /start an engine crawl/i })).toBeDisabled();
    expect(screen.getByText(/engine is not reachable/i)).toBeInTheDocument();
    // The other half is unaffected: one mode being unavailable must not read
    // as the whole screen being broken.
    expect(
      screen.getByRole("button", { name: /set up a screaming frog crawl/i }),
    ).toBeEnabled();
  });

  it("disables the Screaming Frog crawl in fixture mode, with the reason on screen", () => {
    renderView({ canDispatchScreamingFrog: false });

    expect(
      screen.getByRole("button", { name: /set up a screaming frog crawl/i }),
    ).toBeDisabled();
    expect(screen.getByText(/no engine to ask which machines are registered/i)).toBeInTheDocument();
  });
});
