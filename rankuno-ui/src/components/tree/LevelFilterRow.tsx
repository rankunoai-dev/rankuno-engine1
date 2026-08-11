import {
  LANE_DESCRIPTIONS,
  LANE_LABELS,
  METHOD_LABELS,
  type DashModel,
} from "../../lib/dashboardModel";
import { useDashboardStore } from "../../store/useDashboardStore";

const LANE_CHIP = ["f0", "f1", "f2", "f3", "fo"];

interface Props {
  model: DashModel;
}

/**
 * Filter chips for navigation depth and for the cascade layer that classified
 * each page.
 *
 * The layer chips are derived from `model.methodsPresent` rather than
 * hard-coded. Layer 2 (local ML) and Layer 3 (LLM) are protocols with no
 * implementation, so a fixed set of four chips would render three controls that
 * can only ever filter to nothing — a control that appears to work and does not
 * is worse than one that is absent.
 */
export function LevelFilterRow({ model }: Props): JSX.Element {
  const laneFilter = useDashboardStore((state) => state.laneFilter);
  const methodFilter = useDashboardStore((state) => state.methodFilter);
  const toggleLane = useDashboardStore((state) => state.toggleLane);
  const toggleMethod = useDashboardStore((state) => state.toggleMethod);

  return (
    <div className="filters">
      <div className="chiprow">
        {LANE_LABELS.map((label, lane) => (
          <button
            key={label}
            type="button"
            title={`${LANE_DESCRIPTIONS[lane]} — ${model.laneCounts[lane]?.toLocaleString() ?? 0} nodes`}
            className={`fchip ${LANE_CHIP[lane]}${laneFilter.has(lane) ? " on" : ""}`}
            onClick={() => toggleLane(lane, model)}
          >
            <i />
            {label === "OTH" ? "Others" : label}
          </button>
        ))}
      </div>

      {model.methodsPresent.length > 0 && (
        <div className="chiprow">
          {model.methodsPresent.map((method) => (
            <button
              key={method}
              type="button"
              title={METHOD_LABELS[method]}
              className={`fchip fr${methodFilter.has(method) ? " on" : ""}`}
              onClick={() => toggleMethod(method, model)}
            >
              <i />
              {METHOD_LABELS[method].split(" · ")[1] ?? METHOD_LABELS[method]}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
