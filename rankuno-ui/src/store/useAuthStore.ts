import { create } from "zustand";
import { API_BASE, setAuthToken, setSessionExpiredHandler } from "../adapters/httpAdapter";

/**
 * What `POST /auth/login` accepts and returns.
 *
 * Mirrors `LoginRequest`/`LoginResponse` in `src/api/auth.py`. Hand-written,
 * not generated: `scripts/export_ui_contract.py`'s `MODELS` tuple only walks
 * `src/modules/seo/page_classifier/`, so it has never seen `src/api/auth.py`
 * at all — the same gap `RulebookRecord`/`DeliverableAccepted` hit, and the
 * one `GscAccountsView`'s own hand-written `GscAccount` interface already
 * shows the fix for: write the shape next to the one place that reads it,
 * rather than wait on a generator that was never scoped to cover it.
 */
interface LoginRequestBody {
  operator_id: string;
  password: string;
}

interface LoginResponseBody {
  token: string;
  token_type: string;
  org_id: string;
  expires_at: string;
}

/** What is kept in `localStorage`, and what this store restores from it. */
interface StoredSession {
  token: string;
  orgId: string;
  expiresAt: string;
}

const STORAGE_KEY = "rankuno.auth";

interface AuthState {
  token: string | null;
  orgId: string | null;
  expiresAt: string | null;
  /** True while a login request is in flight — the form disables submit on this. */
  loggingIn: boolean;
  /**
   * The last login failure, verbatim from the server.
   *
   * Never more specific than what the server sent: ADR 0016 deliberately
   * makes an unknown operator id, a wrong password, and an inactive operator
   * indistinguishable, so the UI has nothing more specific to say either
   * without undoing that on the client side.
   */
  loginError: string | null;
  login: (operatorId: string, password: string) => Promise<boolean>;
  logout: () => void;
}

function readStoredSession(): StoredSession | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredSession>;
    if (!parsed.token || !parsed.orgId || !parsed.expiresAt) return null;
    return { token: parsed.token, orgId: parsed.orgId, expiresAt: parsed.expiresAt };
  } catch {
    // A corrupt or unreadable value reads the same as no session — the
    // operator sees the login screen either way, not a crash.
    return null;
  }
}

function writeStoredSession(session: StoredSession | null): void {
  try {
    if (session) window.localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
    else window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Private-mode quota, or storage disabled outright. The session still
    // works for the tab that just signed in; it only fails to survive a
    // reload, which is a smaller loss than a login screen that throws.
  }
}

function isExpired(expiresAt: string): boolean {
  return new Date(expiresAt).getTime() <= Date.now();
}

const restored = readStoredSession();
// A token already past its own `expires_at` is dropped before it is ever
// attached to a request. The server would reject it anyway with a `401`;
// this only skips the one guaranteed-failing round trip, and the flash of an
// authenticated shell that the global `401` handler would otherwise have to
// tear back down a moment later.
const restoredValid = restored && !isExpired(restored.expiresAt) ? restored : null;
if (restored && !restoredValid) writeStoredSession(null);

export const useAuthStore = create<AuthState>((set) => ({
  token: restoredValid?.token ?? null,
  orgId: restoredValid?.orgId ?? null,
  expiresAt: restoredValid?.expiresAt ?? null,
  loggingIn: false,
  loginError: null,

  async login(operatorId, password) {
    set({ loggingIn: true, loginError: null });

    let response: Response;
    try {
      response = await fetch(`${API_BASE}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          operator_id: operatorId,
          password,
        } satisfies LoginRequestBody),
      });
    } catch {
      // A transport failure here — almost always the server not running —
      // is a distinct message from a rejected login, per this cycle's brief:
      // one is "check your credentials", the other is "check the server".
      set({
        loggingIn: false,
        loginError: `Cannot reach the engine at ${API_BASE}. Is the API server running?`,
      });
      return false;
    }

    if (!response.ok) {
      // `detail` carries the server's own message for every failure shape
      // this route sends — the login route's generic 401 and its 429 rate
      // limit both arrive this way, so no branching on status is needed to
      // show either one correctly, and neither is more specific than the
      // server chose to be.
      let detail = "invalid operator id or password";
      try {
        const body = (await response.json()) as { detail?: unknown };
        if (typeof body.detail === "string" && body.detail) detail = body.detail;
      } catch {
        // A non-JSON error body falls back to the generic message above.
      }
      set({ loggingIn: false, loginError: detail });
      return false;
    }

    const body = (await response.json()) as LoginResponseBody;
    const session: StoredSession = {
      token: body.token,
      orgId: body.org_id,
      expiresAt: body.expires_at,
    };
    writeStoredSession(session);
    setAuthToken(session.token);
    set({
      token: session.token,
      orgId: session.orgId,
      expiresAt: session.expiresAt,
      loggingIn: false,
      loginError: null,
    });
    return true;
  },

  logout() {
    writeStoredSession(null);
    setAuthToken(null);
    set({ token: null, orgId: null, expiresAt: null, loginError: null });
  },
}));

/**
 * Whether the store currently holds a session the server would still accept.
 *
 * A client-side check only — the server is the real one, enforced by
 * `httpAdapter.ts`'s global `401` handling below. This exists so `App` does
 * not flash the dashboard open on a token it can already tell has expired.
 */
export function isSessionValid(state: Pick<AuthState, "token" | "expiresAt">): boolean {
  return state.token !== null && state.expiresAt !== null && !isExpired(state.expiresAt);
}

// The adapter layer cannot import this store back — see the comment on
// `currentToken` in `httpAdapter.ts` for why. These two calls are the other
// half of that seam: the token restored from `localStorage` at start-up, and
// what a `401` anywhere in the app should do, which is always the same thing
// this store's own `logout` already does.
setAuthToken(restoredValid?.token ?? null);
setSessionExpiredHandler(() => useAuthStore.getState().logout());
