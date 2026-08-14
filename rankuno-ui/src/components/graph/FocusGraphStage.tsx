import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  confidenceBand,
  LANE_LABELS,
  OTHERS_LANE,
  type DashModel,
} from "../../lib/dashboardModel";
import { useDashboardStore } from "../../store/useDashboardStore";
import { BreadcrumbBar } from "./BreadcrumbBar";

/** Children drawn per page. Beyond this the lane stops being readable. */
const PAGE_SIZE = 10;

/** Widest a node card may be, matching `.gn { max-width }`. */
const CARD_WIDTH = 180;

/** Clear space between two cards in the same row. */
const CARD_GUTTER = 14;

/** Width of the lane's vertical label tab, which cards must not sit under. */
const LANE_TAB_WIDTH = 30;

/** Vertical distance between wrapped rows inside one lane. */
const ROW_HEIGHT = 52;

/** Breathing room above and below the rows in an expanded lane. */
const LANE_PADDING = 28;

/** Smallest a collapsed lane may become. Mirrors `.lane { min-height }`. */
const LANE_MIN_HEIGHT = 28;

/** Gap between lanes, mirroring `.lanes { gap }`. */
const LANE_GAP = 7;

/** `.lanes { inset: 10px }`, top and bottom. */
const LANES_INSET = 20;

/** Lanes drawn, one per navigation depth plus OTHERS. */
const LANE_COUNT = 5;

/**
 * Columns that fit in `width` without overlapping.
 *
 * Fixed columns overlap on a narrow stage: five 180px cards need 970px of
 * usable width, and below that they were drawn on top of each other with their
 * labels running together. Wrapping to fewer columns is readable; overlapping
 * never is.
 */
function columnsFor(width: number, count: number): number {
  const usable = Math.max(0, width - LANE_TAB_WIDTH * 2);
  const fits = Math.max(1, Math.floor(usable / (CARD_WIDTH + CARD_GUTTER)));
  return Math.max(1, Math.min(count, fits));
}

/** Keep a card's centre inside the stage, clear of the lane tab. */
function clampX(x: number, width: number): number {
  const half = CARD_WIDTH / 2;
  const min = LANE_TAB_WIDTH + half + 6;
  const max = Math.max(min, width - half - 6);
  return Math.min(Math.max(x, min), max);
}

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
  const bandFilter = useDashboardStore((state) => state.bandFilter);
  const setFocus = useDashboardStore((state) => state.setFocus);
  const childPage = useDashboardStore((state) => state.childPage);
  const nextChildPage = useDashboardStore((state) => state.nextChildPage);

  const stage = useRef<HTMLDivElement>(null);
  const lanes = useRef<HTMLDivElement>(null);
  const [geometry, setGeometry] = useState<{
    centres: number[];
    heights: number[];
    width: number;
    height: number;
  }>({ centres: [], heights: [], width: 0, height: 0 });

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
    return !child.profile || bandFilter.has(confidenceBand(child.profile));
  });

  const page = (focus !== null ? childPage[focus] : 0) ?? 0;
  const pageCount = Math.max(1, Math.ceil(visibleKids.length / PAGE_SIZE));
  const safePage = page % pageCount;
  const shown = visibleKids.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE);
  const remaining = visibleKids.length - (safePage * PAGE_SIZE + shown.length);

  const expandedLane = shown.length > 0 ? model.nodes[shown[0]!]!.lv : (node?.lv ?? 0);

  // Computed before layout, because the expanded lane has to be *sized* to the
  // rows it will hold. A fixed `flex: 2.2` fits one row; a second row of cards
  // then spilled out of the band and over the lane below it.
  //
  // `width` is 0 on the first paint, before the stage has been measured. A
  // typical stage width is assumed for that one frame so the lane does not
  // start at its one-column height and visibly jump.
  const columns = columnsFor(geometry.width || 900, shown.length);
  const rowCount = Math.max(1, Math.ceil(shown.length / columns));
  // Capped at exactly what is left once the other lanes take their minimum, so
  // a tall expanded lane can never push the bottom band out of the stage. A
  // fractional cap looked safe and was not: at five lanes it still overflowed.
  const spareForExpanded =
    (geometry.height || 320) -
    LANES_INSET -
    LANE_GAP * (LANE_COUNT - 1) -
    LANE_MIN_HEIGHT * (LANE_COUNT - 1);
  const expandedLaneHeight = Math.min(
    rowCount * ROW_HEIGHT + LANE_PADDING,
    Math.max(ROW_HEIGHT + LANE_PADDING, spareForExpanded),
  );

  const measure = useCallback(() => {
    const stageElement = stage.current;
    const laneElements = lanes.current?.querySelectorAll(".lane");
    if (!stageElement || !laneElements) return;

    const stageBox = stageElement.getBoundingClientRect();
    const centres: number[] = [];
    const heights: number[] = [];
    laneElements.forEach((lane) => {
      const box = lane.getBoundingClientRect();
      centres.push(box.top - stageBox.top + box.height / 2);
      heights.push(box.height);
    });
    setGeometry({
      centres,
      heights,
      width: stageElement.clientWidth,
      height: stageElement.clientHeight,
    });
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
  }, [measure, expandedLane, focus, safePage, rowCount]);

  useEffect(() => {
    const onResize = (): void => {
      requestAnimationFrame(measure);
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [measure]);

  const positions = new Map<number, Point>();
  const { centres, heights, width } = geometry;

  // Derived from the height the lane actually ended up with, not from the
  // height that was asked for. When the cap above bites, the rows compress to
  // fit rather than spilling into the lane below — which is what put a second
  // row of L2 cards on top of the L3 band.
  const laneHeight = heights[expandedLane] ?? 0;
  const rowSpacing =
    laneHeight > 0
      ? Math.min(ROW_HEIGHT, Math.max(24, (laneHeight - 16) / rowCount))
      : ROW_HEIGHT;

  if (centres.length > 0 && width > 0) {
    chain.forEach((index, position) => {
      const lane = model.nodes[index]!.lv;
      // Spread across the usable width rather than by a fixed step, so a long
      // ancestor chain does not run off the right edge or under the lane tab.
      const span = width - LANE_TAB_WIDTH * 2 - CARD_WIDTH;
      const step = chain.length > 1 ? span / (chain.length - 1) : 0;
      const raw =
        chain.length === 1
          ? width / 2
          : LANE_TAB_WIDTH + CARD_WIDTH / 2 + position * step;
      positions.set(index, { x: clampX(raw, width), y: centres[lane] ?? 0 });
    });

    const usable = width - LANE_TAB_WIDTH * 2;

    shown.forEach((kid, position) => {
      const lane = model.nodes[kid]!.lv;
      const row = Math.floor(position / columns);
      const column = position % columns;
      // Cards in the final row are centred against a full row's spacing, so a
      // partial row does not stretch its cards apart.
      const raw = LANE_TAB_WIDTH + (usable / (columns + 1)) * (column + 1);
      positions.set(kid, {
        x: clampX(raw, width),
        y: (centres[lane] ?? 0) + (row - (rowCount - 1) / 2) * rowSpacing,
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
              // `minHeight` rather than a flex ratio: the other lanes shrink to
              // make room, and the band always contains its own cards.
              style={lane === expandedLane ? { minHeight: expandedLaneHeight } : undefined}
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
                top: (centres[expandedLane] ?? 0) + (rowCount * rowSpacing) / 2 + 4,
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
