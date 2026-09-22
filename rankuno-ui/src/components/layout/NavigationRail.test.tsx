import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { NavigationRail } from "./NavigationRail";
import { useAuthStore } from "../../store/useAuthStore";
import { useUiStore, type RailView, type ProductMode } from "../../store/useUiStore";

vi.mock("../../store/useCrawlStore", () => ({
  useCrawlStore: <T,>(selector: (state: { liveJobs: Record<string, never> }) => T): T =>
    selector({ liveJobs: {} }),
  isLive: () => false,
}));

const ENGINE_ITEMS = [/visualizer/i, /crawl jobs/i, /dashboard/i, /audit/i, /gsc accounts/i];

function at(view: RailView, lastMode: ProductMode = "engine"): void {
  useUiStore.setState({ view, lastMode, lastEngineView: "visualizer" });
}

describe("NavigationRail", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    at("visualizer");
    useAuthStore.setState({
      token: null,
      orgId: null,
      expiresAt: null,
      loggingIn: false,
      loginError: null,
    });
  });

  it("shows Launch and only the engine's destinations in engine mode", () => {
    render(<NavigationRail />);

    expect(screen.getByRole("button", { name: /launch/i })).toBeInTheDocument();
    for (const name of ENGINE_ITEMS) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }
    expect(screen.queryByRole("button", { name: /screaming frog/i })).not.toBeInTheDocument();
  });

  it("shows Launch and only Screaming Frog in Screaming Frog mode", () => {
    at("screaming-frog", "screaming-frog");
    render(<NavigationRail />);

    // Exactly two destinations: removed from the DOM, not faded, so nothing
    // hidden is reachable by Tab or announced by a screen reader.
    const buttons = screen.getAllByRole("button");
    expect(buttons.map((b) => b.textContent?.trim())).toEqual(["Launch", "Screaming Frog"]);
    for (const name of ENGINE_ITEMS) {
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    }
  });

  it("keeps the last product's items on Launch", () => {
    at("launch", "screaming-frog");
    render(<NavigationRail />);

    expect(screen.getByRole("button", { name: /screaming frog/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /visualizer/i })).not.toBeInTheDocument();
  });

  it("marks only the current view with aria-current", () => {
    at("audit");
    render(<NavigationRail />);

    const current = screen.getAllByRole("button").filter((b) => b.getAttribute("aria-current"));
    expect(current).toHaveLength(1);
    expect(current[0]).toHaveTextContent("Audit");
    expect(current[0]).toHaveAttribute("aria-current", "page");
  });

  it("GSC Accounts button has an icon", () => {
    render(<NavigationRail />);

    const gscButton = screen.getByRole("button", { name: /gsc accounts/i });
    expect(gscButton.querySelector("svg")).toBeInTheDocument();
  });

  it("renders no logout control while signed out", () => {
    render(<NavigationRail />);

    expect(screen.queryByRole("button", { name: /log out/i })).not.toBeInTheDocument();
  });

  it("keeps logout in Screaming Frog mode too", () => {
    useAuthStore.setState({ token: "t", orgId: "acme", expiresAt: "2099-01-01T00:00:00Z" });
    at("screaming-frog", "screaming-frog");
    render(<NavigationRail />);

    expect(screen.getByRole("button", { name: /log out/i })).toBeInTheDocument();
  });

  it("renders a logout control once a session exists, and it signs out on click", () => {
    useAuthStore.setState({ token: "t", orgId: "acme", expiresAt: "2099-01-01T00:00:00Z" });

    render(<NavigationRail />);

    fireEvent.click(screen.getByRole("button", { name: /log out/i }));

    expect(useAuthStore.getState().token).toBeNull();
  });
});
