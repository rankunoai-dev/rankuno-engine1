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
    const onOpenEngine = vi.fn();
    const onScreamingFrog = vi.fn();
    render(
      <LaunchView
        onEngineCrawl={onEngineCrawl}
        onOpenEngine={onOpenEngine}
        onScreamingFrog={onScreamingFrog}
        canStartEngineCrawl
        canDispatchScreamingFrog
        {...overrides}
      />,
    );
    return { onEngineCrawl, onOpenEngine, onScreamingFrog };
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

  it("opens the engine without starting a crawl", () => {
    /* Entering the product and starting a crawl were the same control. The
       only way to look at a finished crawl was to open the new-crawl form and
       cancel it, and the rail no longer offers the engine from this screen. */
    const { onEngineCrawl, onOpenEngine } = renderView();

    fireEvent.click(screen.getByRole("button", { name: /open the engine/i }));

    expect(onOpenEngine).toHaveBeenCalledTimes(1);
    expect(onEngineCrawl).not.toHaveBeenCalled();
  });

  it("says what opening the engine does, and says it to a screen reader", () => {
    renderView();

    const open = screen.getByRole("button", { name: /open the engine/i });
    const hint = screen.getByText(/results already stored\. Starts nothing\./i);
    expect(open).toHaveAttribute("aria-describedby", hint.id);
  });

  it("keeps a way into the engine when no crawl can be started", () => {
    /* The trap this change had to clear: a chooser whose only two controls are
       both disabled is an application with no way into it. Reading results
       that already exist asks nothing of the engine. */
    const { onOpenEngine } = renderView({
      canStartEngineCrawl: false,
      canDispatchScreamingFrog: false,
    });

    const open = screen.getByRole("button", { name: /open the engine/i });
    expect(open).toBeEnabled();

    fireEvent.click(open);
    expect(onOpenEngine).toHaveBeenCalledTimes(1);
  });

  it("keeps the Screaming Frog view reachable when nothing can be dispatched", () => {
    /* That view states "fixture mode" and "no machine registered" for itself.
       Being unable to dispatch is a reason to explain, not to lock the door. */
    const { onScreamingFrog } = renderView({ canDispatchScreamingFrog: false });

    fireEvent.click(screen.getByRole("button", { name: /^open screaming frog$/i }));
    expect(onScreamingFrog).toHaveBeenCalledTimes(1);
  });

  it("offers no second door beside an enabled Screaming Frog button", () => {
    // Both controls would land on the same view; one of them is enough.
    renderView();

    expect(
      screen.queryByRole("button", { name: /^open screaming frog$/i }),
    ).not.toBeInTheDocument();
  });
});
