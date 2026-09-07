import { useState } from "react";
import type { DashModel } from "../../lib/dashboardModel";
import { reasonLabel, type RootSummary, type TreeOverlay } from "../../lib/treeOverlay";
import { useDashboardStore } from "../../store/useDashboardStore";

interface Props {
  model: DashModel;
  overlay: TreeOverlay;
}

type SortKey = "missed" | "clicks" | "pages";

/**
 * One card per top-level section, with what the cross-check and Search Console
 * say about it.
 *
 * Sortable because the number of sections is not small: gep.com has 10 plus a
 * locale root per language, and highradius.com has 114. Sorted by misses when
 * a cross-check is on, since that is what the view was opened to find, and by
 * pages otherwise.
 */
export function SectionCards({ model, overlay }: Props): JSX.Element {
  const crossCheckOn = useDashboardStore((state) => state.crossCheckOn);
  const setFocus = useDashboardStore((state) => state.setFocus);
  const showMisses = crossCheckOn && overlay.crossCheck;
  const [sort, setSort] = useState<SortKey | null>(null);
  const key: SortKey = sort ?? (showMisses ? "missed" : overlay.gsc ? "clicks" : "pages");

  const roots = [...overlay.roots].sort((a, b) => b[key] - a[key] || b.pages - a.pages);

  return (
    <div className="xcards">
      <div className="xcards-head">
        <h3>Sections · {overlay.roots.length.toLocaleString()}</h3>
        <div className="xsort">
          sort by
          {(["missed", "clicks", "pages"] as SortKey[])
            .filter((option) => option !== "missed" || showMisses)
            .filter((option) => option !== "clicks" || overlay.gsc)
            .map((option) => (
              <button
                key={option}
                type="button"
                className={`fchip fx${key === option ? " on" : ""}`}
                onClick={() => setSort(option)}
              >
                <i />
                {option}
              </button>
            ))}
        </div>
      </div>
      <div className="xcards-grid">
        {roots.map((root) => (
          <SectionCard
            key={root.i}
            root={root}
            showMisses={showMisses}
            showGsc={overlay.gsc}
            onOpen={() => setFocus(root.i, model)}
          />
        ))}
      </div>
    </div>
  );
}

function SectionCard({
  root,
  showMisses,
  showGsc,
  onOpen,
}: {
  root: RootSummary;
  showMisses: boolean;
  showGsc: boolean;
  onOpen: () => void;
}): JSX.Element {
  const share = root.pages > 0 ? root.missed / root.pages : 0;
  const reasons = Object.entries(root.missedByReason).sort((a, b) => b[1] - a[1]);
  return (
    <button type="button" className="xcard" onClick={onOpen} title="Focus this section in the tree">
      <div className="xcard-title">{root.label}</div>
      <div className="xcard-pages">{root.pages.toLocaleString()} pages</div>
      {showMisses && (
        <div className={`xcard-miss${root.missed > 0 ? " has" : ""}`}>
          <b>{root.missed.toLocaleString()}</b> missed by Screaming Frog
          {root.pages > 0 && <span className="dim"> · {Math.round(share * 100)}%</span>}
          {reasons.length > 0 && (
            <div className="xcard-reasons">
              {reasons.map(([reason, count]) => (
                <span key={reason}>
                  {reasonLabel(reason)} {count.toLocaleString()}
                </span>
              ))}
            </div>
          )}
          {root.added > 0 && (
            <div className="xcard-added">{root.added.toLocaleString()} added from Screaming Frog</div>
          )}
        </div>
      )}
      {showGsc && (
        <div className="xcard-gsc">
          <span>
            <b>{root.clicks.toLocaleString()}</b> clicks
          </span>
          <span>{root.impressions.toLocaleString()} impr.</span>
          <span className="dim">
            {root.gscPages.toLocaleString()} / {root.pages.toLocaleString()} with GSC rows
          </span>
        </div>
      )}
      {root.topTypes.length > 0 && (
        <div className="xcard-types">
          {root.topTypes.map(([type, count]) => (
            <span key={type}>
              {type} <b>{count.toLocaleString()}</b>
            </span>
          ))}
        </div>
      )}
    </button>
  );
}
