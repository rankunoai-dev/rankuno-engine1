import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { buildDashModel } from "../../lib/dashboardModel";
import { useDashboardStore } from "../../store/useDashboardStore";
import { crawl, page } from "../../test/factories";
import { VirtualizedTree } from "./VirtualizedTree";

/**
 * The windowed directory tree.
 *
 * The property worth pinning is that it is *windowed*: it renders roughly 25
 * rows regardless of how many nodes it holds. That is the whole reason a
 * 29,248-node crawl is navigable at all, and it is invisible to `tsc` — a
 * regression that dropped the windowing would still typecheck, still build, and
 * lock the browser on the next real crawl.
 */

function treeOf(count: number) {
  const pages = Array.from({ length: count }, (_, i) =>
    page(`https://e.com/blog/post-${i}/`, { breadcrumb_path: ["Blog"] }),
  );
  const model = buildDashModel(crawl({ pages }), "path");
  useDashboardStore.getState().setModel(model);
  return model;
}

beforeEach(() => {
  useDashboardStore.setState({ focus: null, expanded: new Set<number>() });
});

describe("VirtualizedTree", () => {
  it("mounts on an empty model without throwing", () => {
    /* The state on first paint, before any crawl is selected. */
    const model = buildDashModel(crawl({ pages: [] }), "path");
    expect(() => render(<VirtualizedTree model={model} />)).not.toThrow();
  });

  it("keeps the DOM small when the model is large", () => {
    const model = treeOf(600);
    const { container } = render(<VirtualizedTree model={model} />);
    const rows = container.querySelectorAll(".vrow");
    /*
     * jsdom has no layout engine, so the viewport measures 0 and the window
     * collapses to its minimum — 3 rows for 601 nodes, measured. The exact
     * number is an artefact of the environment and is not asserted; the bound
     * is, because a regression that dropped the windowing would render all 601
     * and blow straight through it.
     *
     * `toBeLessThan(model.nodes.length)` was the first version of this and was
     * vacuous: it also passes when nothing renders at all.
     */
    expect(rows.length).toBeGreaterThan(0);
    expect(rows.length).toBeLessThan(50);
  });

  it("labels a root with its own segment, not the breadcrumb", () => {
    /*
     * Under `path` grouping a node is named for its URL segment — `blog` — and
     * under `navigation` for its breadcrumb — `Blog`. Asserting the wrong one
     * is how this test first failed, and the distinction is real: the lane
     * labels mean different things in the two modes, which cycle 0014 had to
     * spell out on screen for the same reason.
     */
    const model = treeOf(3);
    render(<VirtualizedTree model={model} />);
    expect(screen.getByText("blog")).toBeInTheDocument();
  });
});
