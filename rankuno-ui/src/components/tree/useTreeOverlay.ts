import { useEffect, useMemo } from "react";
import type { DashModel } from "../../lib/dashboardModel";
import { buildTreeOverlay, type TreeOverlay } from "../../lib/treeOverlay";
import { useCrawlStore } from "../../store/useCrawlStore";
import { useDashboardStore } from "../../store/useDashboardStore";

/**
 * Build the overlay for `model` and publish it to the dashboard store.
 *
 * Called from exactly one mounted component — the tree — so the overlay is
 * computed once per model, cross-check or reason change and not once per
 * consumer. The full-screen view and the inspector read it from the store.
 *
 * Returned as well as published, so the caller can render from it on the same
 * frame rather than waiting for the store round-trip.
 */
export function useTreeOverlay(model: DashModel): TreeOverlay {
  const reconciliation = useCrawlStore((state) => state.reconciliation);
  const hiddenReasons = useDashboardStore((state) => state.hiddenReasons);
  const setOverlay = useDashboardStore((state) => state.setOverlay);

  const overlay = useMemo(
    () => buildTreeOverlay(model, reconciliation, hiddenReasons),
    [model, reconciliation, hiddenReasons],
  );

  useEffect(() => {
    setOverlay(overlay, model);
  }, [overlay, model, setOverlay]);

  return overlay;
}

/**
 * The overlay to draw for `model`, or `null` when nothing should be drawn.
 *
 * `null` when the toggle is off, and when the stored overlay belongs to a
 * previous model — its indices would then point at the wrong rows.
 */
export function useActiveOverlay(model: DashModel): TreeOverlay | null {
  const overlay = useDashboardStore((state) => state.overlay);
  const crossCheckOn = useDashboardStore((state) => state.crossCheckOn);
  if (!crossCheckOn || !overlay || overlay.model !== model) return null;
  return overlay;
}
