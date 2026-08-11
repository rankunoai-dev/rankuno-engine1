import { LANE_LABELS, type DashModel } from "../../lib/dashboardModel";
import { useDashboardStore } from "../../store/useDashboardStore";

const LANE_CLASS = ["p0", "p1", "p2", "p3", "po"];

interface Props {
  model: DashModel;
  /** Ancestor indices from root to the focused node, inclusive. */
  chain: number[];
  childCount: number;
}

/**
 * The path from the root to the focused node, each step clickable.
 *
 * The only way back up. The graph shows one neighbourhood at a time, so without
 * this the sole route to an ancestor is finding it again in the tree.
 */
export function BreadcrumbBar({ model, chain, childCount }: Props): JSX.Element {
  const setFocus = useDashboardStore((state) => state.setFocus);

  if (chain.length === 0) {
    return <div className="crumbs" />;
  }

  return (
    <div className="crumbs">
      {chain.map((index, position) => {
        const node = model.nodes[index];
        if (!node) return null;
        return (
          <span key={index} style={{ display: "contents" }}>
            {position > 0 && <i>›</i>}
            <button type="button" className="cb" onClick={() => setFocus(index, model)}>
              <span className={`lvchip ${LANE_CLASS[node.lv]}`}>{LANE_LABELS[node.lv]}</span>
              {node.label}
            </button>
          </span>
        );
      })}
      {childCount > 0 && (
        <>
          <i>›</i>
          <span style={{ color: "var(--faint)", fontSize: 11 }}>
            {childCount.toLocaleString()} children
          </span>
        </>
      )}
    </div>
  );
}
