import { isLive, useCrawlStore } from "../../store/useCrawlStore";
import { useUiStore } from "../../store/useUiStore";

/**
 * Left icon rail.
 *
 * "Visualizer" and "Crawl jobs" are implemented. The other entries are rendered
 * `disabled` with a title saying so, rather than as live buttons that do
 * nothing — a control that looks clickable and silently ignores the click reads
 * as a bug.
 */
export function NavigationRail(): JSX.Element {
  const view = useUiStore((state) => state.view);
  const setView = useUiStore((state) => state.setView);
  const liveJobs = useCrawlStore((state) => state.liveJobs);

  const running = Object.values(liveJobs).filter(isLive).length;

  return (
    <nav className="rail" aria-label="Primary">
      <div className="mark">R</div>

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
          // Announced, not merely drawn. The badge is the only indication that a
          // background crawl exists while the operator is on another tab, and a
          // screen reader user gets nothing from a glowing dot.
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

      <button className="rit" type="button" disabled title="Not implemented yet">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <rect x="3" y="3" width="18" height="18" rx="2" />
          <path d="M3 9h18M3 15h18M9 3v18M15 3v18" />
        </svg>
        Audit
      </button>
    </nav>
  );
}
