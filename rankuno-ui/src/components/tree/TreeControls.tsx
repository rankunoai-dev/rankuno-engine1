import { ApartmentOutlined } from "@ant-design/icons";
import type { DashModel } from "../../lib/dashboardModel";
import { REASON_MEANINGS, reasonLabel, type TreeOverlay } from "../../lib/treeOverlay";
import { useDashboardStore } from "../../store/useDashboardStore";

interface Props {
  model: DashModel;
  overlay: TreeOverlay;
  /** Inside the whole-screen view, where the button to open it is redundant. */
  fullScreen?: boolean;
}

/**
 * The cross-check toggle, its reason chips, and the full-screen control.
 *
 * The toggle is disabled — not hidden — when no cross-check is saved, and its
 * tooltip says why. A control that vanishes leaves the analyst wondering
 * whether the feature exists; one that explains itself tells them what to
 * upload.
 *
 * Every reason counts by default. Three-quarters of what Screaming Frog
 * "missed" on gep.com were `?page=N` variants it filters out on purpose, and
 * hiding those by default would rebuild its blind spot inside this tool. They
 * are shown, split, and each can be switched off.
 */
export function TreeControls({ model, overlay, fullScreen = false }: Props): JSX.Element {
  const expandAll = useDashboardStore((state) => state.expandAll);
  const collapseAll = useDashboardStore((state) => state.collapseAll);
  const crossCheckOn = useDashboardStore((state) => state.crossCheckOn);
  const missedOnly = useDashboardStore((state) => state.missedOnly);
  const hiddenReasons = useDashboardStore((state) => state.hiddenReasons);
  const toggleCrossCheck = useDashboardStore((state) => state.toggleCrossCheck);
  const toggleMissedOnly = useDashboardStore((state) => state.toggleMissedOnly);
  const toggleReason = useDashboardStore((state) => state.toggleReason);
  const setFullScreen = useDashboardStore((state) => state.setFullScreen);

  const reasons = Object.entries(overlay.reasons).sort((a, b) => b[1] - a[1]);
  const on = crossCheckOn && overlay.crossCheck;

  return (
    <div className="xctl">
      <div className="xctl-row">
        {/* Depth first, then the overlay: you shape the tree, then compare it
            against something. These used to live in the dashboard's own
            toolbar, which meant the full-screen tree — the view with the most
            rows and the most need to close them — had no way to collapse
            anything. One definition, both views. */}
        <div className="xdepth">
          <button
            type="button"
            className="xbtn"
            title="Open the first level only"
            onClick={() => expandAll(model, 1)}
          >
            L1
          </button>
          <button
            type="button"
            className="xbtn"
            title="Open the first two levels"
            onClick={() => expandAll(model, 2)}
          >
            L2
          </button>
          <button
            type="button"
            className="xbtn"
            title={`Open every section, to the bottom — ${model.nodes.length.toLocaleString()} nodes`}
            onClick={() => expandAll(model, 99)}
          >
            Expand all
          </button>
          <button
            type="button"
            className="xbtn"
            title="Close every section back to the top level"
            onClick={() => collapseAll(model)}
          >
            Collapse all
          </button>
        </div>
        <label
          className={`xtoggle${on ? " on" : ""}${overlay.crossCheck ? "" : " off"}`}
          title={
            overlay.crossCheck
              ? "Mark every page Screaming Frog did not find, and count them per section"
              : overlay.crossCheckUnavailable ?? ""
          }
        >
          <input
            type="checkbox"
            checked={on}
            disabled={!overlay.crossCheck}
            onChange={() => toggleCrossCheck(model)}
          />
          <span>Cross-check</span>
        </label>
        {on && (
          <button
            type="button"
            className={`fchip fx${missedOnly ? " on" : ""}`}
            title="Show only sections and pages Screaming Frog missed"
            onClick={() => toggleMissedOnly(model)}
          >
            <i />
            Missed only
          </button>
        )}
        {/* One slot at the right of the row, two states. Full screen is a place
            you go and a place you come back from, and the way back belonged
            beside the controls rather than only in the overlay's header — the
            header is a strip you scroll away from the moment you start reading
            the tree. */}
        {fullScreen ? (
          <button
            type="button"
            className="xfull"
            title="Back to the tree on the main dashboard"
            onClick={() => setFullScreen(false)}
          >
            <ApartmentOutlined /> Main tree view
          </button>
        ) : (
          <button
            type="button"
            className="xfull"
            title="Open the tree across the whole screen, with per-section totals and the OTHERS breakdown"
            onClick={() => setFullScreen(true)}
          >
            ⛶ Full screen
          </button>
        )}
      </div>
      {on && reasons.length > 0 && (
        <div className="xctl-row xreasons">
          {reasons.map(([reason, count]) => {
            const hidden = hiddenReasons.has(reason);
            return (
              <button
                key={reason}
                type="button"
                className={`fchip fx${hidden ? "" : " on"}`}
                title={`${REASON_MEANINGS[reason] ?? reason} — ${count.toLocaleString()} pages. Click to ${hidden ? "count" : "stop counting"} these.`}
                onClick={() => toggleReason(reason)}
              >
                <i />
                {reasonLabel(reason)} · {count.toLocaleString()}
              </button>
            );
          })}
        </div>
      )}
      {!overlay.crossCheck && !fullScreen && (
        <div className="xnote">{overlay.crossCheckUnavailable}</div>
      )}
    </div>
  );
}
