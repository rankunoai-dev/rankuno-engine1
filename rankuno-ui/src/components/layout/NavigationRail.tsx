import { isLive, useCrawlStore } from "../../store/useCrawlStore";
import { useAuthStore } from "../../store/useAuthStore";
import { selectMode, useUiStore } from "../../store/useUiStore";

/**
 * Left icon rail.
 *
 * Shows one product at a time. Launch and Log out are always present — Launch
 * is how the operator switches product. In engine mode the engine's
 * destinations follow; in Screaming Frog mode only the Screaming Frog view
 * does. Hidden entries are not rendered at all, rather than faded, so keyboard
 * and screen-reader users cannot tab into a destination that is not on screen.
 *
 * Unimplemented entries ("Dashboard") are rendered `disabled` with a title
 * saying so, rather than as live buttons that do nothing — a control that
 * looks clickable and silently ignores the click reads as a bug.
 */
export function NavigationRail(): JSX.Element {
  const view = useUiStore((state) => state.view);
  const mode = useUiStore(selectMode);
  const setView = useUiStore((state) => state.setView);
  const liveJobs = useCrawlStore((state) => state.liveJobs);
  // `null` in offline/fixture mode, which never logged in and has nothing to
  // log out of — the button below is conditional on this for that reason,
  // not merely to hide it while `App` is still choosing an adapter.
  const token = useAuthStore((state) => state.token);
  const logout = useAuthStore((state) => state.logout);

  const running = Object.values(liveJobs).filter(isLive).length;

  return (
    <nav className="rail" aria-label="Primary">
      <div className="mark">R</div>

      {/* First, and the opening view: a session starts with nothing loaded,
          and this is the screen that says which of the two crawlers you are
          about to use. */}
      <button
        className={`rit${view === "launch" ? " on" : ""}`}
        type="button"
        onClick={() => setView("launch")}
        {...(view === "launch" ? { "aria-current": "page" as const } : {})}
      >
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 2.5c3.5 2.2 5.5 6 5.5 10l-2 3h-7l-2-3c0-4 2-7.8 5.5-10z" />
          <circle cx="12" cy="9.5" r="2" />
          <path d="M9 19c0 1.4.9 2.5 3 2.5s3-1.1 3-2.5" />
        </svg>
        Launch
      </button>

      {mode === "engine" && (
        <>
          <button
            className={`rit${view === "visualizer" ? " on" : ""}`}
            type="button"
            onClick={() => setView("visualizer")}
            {...(view === "visualizer" ? { "aria-current": "page" as const } : {})}
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <circle cx="5" cy="6" r="2.5" />
              <circle cx="19" cy="6" r="2.5" />
              <circle cx="12" cy="18" r="2.5" />
              <path d="M7 7.5l3.5 8M17 7.5l-3.5 8" />
            </svg>
            Visualizer
          </button>

          <button
            className={`rit${view === "jobs" ? " on" : ""}`}
            type="button"
            onClick={() => setView("jobs")}
            {...(view === "jobs" ? { "aria-current": "page" as const } : {})}
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M13 2L4.5 13.5H11l-1 8.5 8.5-11.5H12l1-8.5z" />
            </svg>
            Crawl jobs
            {running > 0 && (
              // Announced, not merely drawn. A screen reader user gets nothing
              // from a glowing dot. In Screaming Frog mode this item is not
              // rendered; the header's background pill and the completion
              // toasts from `CrawlNotifier` carry the running crawl instead.
              <span className="rit-badge" aria-label={`${running} crawls running`}>
                {running}
              </span>
            )}
          </button>

          <button className="rit" type="button" disabled title="Not implemented yet">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <rect x="3" y="3" width="7" height="9" rx="1.5" />
              <rect x="14" y="3" width="7" height="5" rx="1.5" />
              <rect x="14" y="12" width="7" height="9" rx="1.5" />
              <rect x="3" y="16" width="7" height="5" rx="1.5" />
            </svg>
            Dashboard
          </button>

          <button
            className={`rit${view === "audit" ? " on" : ""}`}
            type="button"
            onClick={() => setView("audit")}
            {...(view === "audit" ? { "aria-current": "page" as const } : {})}
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <path d="M3 9h18M3 15h18M9 3v18M15 3v18" />
            </svg>
            Audit
          </button>

          <button
            className={`rit${view === "gsc-accounts" ? " on" : ""}`}
            type="button"
            onClick={() => setView("gsc-accounts")}
            {...(view === "gsc-accounts" ? { "aria-current": "page" as const } : {})}
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <circle cx="12" cy="8" r="3" />
              <path d="M12 14c-3.31 0-5 1.67-5 5v2h10v-2c0-3.33-1.69-5-5-5z" />
              <path d="M19 2l.47 1.41L21 3.88l-1.42.47L19 6l-.47-1.41L17 3.88l1.42-.47L19 2z" />
            </svg>
            GSC Accounts
          </button>
        </>
      )}

      {mode === "screaming-frog" && (
        <>
          {/* Its own destination, not a tab inside "Crawl jobs". These are a
              separate job system — different ids, different statuses, different
              endpoints — and one table holding both would invite reading a
              Screaming Frog dispatch as an engine crawl. */}
          <button
            className={`rit${view === "screaming-frog" ? " on" : ""}`}
            type="button"
            onClick={() => setView("screaming-frog")}
            {...(view === "screaming-frog" ? { "aria-current": "page" as const } : {})}
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <rect x="2.5" y="4" width="19" height="12" rx="1.5" />
              <path d="M8 20h8M12 16v4" />
              <path d="M7.5 10.5l2.5-2.5 2 2 2.5-3 2 2.5" />
            </svg>
            Screaming Frog
          </button>
        </>
      )}

      {/* Only shown once there is a session to end — `token` is `null` in
          offline/fixture mode, which never went through `/auth/login` and
          has no server-side identity for this to sign out of. */}
      {token !== null && (
        <button
          className="rit rit-logout"
          type="button"
          onClick={() => logout()}
          title="Sign out"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M15 4H6a2 2 0 00-2 2v12a2 2 0 002 2h9" />
            <path d="M10 12h10m0 0l-3.5-3.5M20 12l-3.5 3.5" />
          </svg>
          Log out
        </button>
      )}
    </nav>
  );
}
