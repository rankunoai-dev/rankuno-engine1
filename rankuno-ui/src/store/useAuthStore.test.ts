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
