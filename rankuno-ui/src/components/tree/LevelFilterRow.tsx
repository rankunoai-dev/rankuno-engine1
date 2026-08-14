import {
  BAND_LABELS,
  CONFIDENCE_THRESHOLD,
  LANE_DESCRIPTIONS,
  LANE_LABELS,
  PATH_LANE_DESCRIPTIONS,
  type ConfidenceBand,
  type DashModel,
} from "../../lib/dashboardModel";
import { useCrawlStore } from "../../store/useCrawlStore";
import { useDashboardStore } from "../../store/useDashboardStore";

const LANE_CHIP = ["f0", "f1", "f2", "f3", "fo"];

interface Props {
  model: DashModel;
}

/**
 * Filter chips for tree depth and for classification confidence.
 *
 * The second row used to filter by `consensus_method` — which cascade layer
 * resolved the page. That is an engine internal: it tells an analyst which code
 * path ran, not whether the answer can be trusted. Worse, two of its four
 * values can never appear, because Layers 2 and 3 have no implementation, so
 * the row offered controls that could only ever filter to nothing.
 *
 * Confidence is the question actually being asked of this screen: *what does
 * the engine want me to check?*
 */
export function LevelFilterRow({ model }: Props): JSX.Element {
  const laneFilter = useDashboardStore((state) => state.laneFilter);
  const bandFilter = useDashboardStore((state) => state.bandFilter);
  const toggleLane = useDashboardStore((state) => state.toggleLane);
  const toggleBand = useDashboardStore((state) => state.toggleBand);
  const navGrouped = useCrawlStore(
    (state) => state.grouping === "navigation" && (state.result?.navigation?.roots.length ?? 0) > 0,
  );

  return (
    <div className="filters">
      <div className="chiprow">
        {LANE_LABELS.map((label, lane) => (
          <button
            key={label}
            type="button"
            title={`${(navGrouped ? LANE_DESCRIPTIONS : PATH_LANE_DESCRIPTIONS)[lane]} — ${model.laneCounts[lane]?.toLocaleString() ?? 0} nodes`}
            className={`fchip ${LANE_CHIP[lane]}${laneFilter.has(lane) ? " on" : ""}`}
            onClick={() => toggleLane(lane, model)}
          >
            <i />
            {label === "OTH" ? "Others" : label}
          </button>
        ))}
      </div>

      <div className="chiprow">
        {(["high", "review"] as ConfidenceBand[]).map((band) => (
          <button
            key={band}
            type="button"
            title={
              band === "high"
                ? `Classified at ${Math.round(CONFIDENCE_THRESHOLD * 100)}% confidence or above — ${model.bandCounts.high.toLocaleString()} pages`
                : `Below ${Math.round(CONFIDENCE_THRESHOLD * 100)}% confidence, or not classified at all — ${model.bandCounts.review.toLocaleString()} pages`
            }
            className={`fchip fr${bandFilter.has(band) ? " on" : ""}`}
            onClick={() => toggleBand(band, model)}
          >
            <i />
            {BAND_LABELS[band]} · {model.bandCounts[band].toLocaleString()}
          </button>
        ))}
      </div>
    </div>
  );
}
