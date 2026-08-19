import { useCallback, useEffect, useRef, useState } from "react";
import {
  LEVEL_BADGE,
  TRAIL_SOURCE_BADGE,
  type DashModel,
  type DashNode,
} from "../../lib/dashboardModel";
import { useDashboardStore } from "../../store/useDashboardStore";

/** Row height in pixels. Fixed, which is what makes the window arithmetic O(1). */
const ROW = 30;

/** Rows rendered beyond each edge of the viewport, to hide scroll latency. */
const OVERSCAN = 3;

const LANE_CLASS = ["p0", "p1", "p2", "p3", "po"];

interface Props {
  model: DashModel;
}

/**
 * The directory tree, windowed to roughly 25 rows in the DOM.
 *
 * Only rows intersecting the viewport are mounted; the rest exist solely as
 * scroll height on a spacer. Without this the tree mounts 20,000 rows on first
 * paint and the tab stops responding — the failure is total rather than gradual,
 * which is why this is the one component in the app with hand-written
 * virtualization rather than a library.
 *
 * The flattened view-model lives in the store and is rebuilt only when the tree
 * or a filter changes. Rebuilding it per scroll frame would defeat the point.
 */
export function VirtualizedTree({ model }: Props): JSX.Element {
  const flat = useDashboardStore((state) => state.flat);
  const open = useDashboardStore((state) => state.open);
  const focus = useDashboardStore((state) => state.focus);
  const toggleOpen = useDashboardStore((state) => state.toggleOpen);
  const setFocus = useDashboardStore((state) => state.setFocus);

  const viewport = useRef<HTMLDivElement>(null);
  const [range, setRange] = useState({ start: 0, end: 40 });

  const recompute = useCallback(() => {
    const element = viewport.current;
    if (!element) return;
    const start = Math.max(0, Math.floor(element.scrollTop / ROW) - OVERSCAN);
    const end = Math.min(
      flat.length,
      Math.ceil((element.scrollTop + element.clientHeight) / ROW) + OVERSCAN,
    );
    setRange((previous) =>
      previous.start === start && previous.end === end ? previous : { start, end },
    );
  }, [flat.length]);

  useEffect(recompute, [recompute, flat]);

  // Scroll the focused row into view when selection arrives from elsewhere —
  // teleport search, a graph node, a breadcrumb. Without this, selecting a node
  // 12,000 rows down highlights a row nobody can see.
  useEffect(() => {
    const element = viewport.current;
    if (!element || focus === null) return;
    const position = flat.findIndex((row) => row.i === focus);
    if (position < 0) return;

    const top = position * ROW;
    const visible = top >= element.scrollTop && top + ROW <= element.scrollTop + element.clientHeight;
    if (!visible) {
      element.scrollTop = Math.max(0, top - element.clientHeight / 2);
      recompute();
    }
  }, [focus, flat, recompute]);

  const onScroll = useCallback(() => {
    // rAF-coalesced: a trackpad fires scroll far more often than the browser
    // paints, and setting state per event drops frames for no visual gain.
    requestAnimationFrame(recompute);
  }, [recompute]);

  const rows = [];
  for (let position = range.start; position < range.end; position += 1) {
    const row = flat[position];
    if (!row) continue;
    const node = model.nodes[row.i];
    if (!node) continue;

    const hasChildren = node.kids.length > 0;
    rows.push(
      <button
        key={node.i}
        type="button"
        className={`vrow${focus === node.i ? " sel" : ""}`}
        style={{ top: position * ROW, paddingLeft: 10 + row.depth * 16 }}
        onClick={() => setFocus(node.i, model)}
      >
        <span
          className={`tw${open.has(node.i) ? " open" : ""}`}
          onClick={(event) => {
            // Stop the row's own select handler: expanding a branch and moving
            // the focus are different intentions.
            event.stopPropagation();
            toggleOpen(node.i, model);
          }}
        >
          {hasChildren ? "▶" : ""}
        </span>
        <LevelChip node={node} />
        <span className="tlbl">{node.label}</span>
        {/* Only on section headers. On a leaf the badge would repeat on every
            row and stop carrying information; the drawer states it per page. */}
        {hasChildren && model.hasProvenance && (
          <span
            className={`srcdot src-${node.src}`}
            title={`Section built from: ${TRAIL_SOURCE_BADGE[node.src]}`}
          >
            {TRAIL_SOURCE_BADGE[node.src]}
          </span>
        )}
        {hasChildren && <span className="tcnt">{node.cnt.toLocaleString()}</span>}
      </button>,
    );
  }

  return (
    <>
      <div className="vtree" ref={viewport} onScroll={onScroll}>
        <div className="vspacer" style={{ height: flat.length * ROW }}>
          {rows}
        </div>
      </div>
      <div className="treefoot">
        <span>{flat.length.toLocaleString()} rows in view-model</span>
        <span>
          DOM rows: <b>{rows.length}</b> / {model.nodes.length.toLocaleString()}
        </span>
      </div>
    </>
  );
}

/**
 * The level badge for one row.
 *
 * Reads the engine's `hierarchy_level` when the page was classified, and falls
 * back to the lane only for a node the crawl never produced a profile for —
 * an intermediate path segment that is not itself a page.
 *
 * This used to render the lane unconditionally. With no header menu the lane is
 * URL-path depth, so every single-segment URL on a flat site showed `L0` while
 * the engine had classified it `L3_LEAF_PAGE`. The correct answer was already
 * in the payload; the row was showing a different number.
 */
function LevelChip({ node }: { node: DashNode }): JSX.Element {
  const level = node.profile?.hierarchy_level;

  // No profile means no page was crawled at this URL — it is a path segment
  // the tree needed in order to hold its children. It gets a neutral mark, not
  // a level.
  //
  // It used to fall back to the lane number, which produced the collision that
  // exposed this: under `global-presence`, the crawled entries showed `L3`
  // (their classification) while the uncrawled `asia` showed `L1` (its depth).
  // Two different scales in identically-shaped chips reads as a hierarchy
  // error, and there is no way to tell from the chip which scale you are
  // looking at.
  if (level === undefined) {
    return (
      <span
        className="lvchip lvpath"
        title="URL path segment — no page was crawled at this address"
      >
        ·
      </span>
    );
  }

  const badge = LEVEL_BADGE[level];
  return (
    <span className={`lvchip ${LANE_CLASS[badge.lane]}`} title={`Classified ${level}`}>
      {badge.label}
    </span>
  );
}
