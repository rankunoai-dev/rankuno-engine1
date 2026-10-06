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

/**
 * The local launcher's one-time sign-in link (ADR 0033).
 *
 * `scripts/run_local.ps1` opens `http://127.0.0.1:<port>/#autosignin=<token>`.
 * The token rides in the fragment because a browser never sends a fragment to
 * the server, so it reaches no access log. It is read once, at module load and
 * so before any request, stripped from the address bar at once, and held only
 * in this module-local variable until `signInWithLink` posts it. It is never
 * put in store state, in `localStorage`, in a URL, or in a log.
 */
const LINK_PARAM = "autosignin";
const LINK_TOKEN_SHAPE = /^[0-9a-f]{64,256}$/i;
const LINK_FAILED =
  "This sign-in link has expired or was already used. Sign in with your operator id and password.";

let pendingLinkToken: string | null = null;

/**
 * Take a sign-in link's token out of `location.hash`, and out of the address bar.
 *
 * Runs once on module load. Exported so a test can drive it after changing
 * `location`; calling it again with no link in the URL changes nothing.
 */
export function captureSignInLink(): void {
  const hash = window.location.hash;
  if (hash.length < 2) return;
  const params = new URLSearchParams(hash.slice(1));
  if (!params.has(LINK_PARAM)) return;
  const value = params.get(LINK_PARAM) ?? "";
  // Stripped whatever the value, and before anything is sent anywhere, so the
  // link cannot linger in history, a bookmark or a copied address.
  window.history.replaceState(
    window.history.state,
    "",
    window.location.pathname + window.location.search,
  );
  pendingLinkToken = LINK_TOKEN_SHAPE.test(value) ? value : null;
}

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
  /**
   * Exchange a captured launcher sign-in link for a session.
   *
   * Resolves `false` at once, without a request, when there is no link. Any
   * failure falls back to the normal login screen with a generic message.
   */
  signInWithLink: () => Promise<boolean>;
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

captureSignInLink();

const restored = readStoredSession();
// A token already past its own `expires_at` is dropped before it is ever
// attached to a request. The server would reject it anyway with a `401`;
// this only skips the one guaranteed-failing round trip, and the flash of an
// authenticated shell that the global `401` handler would otherwise have to
// tear back down a moment later.
const restoredValid = restored && !isExpired(restored.expiresAt) ? restored : null;
if (restored && !restoredValid) writeStoredSession(null);

export const useAuthStore = create<AuthState>((set) => {
  /** The one path a session takes into this store, from either kind of sign-in. */
  function storeSession(body: LoginResponseBody): void {
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
  }

  return {
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

    storeSession((await response.json()) as LoginResponseBody);
    return true;
  },

  async signInWithLink() {
    const linkToken = pendingLinkToken;
    pendingLinkToken = null;
    if (!linkToken) return false;
    set({ loggingIn: true, loginError: null });
    try {
      const response = await fetch(`${API_BASE}/auth/local-signin`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: linkToken }),
      });
      if (response.ok) {
        storeSession((await response.json()) as LoginResponseBody);
        return true;
      }
    } catch {
      // Unreachable server or an unreadable body: the same fallback as a 401.
    }
    // One message for every failure, the server's 401 and 429 included: the
    // operator's next step is the same either way.
    set({ loggingIn: false, loginError: LINK_FAILED });
    return false;
  },

  logout() {
    writeStoredSession(null);
    setAuthToken(null);
    set({ token: null, orgId: null, expiresAt: null, loginError: null });
  },
  };
});

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
