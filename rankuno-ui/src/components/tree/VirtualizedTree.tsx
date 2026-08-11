import { useCallback, useEffect, useRef, useState } from "react";
import { LANE_LABELS, type DashModel } from "../../lib/dashboardModel";
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
        <span className={`lvchip ${LANE_CLASS[node.lv]}`}>{LANE_LABELS[node.lv]}</span>
        <span className="tlbl">{node.label}</span>
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
