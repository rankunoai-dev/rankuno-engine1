import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import App from "./App";
import { captureSignInLink, useAuthStore } from "./store/useAuthStore";

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

  it("does not restore anything behind the login screen when the session expired", async () => {
    /* Edge case in the reload brief: the view is restored at module load, but
       `App` still gates on the session, so an expired one shows the login
       screen and no crawl is fetched until it is replaced. Signing in then
       lands on the restored view with its crawl, rather than the two fighting
       over what is on screen. */
    (fetch as any).mockResolvedValue(new Response("", { status: 200 })); // /health
    window.localStorage.setItem("rankuno.ui", JSON.stringify({ view: "visualizer" }));

    const { rerender } = render(<App />);

    await waitFor(() => {
      expect(screen.getByText("LOGIN_SCREEN")).toBeInTheDocument();
    });
    expect(init).not.toHaveBeenCalled();

    useAuthStore.setState({ token: "t", orgId: "acme", expiresAt: "2099-01-01T00:00:00Z" });
    rerender(<App />);

    await waitFor(() => {
      expect(screen.getByText("DASHBOARD_SHELL")).toBeInTheDocument();
    });
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

  describe("launcher sign-in link (ADR 0033)", () => {
    const LINK_TOKEN = "3c".repeat(32);

    it("exchanges the link before any other request and opens the dashboard", async () => {
      window.history.replaceState(null, "", `/#autosignin=${LINK_TOKEN}`);
      captureSignInLink();
      (fetch as any)
        .mockResolvedValueOnce(
          new Response(
            JSON.stringify({
              token: "session-from-link",
              token_type: "bearer",
              org_id: "default",
              expires_at: "2099-01-01T00:00:00Z",
            }),
            { status: 200 },
          ),
        ) // /auth/local-signin
        .mockResolvedValueOnce(new Response("", { status: 200 })); // /health

      render(<App />);

      await waitFor(() => {
        expect(screen.getByText("DASHBOARD_SHELL")).toBeInTheDocument();
      });
      const urls = (fetch as any).mock.calls.map((call: unknown[]) => String(call[0]));
      expect(urls[0]).toMatch(/\/auth\/local-signin$/);
      expect(urls[1]).toMatch(/\/health$/);
      expect(urls.join(" ")).not.toContain(LINK_TOKEN);
      expect(init).toHaveBeenCalled();
    });

    it("shows the normal login screen when the link is refused", async () => {
      window.history.replaceState(null, "", `/#autosignin=${LINK_TOKEN}`);
      captureSignInLink();
      (fetch as any)
        .mockResolvedValueOnce(
          new Response(JSON.stringify({ detail: "sign-in link is invalid or expired" }), {
            status: 401,
          }),
        )
        .mockResolvedValueOnce(new Response("", { status: 200 }));

      render(<App />);

      await waitFor(() => {
        expect(screen.getByText("LOGIN_SCREEN")).toBeInTheDocument();
      });
      expect(useAuthStore.getState().loginError).toMatch(/expired or was already used/);
      expect(init).not.toHaveBeenCalled();
    });
  });
});
