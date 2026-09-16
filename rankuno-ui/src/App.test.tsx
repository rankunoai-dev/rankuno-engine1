import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import App from "./App";
import { useAuthStore } from "./store/useAuthStore";

/**
 * The login gate ADR 0016 forced onto `App`.
 *
 * `DashboardShell`/`LoginScreen` are stubbed rather than rendered for real:
 * this suite exists to prove which one `App` picks and when, not to re-test
 * either screen's own internals (covered by `LoginScreen.test.tsx` and the
 * dashboard's own suites). `useCrawlStore` is stubbed for the same reason —
 * its `init` firing (or not) is the observable this file checks, not what it
 * does once called.
 */

vi.stubGlobal("fetch", vi.fn());

vi.mock("./components/layout/DashboardShell", () => ({
  DashboardShell: () => <div>DASHBOARD_SHELL</div>,
}));

vi.mock("./components/auth/LoginScreen", () => ({
  LoginScreen: () => <div>LOGIN_SCREEN</div>,
}));

const init = vi.fn().mockResolvedValue(undefined);
vi.mock("./store/useCrawlStore", () => ({
  useCrawlStore: (selector: (state: { init: typeof init }) => unknown) =>
    selector({ init }),
}));

function resetAuth(): void {
  useAuthStore.setState({
    token: null,
    orgId: null,
    expiresAt: null,
    loggingIn: false,
    loginError: null,
  });
}

describe("App", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    resetAuth();
  });

  it("shows the login screen when the live engine answers but no session exists", async () => {
    (fetch as any).mockResolvedValueOnce(new Response("", { status: 200 })); // /health

    render(<App />);

    await waitFor(() => {
      expect(screen.getByText("LOGIN_SCREEN")).toBeInTheDocument();
    });
    expect(screen.queryByText("DASHBOARD_SHELL")).not.toBeInTheDocument();
    // The whole point of the gate: no authenticated request fires before a
    // session exists, so nothing 401s the instant the tab opens.
    expect(init).not.toHaveBeenCalled();
  });

  it("shows the dashboard directly when a valid session already exists", async () => {
    (fetch as any).mockResolvedValueOnce(new Response("", { status: 200 })); // /health
    useAuthStore.setState({ token: "t", orgId: "acme", expiresAt: "2099-01-01T00:00:00Z" });

    render(<App />);

    await waitFor(() => {
      expect(screen.getByText("DASHBOARD_SHELL")).toBeInTheDocument();
    });
    expect(screen.queryByText("LOGIN_SCREEN")).not.toBeInTheDocument();
    expect(init).toHaveBeenCalled();
  });

  it("shows the dashboard for offline/fixture mode without requiring a session", async () => {
    (fetch as any).mockRejectedValueOnce(new TypeError("Failed to fetch")); // /health unreachable

    render(<App />);

    await waitFor(() => {
      expect(screen.getByText("DASHBOARD_SHELL")).toBeInTheDocument();
    });
    // Bundled fixtures never leave the browser and carry no session boundary
    // to guard — gating them behind a login screen would strand the exact
    // "server is not running" case that mode exists for.
    expect(screen.queryByText("LOGIN_SCREEN")).not.toBeInTheDocument();
  });
});
