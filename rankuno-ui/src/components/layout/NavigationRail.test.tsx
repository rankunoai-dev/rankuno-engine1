import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { NavigationRail } from "./NavigationRail";
import { useAuthStore } from "../../store/useAuthStore";
import { useUiStore, type RailView } from "../../store/useUiStore";

vi.mock("../../store/useCrawlStore", () => ({
  useCrawlStore: <T,>(selector: (state: { liveJobs: Record<string, never> }) => T): T =>
    selector({ liveJobs: {} }),
  isLive: () => false,
}));

const ENGINE_ITEMS = [/visualizer/i, /crawl jobs/i, /dashboard/i, /audit/i, /gsc accounts/i];

function at(view: RailView): void {
  useUiStore.setState({ view, lastEngineView: "visualizer" });
}

function signedIn(): void {
  useAuthStore.setState({ token: "t", orgId: "acme", expiresAt: "2099-01-01T00:00:00Z" });
}

/** What the rail actually offers, in order, as a reader would read it. */
function railItems(): (string | undefined)[] {
  return screen.getAllByRole("button").map((button) => button.textContent?.trim());
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
    at("screaming-frog");
    render(<NavigationRail />);

    // Exactly two destinations: removed from the DOM, not faded, so nothing
    // hidden is reachable by Tab or announced by a screen reader.
    expect(railItems()).toEqual(["Launch", "Screaming Frog"]);
    for (const name of ENGINE_ITEMS) {
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    }
  });

  it("offers nothing but Launch on the chooser", () => {
    /* The five engine tabs are destinations *inside* the engine and belong
       there. Launch asks which of two crawlers you want; it used to open with
       the last product's rail already beside the question. */
    at("launch");
    render(<NavigationRail />);

    expect(railItems()).toEqual(["Launch"]);
    for (const name of ENGINE_ITEMS) {
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    }
    expect(screen.queryByRole("button", { name: /screaming frog/i })).not.toBeInTheDocument();
  });

  it("still offers nothing but Launch after the engine has been used", () => {
    /* The old bug was a *stored* product, so it only appeared once one had
       been entered. Coming back to the chooser is exactly that path. */
    useUiStore.getState().enterMode("engine");
    useUiStore.getState().setView("audit");
    useUiStore.getState().setView("launch");
    render(<NavigationRail />);

    expect(railItems()).toEqual(["Launch"]);
  });

  it("keeps log out reachable from the chooser", () => {
    /* A Launch-only rail must still end the session. Signing out is not an
       engine action and there is no other control for it. */
    signedIn();
    at("launch");
    render(<NavigationRail />);

    expect(railItems()).toEqual(["Launch", "Log out"]);

    fireEvent.click(screen.getByRole("button", { name: /log out/i }));
    expect(useAuthStore.getState().token).toBeNull();
  });

  it("marks Launch as the current page on the chooser", () => {
    at("launch");
    render(<NavigationRail />);

    const current = screen.getAllByRole("button").filter((b) => b.getAttribute("aria-current"));
    expect(current).toHaveLength(1);
    expect(current[0]).toHaveTextContent("Launch");
    expect(current[0]).toHaveAttribute("aria-current", "page");
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
    signedIn();
    at("screaming-frog");
    render(<NavigationRail />);

    expect(screen.getByRole("button", { name: /log out/i })).toBeInTheDocument();
  });

  it("renders a logout control once a session exists, and it signs out on click", () => {
    signedIn();

    render(<NavigationRail />);

    fireEvent.click(screen.getByRole("button", { name: /log out/i }));

    expect(useAuthStore.getState().token).toBeNull();
  });
});
