import { describe, expect, it } from "vitest";
import { rowCentre } from "./FocusGraphStage";

/**
 * Row placement inside a lane.
 *
 * Tested as arithmetic rather than through a mounted component: jsdom has no
 * layout engine, so every `getBoundingClientRect` is zero and the graph never
 * populates a single position. Asserting on a rendered card would be asserting
 * on an empty stage.
 *
 * The bug being pinned: a node and its children can share a lane — everything
 * under OTHERS is assigned the OTHERS lane by design — and both sets were
 * centred on the same lane independently, so they were drawn on top of each
 * other.
 */

const LANE_CENTRE = 200;
const LANE_HEIGHT = 120;
const SPACING = 40;

describe("rowCentre", () => {
  it("separates the chain row from the child rows", () => {
    // The exact case from the screenshot: chain on row 0, children below it.
    const rows = 3;
    const chain = rowCentre(LANE_CENTRE, LANE_HEIGHT, rows, SPACING, 0);
    const first = rowCentre(LANE_CENTRE, LANE_HEIGHT, rows, SPACING, 1);
    const second = rowCentre(LANE_CENTRE, LANE_HEIGHT, rows, SPACING, 2);

    expect(chain).toBeLessThan(first);
    expect(first).toBeLessThan(second);
    expect(first - chain).toBeCloseTo(SPACING);
  });

  it("never returns the same y for two different rows", () => {
    const seen = new Set<number>();
    for (let row = 0; row < 6; row += 1) {
      seen.add(rowCentre(LANE_CENTRE, LANE_HEIGHT, 6, SPACING, row));
    }
    expect(seen.size).toBe(6);
  });

  it("centres a single row on the lane", () => {
    expect(rowCentre(LANE_CENTRE, LANE_HEIGHT, 1, SPACING, 0)).toBeCloseTo(LANE_CENTRE);
  });

  it("keeps the block of rows centred in the lane", () => {
    /* Top and bottom rows equidistant from the lane centre, so a lane sized to
       its rows does not push its own cards out of the band. */
    const rows = 4;
    const top = rowCentre(LANE_CENTRE, LANE_HEIGHT, rows, SPACING, 0);
    const bottom = rowCentre(LANE_CENTRE, LANE_HEIGHT, rows, SPACING, rows - 1);
    expect((top + bottom) / 2).toBeCloseTo(LANE_CENTRE);
  });

  it("still separates rows before the lane has been measured", () => {
    /* Height is 0 on the first paint. Rows must not all collapse onto the
       centre for that frame — that is the overlap, briefly. */
    const a = rowCentre(LANE_CENTRE, 0, 3, SPACING, 0);
    const b = rowCentre(LANE_CENTRE, 0, 3, SPACING, 1);
    expect(b - a).toBeCloseTo(SPACING);
    expect(a).not.toBeCloseTo(b);
  });

  it("is centred on the lane when unmeasured, not hanging below it", () => {
    const rows = 3;
    const top = rowCentre(LANE_CENTRE, 0, rows, SPACING, 0);
    const bottom = rowCentre(LANE_CENTRE, 0, rows, SPACING, rows - 1);
    expect((top + bottom) / 2).toBeCloseTo(LANE_CENTRE);
  });
});
