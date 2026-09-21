import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { NavigationRail } from "./NavigationRail";
import { useAuthStore } from "../../store/useAuthStore";

// Mock the stores
vi.mock("../../store/useUiStore", () => ({
  useUiStore: (selector: any) => {
    const state = {
      view: "visualizer",
      setView: vi.fn(),
    };
    return selector(state);
  },
}));

vi.mock("../../store/useCrawlStore", () => ({
  useCrawlStore: (selector: any) => {
    const state = {
      liveJobs: {},
    };
    return selector(state);
  },
  isLive: () => false,
}));

describe("NavigationRail", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({
      token: null,
      orgId: null,
      expiresAt: null,
      loggingIn: false,
      loginError: null,
    });
  });

  it("renders all navigation buttons", () => {
    render(<NavigationRail />);

    expect(screen.getByRole("button", { name: /launch/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /visualizer/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /crawl jobs/i })).toBeInTheDocument();
    // Its own destination. Screaming Frog dispatches are a separate job system
    // from `Crawl jobs`, and the rail is where that separation is first seen.
    expect(screen.getByRole("button", { name: /screaming frog/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /audit/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /gsc accounts/i })).toBeInTheDocument();
  });

  it("renders GSC Accounts button", () => {
    render(<NavigationRail />);

    const gscButton = screen.getByRole("button", { name: /gsc accounts/i });
    expect(gscButton).toBeInTheDocument();
  });

  it("GSC Accounts button has correct icon", () => {
    render(<NavigationRail />);

    const gscButton = screen.getByRole("button", { name: /gsc accounts/i });
    const svg = gscButton.querySelector("svg");
    expect(svg).toBeInTheDocument();
  });

  it("renders no logout control while signed out", () => {
    render(<NavigationRail />);

    expect(screen.queryByRole("button", { name: /log out/i })).not.toBeInTheDocument();
  });

  it("renders a logout control once a session exists, and it signs out on click", () => {
    useAuthStore.setState({ token: "t", orgId: "acme", expiresAt: "2099-01-01T00:00:00Z" });

    render(<NavigationRail />);

    const logoutButton = screen.getByRole("button", { name: /log out/i });
    fireEvent.click(logoutButton);

    expect(useAuthStore.getState().token).toBeNull();
  });
});
