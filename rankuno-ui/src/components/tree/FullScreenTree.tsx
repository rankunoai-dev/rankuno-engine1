import { useEffect } from "react";
import { createPortal } from "react-dom";
import type { DashModel } from "../../lib/dashboardModel";
import type { TreeOverlay } from "../../lib/treeOverlay";
import { useCrawlStore } from "../../store/useCrawlStore";
import { useDashboardStore } from "../../store/useDashboardStore";
import { OthersInsight } from "./OthersInsight";
import { SectionCards } from "./SectionCards";
import { TreeControls } from "./TreeControls";
import { TreeList } from "./VirtualizedTree";

interface Props {
  model: DashModel;
  overlay: TreeOverlay;
}

/**
 * The directory tree across the whole screen, with section totals and the
 * OTHERS breakdown beside it.
 *
 * A portal onto `document.body` rather than a route or a layout change. The
 * shell's grid gives the tree a 400px column, and the totals need width the
 * column does not have; taking the viewport for the duration is the smallest
 * change that gives it. The tree inside is the same windowed list, reading the
 * same expansion and focus state — closing this returns to the shell exactly
 * as it was.
 */
export function FullScreenTree({ model, overlay }: Props): JSX.Element | null {
  const fullScreen = useDashboardStore((state) => state.fullScreen);
  const setFullScreen = useDashboardStore((state) => state.setFullScreen);
  const flat = useDashboardStore((state) => state.flat);
  const baseUrl = useCrawlStore((state) => state.result?.base_url ?? "");

  useEffect(() => {
    if (!fullScreen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setFullScreen(false);
    };
    window.addEventListener("keydown", onKey);
    // The page behind must not scroll under the overlay.
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [fullScreen, setFullScreen]);

  if (!fullScreen) return null;

  return createPortal(
    <div className="xfs" role="dialog" aria-label="Directory tree, full screen">
      <div className="xfs-head">
        <h2>
          Directory tree <span className="dim">· {baseUrl}</span>
        </h2>
        <span className="dim">
          {model.nodes.length.toLocaleString()} nodes · {flat.length.toLocaleString()} rows in view
        </span>
        <button type="button" className="xclose" onClick={() => setFullScreen(false)} title="Close (Esc)">
          ✕ Close
        </button>
      </div>
      <div className="xfs-body">
        <div className="xfs-left">
          <SectionCards model={model} overlay={overlay} />
          <div className="xfs-tree">
            <TreeControls model={model} overlay={overlay} fullScreen />
            <TreeList model={model} wide />
          </div>
        </div>
        <div className="xfs-right">
          <OthersInsight model={model} overlay={overlay} />
        </div>
      </div>
    </div>,
    document.body,
  );
}
