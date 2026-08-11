import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { LANE_LABELS, OTHERS_LANE, type DashModel } from "../../lib/dashboardModel";
import { useDashboardStore } from "../../store/useDashboardStore";
import { BreadcrumbBar } from "./BreadcrumbBar";

/** Children drawn per page. Beyond this the lane stops being readable. */
const PAGE_SIZE = 10;

/** Children per row within a lane before wrapping. */
const COLUMNS = 5;

const NODE_CLASS = ["g0", "g1", "g2", "g3", "go"];
const LANE_CLASS = ["ln0", "ln1", "ln2", "ln3", "lno"];

interface Point {
  x: number;
  y: number;
}

interface Props {
  model: DashModel;
}

/**
 * The focus-mode graph: the selected node's neighbourhood, not the whole site.
 *
 * Drawing 20,000 nodes is not a layout problem to solve, it is a view nobody can
 * read. This renders the ancestor chain down to the selection plus one page of
 * its children — a dozen or so nodes — and re-centres as the user walks the
 * tree. The hint in the corner states how many of the total are on screen, so
 * the partial view is never mistaken for the whole.
 *
 * Lane geometry is measured from the DOM after layout rather than computed,
 * because the lanes are flexbox children whose heights change when one expands.
 */
export function FocusGraphStage({ model }: Props): JSX.Element {
  const focus = useDashboardStore((state) => state.focus);
  const laneFilter = useDashboardStore((state) => state.laneFilter);
  const methodFilter = useDashboardStore((state) => state.methodFilter);
  const setFocus = useDashboardStore((state) => state.setFocus);
  const childPage = useDashboardStore((state) => state.childPage);
  const nextChildPage = useDashboardStore((state) => state.nextChildPage);

  const stage = useRef<HTMLDivElement>(null);
  const lanes = useRef<HTMLDivElement>(null);
  const [geometry, setGeometry] = useState<{ centres: number[]; width: number }>({
    centres: [],
    width: 0,
  });

  const node = focus === null ? null : model.nodes[focus];

  const chain: number[] = [];
  if (node) {
    let cursor: number | null = node.i;
    while (cursor !== null) {
      chain.unshift(cursor);
      cursor = model.nodes[cursor]?.p ?? null;
    }
  }

  const visibleKids = (node?.kids ?? []).filter((kid) => {
    const child = model.nodes[kid];
    if (!child || !laneFilter.has(child.lv)) return false;
    return !child.profile || methodFilter.has(child.profile.consensus_method);
  });

  const page = (focus !== null ? childPage[focus] : 0) ?? 0;
  const pageCount = Math.max(1, Math.ceil(visibleKids.length / PAGE_SIZE));
  const safePage = page % pageCount;
  const shown = visibleKids.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE);
  const remaining = visibleKids.length - (safePage * PAGE_SIZE + shown.length);

  const expandedLane = shown.length > 0 ? model.nodes[shown[0]!]!.lv : (node?.lv ?? 0);

  const measure = useCallback(() => {
    const stageElement = stage.current;
    const laneElements = lanes.current?.querySelectorAll(".lane");
    if (!stageElement || !laneElements) return;

    const stageBox = stageElement.getBoundingClientRect();
    const centres: number[] = [];
    laneElements.forEach((lane) => {
      const box = lane.getBoundingClientRect();
      centres.push(box.top - stageBox.top + box.height / 2);
    });
    setGeometry({ centres, width: stageElement.clientWidth });
  }, []);

  // Measured after the browser has laid out the expanded lane, and again when
  // the CSS `flex` transition finishes — otherwise the wires are drawn against
  // the pre-expansion geometry and visibly miss their nodes.
  useLayoutEffect(() => {
    const frame = requestAnimationFrame(measure);
    const settle = setTimeout(measure, 280);
    return () => {
      cancelAnimationFrame(frame);
      clearTimeout(settle);
    };
  }, [measure, expandedLane, focus, safePage]);

  useEffect(() => {
    const onResize = (): void => {
      requestAnimationFrame(measure);
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [measure]);

  const positions = new Map<number, Point>();
  const { centres, width } = geometry;

  if (centres.length > 0 && width > 0) {
    chain.forEach((index, position) => {
      const lane = model.nodes[index]!.lv;
      const x =
        chain.length === 1 ? width / 2 : Math.min(90 + position * (width * 0.28), width - 140);
      positions.set(index, { x, y: centres[lane] ?? 0 });
    });

    const rows = Math.ceil(shown.length / COLUMNS) || 1;
    shown.forEach((kid, position) => {
      const lane = model.nodes[kid]!.lv;
      const columns = Math.min(shown.length, COLUMNS);
      const row = Math.floor(position / columns);
      const column = position % columns;
      positions.set(kid, {
        x: ((width - 100) / (columns + 1)) * (column + 1) + 70,
        y: (centres[lane] ?? 0) + (row - (rows - 1) / 2) * 44,
      });
    });
  }

  const wires: JSX.Element[] = [];
  for (let position = 1; position < chain.length; position += 1) {
    const from = positions.get(chain[position - 1]!);
    const to = positions.get(chain[position]!);
    if (from && to) {
      wires.push(
        <path
          key={`chain-${position}`}
          className={chain[position] === focus ? "wire hot" : "wire"}
          d={bezier(from, to)}
        />,
      );
    }
  }
  const focusPoint = focus === null ? undefined : positions.get(focus);
  if (focusPoint) {
    for (const kid of shown) {
      const to = positions.get(kid);
      if (to) wires.push(<path key={`kid-${kid}`} className="wire" d={bezier(focusPoint, to)} />);
    }
  }

  return (
    <>
      <BreadcrumbBar model={model} chain={chain} childCount={visibleKids.length} />

      <div className="stage" ref={stage}>
        <div className="lanes" ref={lanes}>
          {LANE_LABELS.map((label, lane) => (
            <div
              key={label}
              className={`lane ${LANE_CLASS[lane]}${lane === expandedLane ? " big" : ""}`}
              data-lv={lane}
            >
              <div className="tab">{label}</div>
              <div className="band" />
            </div>
          ))}
        </div>

        <svg className="wires">
          <g>{wires}</g>
        </svg>

        <div>
          {[...chain, ...shown].map((index) => {
            const point = positions.get(index);
            const entry = model.nodes[index];
            if (!point || !entry) return null;
            return (
              <button
                key={index}
                type="button"
                className={`gn ${NODE_CLASS[entry.lv]}${index === focus ? " sel" : ""}`}
                style={{ left: point.x, top: point.y }}
                onClick={() => setFocus(index, model)}
              >
                <div className="gt">{entry.label}</div>
                <div className="gu">{entry.url}</div>
              </button>
            );
          })}

          {(remaining > 0 || safePage > 0) && focusPoint && (
            <button
              type="button"
              className="gn pager"
              style={{
                left: width - 110,
                top: (centres[expandedLane] ?? 0) + Math.ceil(shown.length / COLUMNS) * 30,
              }}
              onClick={() => focus !== null && nextChildPage(focus, pageCount)}
            >
              <div className="gt">
                {remaining > 0 ? `+ ${remaining.toLocaleString()} more →` : "↺ first page"}
              </div>
              <div className="gu">
                page {safePage + 1} / {pageCount}
              </div>
            </button>
          )}
        </div>

        <div className="hint">
          rendered {chain.length + shown.length} of {model.nodes.length.toLocaleString()} nodes
        </div>
      </div>
    </>
  );
}

/**
 * A vertical cubic bezier between two node centres.
 *
 * Control points sit at the vertical midpoint, so the curve leaves the parent
 * downward and enters the child downward regardless of horizontal offset. The
 * ±14px keeps the endpoints off the node borders.
 */
function bezier(from: Point, to: Point): string {
  const mid = (from.y + to.y) / 2;
  return `M${from.x},${from.y + 14} C${from.x},${mid} ${to.x},${mid} ${to.x},${to.y - 16}`;
}

export { OTHERS_LANE };
