import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * ADR 0016 session-token storage and the login round trip.
 *
 * `login`/`logout` are exercised directly against the store, the same way
 * `useCrawlStore.test.ts` exercises `refreshJobs` — no component needed to
 * prove the state machine is correct. `LoginScreen.test.tsx` covers the form
 * wired to it.
 */

const STORAGE_KEY = "rankuno.auth";

vi.stubGlobal("fetch", vi.fn());

describe("useAuthStore", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    window.localStorage.clear();
    const { useAuthStore } = await import("./useAuthStore");
    useAuthStore.setState({ token: null, orgId: null, expiresAt: null, loggingIn: false, loginError: null });
  });

  it("stores the token, org, and expiry on a successful login", async () => {
    const { useAuthStore } = await import("./useAuthStore");
    (fetch as any).mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          token: "session-token-abc",
          token_type: "bearer",
          org_id: "acme",
          expires_at: "2099-01-01T00:00:00Z",
        }),
        { status: 200 },
      ),
    );

    const ok = await useAuthStore.getState().login("op-1", "correct-horse");

    expect(ok).toBe(true);
    expect(useAuthStore.getState().token).toBe("session-token-abc");
    expect(useAuthStore.getState().orgId).toBe("acme");
    expect(useAuthStore.getState().expiresAt).toBe("2099-01-01T00:00:00Z");
    expect(useAuthStore.getState().loginError).toBeNull();
    expect(useAuthStore.getState().loggingIn).toBe(false);

    // Persisted for the next page load, per ADR 0016's "the app is currently
    // non-functional" brief — a token that only lived in memory would force
    // a fresh login on every refresh.
    const stored = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "null");
    expect(stored).toEqual({
      token: "session-token-abc",
      orgId: "acme",
      expiresAt: "2099-01-01T00:00:00Z",
    });
  });

  it("surfaces the server's generic message on a rejected login, never which field was wrong", async () => {
    const { useAuthStore } = await import("./useAuthStore");
    (fetch as any).mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "invalid operator id or password" }), {
        status: 401,
      }),
    );

    const ok = await useAuthStore.getState().login("nobody", "wrong");

    expect(ok).toBe(false);
    expect(useAuthStore.getState().token).toBeNull();
    expect(useAuthStore.getState().loginError).toBe("invalid operator id or password");
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it("gives a distinct message for a network failure, not the credentials message", async () => {
    const { useAuthStore } = await import("./useAuthStore");
    (fetch as any).mockRejectedValueOnce(new TypeError("Failed to fetch"));

    const ok = await useAuthStore.getState().login("op-1", "whatever");

    expect(ok).toBe(false);
    expect(useAuthStore.getState().loginError).toMatch(/cannot reach the engine/i);
    expect(useAuthStore.getState().loginError).not.toMatch(/invalid operator id or password/i);
  });

  it("sets loggingIn while the request is in flight and clears it after", async () => {
    const { useAuthStore } = await import("./useAuthStore");
    let resolveFetch: (value: Response) => void = () => {};
    (fetch as any).mockReturnValueOnce(
      new Promise<Response>((resolve) => {
        resolveFetch = resolve;
      }),
    );

    const pending = useAuthStore.getState().login("op-1", "pw");
    expect(useAuthStore.getState().loggingIn).toBe(true);

    resolveFetch(
      new Response(
        JSON.stringify({
          token: "t",
          token_type: "bearer",
          org_id: "acme",
          expires_at: "2099-01-01T00:00:00Z",
        }),
        { status: 200 },
      ),
    );
    await pending;

    expect(useAuthStore.getState().loggingIn).toBe(false);
  });

  it("clears the token, org, expiry, and localStorage on logout", async () => {
    const { useAuthStore } = await import("./useAuthStore");
    useAuthStore.setState({ token: "t", orgId: "acme", expiresAt: "2099-01-01T00:00:00Z" });
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ token: "t", orgId: "acme", expiresAt: "2099-01-01T00:00:00Z" }),
    );

    useAuthStore.getState().logout();

    expect(useAuthStore.getState().token).toBeNull();
    expect(useAuthStore.getState().orgId).toBeNull();
    expect(useAuthStore.getState().expiresAt).toBeNull();
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  describe("isSessionValid", () => {
    it("is false with no token", async () => {
      const { isSessionValid } = await import("./useAuthStore");
      expect(isSessionValid({ token: null, expiresAt: null })).toBe(false);
    });

    it("is true for a token that has not expired", async () => {
      const { isSessionValid } = await import("./useAuthStore");
      expect(isSessionValid({ token: "t", expiresAt: "2099-01-01T00:00:00Z" })).toBe(true);
    });

    it("is false for a token past its own expires_at", async () => {
      const { isSessionValid } = await import("./useAuthStore");
      expect(isSessionValid({ token: "t", expiresAt: "2000-01-01T00:00:00Z" })).toBe(false);
    });
  });

  describe("launcher sign-in link (ADR 0033)", () => {
    const LINK_TOKEN = "7e".repeat(32);

    function sessionResponse(status = 200): Response {
      return new Response(
        JSON.stringify(
          status === 200
            ? {
                token: "session-from-link",
                token_type: "bearer",
                org_id: "default",
                expires_at: "2099-01-01T00:00:00Z",
              }
            : { detail: "sign-in link is invalid or expired" },
        ),
        { status },
      );
    }

    async function loadWithUrl(url: string) {
      window.history.replaceState(null, "", url);
      vi.resetModules();
      return import("./useAuthStore");
    }

    function everythingStored(): string {
      const values: string[] = [];
      for (let i = 0; i < window.localStorage.length; i += 1) {
        const key = window.localStorage.key(i) ?? "";
        values.push(key, window.localStorage.getItem(key) ?? "");
      }
      return values.join("\n");
    }

    it("strips the link from the address bar on load, before any request", async () => {
      const replaceState = vi.spyOn(window.history, "replaceState");
      await loadWithUrl(`/#autosignin=${LINK_TOKEN}`);

      expect(window.location.hash).toBe("");
      expect(window.location.href).not.toContain(LINK_TOKEN);
      // Called by the module itself (the first call is this test's own setup).
      expect(replaceState).toHaveBeenCalledTimes(2);
      expect(fetch).not.toHaveBeenCalled();
      replaceState.mockRestore();
    });

    it("keeps the path and query when it strips the fragment", async () => {
      await loadWithUrl(`/login?tab=jobs#autosignin=${LINK_TOKEN}`);
      expect(window.location.pathname).toBe("/login");
      expect(window.location.search).toBe("?tab=jobs");
      expect(window.location.hash).toBe("");
    });

    it("posts the token in the body, once, and stores the session the login way", async () => {
      const { useAuthStore } = await loadWithUrl(`/#autosignin=${LINK_TOKEN}`);
      const { API_BASE } = await import("../adapters/httpAdapter");
      const consoleSpies = (["log", "info", "warn", "error", "debug"] as const).map((level) =>
        vi.spyOn(console, level).mockImplementation(() => undefined),
      );
      (fetch as any).mockResolvedValueOnce(sessionResponse());

      const ok = await useAuthStore.getState().signInWithLink();

      expect(ok).toBe(true);
      expect(fetch).toHaveBeenCalledTimes(1);
      const [url, init] = (fetch as any).mock.calls[0] as [string, RequestInit];
      expect(url).toBe(`${API_BASE}/auth/local-signin`);
      expect(url).not.toContain(LINK_TOKEN);
      expect(init.method).toBe("POST");
      expect(JSON.parse(String(init.body))).toEqual({ token: LINK_TOKEN });

      const state = useAuthStore.getState();
      expect(state.token).toBe("session-from-link");
      expect(state.orgId).toBe("default");
      expect(JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "null")).toEqual({
        token: "session-from-link",
        orgId: "default",
        expiresAt: "2099-01-01T00:00:00Z",
      });
      expect(JSON.stringify(state)).not.toContain(LINK_TOKEN);
      expect(everythingStored()).not.toContain(LINK_TOKEN);
      for (const spy of consoleSpies) {
        expect(JSON.stringify(spy.mock.calls)).not.toContain(LINK_TOKEN);
        spy.mockRestore();
      }

      // Read once: a second call has nothing to send.
      expect(await useAuthStore.getState().signInWithLink()).toBe(false);
      expect(fetch).toHaveBeenCalledTimes(1);
    });

    it.each([
      ["a refused link", () => Promise.resolve(sessionResponse(401))],
      ["a rate-limited link", () => Promise.resolve(sessionResponse(429))],
      ["an unreachable engine", () => Promise.reject(new TypeError("Failed to fetch"))],
    ])("falls back to the login screen with a generic message for %s", async (_name, reply) => {
      const { useAuthStore } = await loadWithUrl(`/#autosignin=${LINK_TOKEN}`);
      (fetch as any).mockImplementationOnce(reply);

      const ok = await useAuthStore.getState().signInWithLink();

      expect(ok).toBe(false);
      const state = useAuthStore.getState();
      expect(state.token).toBeNull();
      expect(state.loggingIn).toBe(false);
      expect(state.loginError).toMatch(/expired or was already used/);
      expect(JSON.stringify(state)).not.toContain(LINK_TOKEN);
      expect(everythingStored()).not.toContain(LINK_TOKEN);
    });

    it("strips a malformed link and never sends it", async () => {
      const { useAuthStore } = await loadWithUrl("/#autosignin=not-a-hex-token");

      expect(window.location.hash).toBe("");
      expect(await useAuthStore.getState().signInWithLink()).toBe(false);
      expect(fetch).not.toHaveBeenCalled();
      expect(useAuthStore.getState().loginError).toBeNull();
    });

    it("does nothing without a link", async () => {
      const { useAuthStore } = await loadWithUrl("/#section=jobs");

      expect(window.location.hash).toBe("#section=jobs");
      expect(await useAuthStore.getState().signInWithLink()).toBe(false);
      expect(fetch).not.toHaveBeenCalled();
      expect(useAuthStore.getState().loginError).toBeNull();
    });
  });

  describe("start-up restore", () => {
    it("restores a valid session from localStorage on module load", async () => {
      window.localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ token: "restored-token", orgId: "acme", expiresAt: "2099-01-01T00:00:00Z" }),
      );
      vi.resetModules();
      const { useAuthStore } = await import("./useAuthStore");

      expect(useAuthStore.getState().token).toBe("restored-token");
      expect(useAuthStore.getState().orgId).toBe("acme");
    });

    it("drops an expired session on load rather than starting authenticated", async () => {
      window.localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ token: "stale-token", orgId: "acme", expiresAt: "2000-01-01T00:00:00Z" }),
      );
      vi.resetModules();
      const { useAuthStore } = await import("./useAuthStore");

      expect(useAuthStore.getState().token).toBeNull();
      // The stale value is not just ignored in memory — it is wiped, so a
      // later read of `localStorage` cannot resurrect it either.
      expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
    });
  });
});
