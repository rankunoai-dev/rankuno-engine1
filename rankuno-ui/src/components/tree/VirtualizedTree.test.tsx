import { fireEvent, render, screen } from "@testing-library/react";
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
  useDashboardStore.setState({ focus: null, open: new Set<number>() });
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

describe("whole-branch expand and collapse", () => {
  /**
   * A nested tree: `/docs/` holds `guides/`, which holds three posts. Two levels
   * below a root is the shallowest shape where "open one level" and "open the
   * branch" differ, which is the distinction under test.
   */
  function nested() {
    const pages = [
      page("https://e.com/docs/guides/a/"),
      page("https://e.com/docs/guides/b/"),
      page("https://e.com/docs/guides/c/"),
    ];
    const model = buildDashModel(crawl({ pages }), "path");
    useDashboardStore.getState().setModel(model);
    return model;
  }

  it("opens every descendant, not just the next level", () => {
    const model = nested();
    const store = useDashboardStore.getState();
    const root = model.roots[0]!;

    store.collapseAll(model);
    const oneLevel = useDashboardStore.getState().flat.length;

    useDashboardStore.getState().expandBranch(root, model);
    const wholeBranch = useDashboardStore.getState().flat.length;

    expect(wholeBranch).toBeGreaterThan(oneLevel);
    expect(wholeBranch).toBe(model.nodes.length);
  });

  it("closes the node itself as well as its descendants", () => {
    const model = nested();
    const root = model.roots[0]!;
    useDashboardStore.getState().expandBranch(root, model);
    useDashboardStore.getState().collapseBranch(root, model);

    const { open, flat } = useDashboardStore.getState();
    expect(open.has(root)).toBe(false);
    // The root row itself still renders: a closed section is visible, its
    // children are not.
    expect(flat.some((row) => row.i === root)).toBe(true);
    expect(flat).toHaveLength(model.roots.length);
  });

  it("leaves other sections alone", () => {
    /*
     * The difference between this and `expandAll`, which replaces the open set
     * outright. Opening one section in full must not close another the analyst
     * had already opened.
     */
    const pages = [
      page("https://e.com/docs/guides/a/"),
      page("https://e.com/blog/news/b/"),
    ];
    const model = buildDashModel(crawl({ pages }), "path");
    useDashboardStore.getState().setModel(model);
    const [first, second] = model.roots;

    useDashboardStore.getState().expandBranch(first!, model);
    useDashboardStore.getState().expandBranch(second!, model);

    const { open } = useDashboardStore.getState();
    expect(open.has(first!)).toBe(true);
    expect(open.has(second!)).toBe(true);
  });

  it("offers the control on a row with children and withholds it on a leaf", () => {
    const model = nested();
    useDashboardStore.getState().expandBranch(model.roots[0]!, model);
    const { container } = render(<VirtualizedTree model={model} />);

    const rows = [...container.querySelectorAll(".vrow")];
    const parents = rows.filter((row) => row.querySelector(".tcnt"));
    const leaves = rows.filter((row) => !row.querySelector(".tcnt"));

    expect(parents.length).toBeGreaterThan(0);
    expect(parents.every((row) => row.querySelector(".tbranch"))).toBe(true);
    // A leaf has nothing to expand; a control that does nothing reads as broken.
    expect(leaves.every((row) => !row.querySelector(".tbranch"))).toBe(true);
  });

  it("expands the whole branch on a shift-click of a closed node", () => {
    const model = nested();
    // `collapseAll` leaves roots open by design, so a root is the one row whose
    // control collapses rather than expands. Close it explicitly first.
    useDashboardStore.getState().collapseBranch(model.roots[0]!, model);
    const before = useDashboardStore.getState().flat.length;

    const { container } = render(<VirtualizedTree model={model} />);
    fireEvent.click(container.querySelector(".vrow .tw")!, { shiftKey: true });

    expect(useDashboardStore.getState().flat.length).toBeGreaterThan(before);
    expect(useDashboardStore.getState().flat).toHaveLength(model.nodes.length);
  });

  it("collapses a root that `collapseAll` left open", () => {
    /*
     * Pins a semantic that surprised this test first time round: "collapse all"
     * closes every *section* but keeps the roots themselves open, so the tree
     * never collapses to nothing. A root's branch control therefore reads as
     * collapse, not expand, immediately after it.
     */
    const model = nested();
    useDashboardStore.getState().collapseAll(model);
    expect(useDashboardStore.getState().open.has(model.roots[0]!)).toBe(true);

    const { container } = render(<VirtualizedTree model={model} />);
    fireEvent.click(container.querySelector(".vrow .tw")!, { shiftKey: true });

    expect(useDashboardStore.getState().open.has(model.roots[0]!)).toBe(false);
  });

  it("still opens one level on a plain click", () => {
    const model = nested();
    useDashboardStore.getState().collapseAll(model);

    const { container } = render(<VirtualizedTree model={model} />);
    fireEvent.click(container.querySelector(".vrow .tw")!);

    expect(useDashboardStore.getState().flat.length).toBeLessThan(model.nodes.length);
  });
});
