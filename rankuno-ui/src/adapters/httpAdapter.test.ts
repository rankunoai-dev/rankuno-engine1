import { afterEach, describe, expect, it, vi } from "vitest";
import { authorizedFetch, setAuthToken, setSessionExpiredHandler } from "./httpAdapter";

/**
 * The ADR 0016 plumbing `authorizedFetch` adds underneath every adapter call:
 * the bearer header, and treating a `401` (and only a `401`) as a dead
 * session. `HttpAdapter`'s own methods are exercised through the store tests
 * and components that call them; this file is the one place the header
 * attachment and the `401`/`403` distinction are checked directly.
 */

vi.stubGlobal("fetch", vi.fn());

afterEach(() => {
  vi.clearAllMocks();
  setAuthToken(null);
  setSessionExpiredHandler(null);
});

describe("authorizedFetch", () => {
  it("attaches the stored token as a bearer header", async () => {
    setAuthToken("session-token-abc");
    (fetch as any).mockResolvedValueOnce(new Response("{}", { status: 200 }));

    await authorizedFetch("http://engine/api/v1/jobs");

    const [, init] = (fetch as any).mock.calls[0];
    expect((init.headers as Headers).get("Authorization")).toBe("Bearer session-token-abc");
  });

  it("sends no Authorization header when signed out", async () => {
    setAuthToken(null);
    (fetch as any).mockResolvedValueOnce(new Response("{}", { status: 200 }));

    await authorizedFetch("http://engine/api/v1/jobs");

    const [, init] = (fetch as any).mock.calls[0];
    expect((init.headers as Headers).has("Authorization")).toBe(false);
  });

  it("preserves the caller's own init fields alongside the auth header", async () => {
    setAuthToken("t");
    (fetch as any).mockResolvedValueOnce(new Response("{}", { status: 200 }));

    await authorizedFetch("http://engine/api/v1/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });

    const [, init] = (fetch as any).mock.calls[0];
    expect(init.method).toBe("POST");
    expect(init.body).toBe("{}");
    expect((init.headers as Headers).get("Content-Type")).toBe("application/json");
    expect((init.headers as Headers).get("Authorization")).toBe("Bearer t");
  });

  it("runs the session-expired handler on a 401", async () => {
    const onExpired = vi.fn();
    setSessionExpiredHandler(onExpired);
    setAuthToken("stale-token");
    (fetch as any).mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "invalid or expired session" }), { status: 401 }),
    );

    await authorizedFetch("http://engine/api/v1/jobs");

    expect(onExpired).toHaveBeenCalledTimes(1);
  });

  it("does not run the session-expired handler on a 403 — a real org mismatch, not a dead session", async () => {
    const onExpired = vi.fn();
    setSessionExpiredHandler(onExpired);
    setAuthToken("valid-token");
    (fetch as any).mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "access denied" }), { status: 403 }),
    );

    await authorizedFetch("http://engine/api/v1/jobs");

    expect(onExpired).not.toHaveBeenCalled();
  });

  it("does not run the session-expired handler on a 2xx", async () => {
    const onExpired = vi.fn();
    setSessionExpiredHandler(onExpired);
    setAuthToken("valid-token");
    (fetch as any).mockResolvedValueOnce(new Response("{}", { status: 200 }));

    await authorizedFetch("http://engine/api/v1/jobs");

    expect(onExpired).not.toHaveBeenCalled();
  });
});
