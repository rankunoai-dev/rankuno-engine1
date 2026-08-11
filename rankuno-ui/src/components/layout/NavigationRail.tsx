/**
 * Left icon rail.
 *
 * Only "Visualizer" is implemented. The other entries are rendered `disabled`
 * with a title saying so, rather than as live buttons that do nothing — a
 * control that looks clickable and silently ignores the click reads as a bug.
 */
export function NavigationRail(): JSX.Element {
  return (
    <nav className="rail" aria-label="Primary">
      <div className="mark">R</div>

      <button className="rit on" type="button" aria-current="page">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="5" cy="6" r="2.5" />
          <circle cx="19" cy="6" r="2.5" />
          <circle cx="12" cy="18" r="2.5" />
          <path d="M7 7.5l3.5 8M17 7.5l-3.5 8" />
        </svg>
        Visualizer
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
