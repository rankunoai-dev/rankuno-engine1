import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { buildDashModel } from "../../lib/dashboardModel";
import { useDashboardStore } from "../../store/useDashboardStore";
import { crawl, page } from "../../test/factories";
import { NodeInspector } from "./NodeInspector";

/**
 * The detail panel for the focused node.
 *
 * Reads deep into a profile — `signals_evaluated`, `consensus_method`,
 * `trail_source` — and most of those are fields a stored result may not carry.
 * That combination is what makes it worth mounting: every read here is a
 * candidate for the `undefined.toLocaleString()` class of crash that took the
 * dashboard down in cycle 0021.
 */

function focusOn(profileOverrides = {}) {
  const model = buildDashModel(
    crawl({ pages: [page("https://e.com/blog/a/", profileOverrides)] }),
    "path",
  );
  useDashboardStore.getState().setModel(model);
  // The leaf, not the root — the root is a structural node with no profile.
  const leaf = model.nodes.findIndex((n) => n.profile !== null);
  useDashboardStore.setState({ focus: leaf });
  return model;
}

beforeEach(() => {
  useDashboardStore.setState({ focus: null, open: new Set<number>() });
});

describe("NodeInspector", () => {
  it("mounts with nothing focused", () => {
    /* The state on first paint. A panel that throws here blanks the dashboard. */
    const model = buildDashModel(crawl({ pages: [] }), "path");
    useDashboardStore.getState().setModel(model);
    expect(() => render(<NodeInspector model={model} />)).not.toThrow();
  });

  it("shows the focused page's URL", () => {
    const model = focusOn();
    render(<NodeInspector model={model} />);
    expect(screen.getAllByText(/\/blog\/a\//).length).toBeGreaterThan(0);
  });

  it("survives a profile carrying no signals at all", () => {
    /*
     * `signals_evaluated: []` is what a merged Screaming Frog page looks like —
     * classified from a URL with no HTML to read. Cycle 0028 added a whole
     * source of these, so an inspector that assumed at least one signal would
     * now crash on a real, ordinary node.
     */
    const model = focusOn({ signals_evaluated: [], final_confidence_score: 0 });
    expect(() => render(<NodeInspector model={model} />)).not.toThrow();
  });

  it("survives a profile that predates trail_source", () => {
    /* Every result stored before cycle 0023 lacks the field entirely. */
    const model = focusOn({ trail_source: undefined as unknown as "none" });
    expect(() => render(<NodeInspector model={model} />)).not.toThrow();
  });
});
