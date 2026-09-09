import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import type { SavedReconciliation } from "../../adapters/adapterInterface";
import { buildDashModel } from "../../lib/dashboardModel";
import { useCrawlStore } from "../../store/useCrawlStore";
import { useDashboardStore } from "../../store/useDashboardStore";
import { crawl, page } from "../../test/factories";
import { VirtualizedTree } from "./VirtualizedTree";

/**
 * The cross-check overlay as it reaches the screen.
 *
 * Rendered through `VirtualizedTree` rather than `TreeControls` alone, because
 * the tree is where the overlay is built and published; a control test that
 * bypassed that would pass with the wiring missing.
 */

function reconciliation(): SavedReconciliation {
  return {
    summary: {
      job_id: "j",
      source_job_id: "j",
      base_url: "https://e.com/",
      frog_rows: 0,
      in_both: 1,
      missed_pages: 0,
      orphans: 0,
      merged: 0,
      frog_reasons: {},
      engine_reasons: {},
    },
    created_at: "",
    missed_pages: [],
    orphans: [],
    frog_only: [],
    engine_only: [{ url: "https://e.com/docs/b/", reason: "SITEMAP_ORPHAN" }],
  };
}

function tree() {
  const pages = [
    page("https://e.com/docs/a/", { breadcrumb_path: ["Docs"] }),
    page("https://e.com/docs/b/", { breadcrumb_path: ["Docs"] }),
  ];
  const model = buildDashModel(crawl({ pages }), "navigation");
  useDashboardStore.getState().setModel(model);
  useDashboardStore.getState().expandAll(model, 99);
  return model;
}

beforeEach(() => {
  useDashboardStore.setState({
    overlay: null,
    crossCheckOn: false,
    missedOnly: false,
    fullScreen: false,
    hiddenReasons: new Set<string>(),
  });
  useCrawlStore.setState({ reconciliation: null, result: null, includeDefaulters: false });
});

describe("cross-check toggle", () => {
  it("is disabled, with the reason, when no cross-check is saved", () => {
    const model = tree();
    render(<VirtualizedTree model={model} />);
    const toggle = screen.getByLabelText("Cross-check") as HTMLInputElement;
    expect(toggle.disabled).toBe(true);
    expect(screen.getByText(/No Screaming Frog cross-check is saved/)).toBeInTheDocument();
  });

  it("marks the missed row and counts it on the section", () => {
    const model = tree();
    useCrawlStore.setState({ reconciliation: reconciliation() });
    const { container } = render(<VirtualizedTree model={model} />);

    expect(container.querySelector(".xmark-missed")).toBeNull();
    fireEvent.click(screen.getByLabelText("Cross-check"));

    expect(container.querySelectorAll(".xmark-missed")).toHaveLength(1);
    expect(screen.getByText("· 1 missed")).toBeInTheDocument();
    // The reason chip carries the sidecar's own count.
    expect(screen.getByText("Sitemap Orphan · 1")).toBeInTheDocument();
    expect(screen.getByText(/cross-check ✓/)).toBeInTheDocument();
  });

  it("stops counting a reason when its chip is switched off, and keeps the mark", () => {
    const model = tree();
    useCrawlStore.setState({ reconciliation: reconciliation() });
    const { container } = render(<VirtualizedTree model={model} />);
    fireEvent.click(screen.getByLabelText("Cross-check"));
    fireEvent.click(screen.getByText("Sitemap Orphan · 1"));

    expect(screen.queryByText("· 1 missed")).toBeNull();
    expect(container.querySelectorAll(".xmark-missed")).toHaveLength(1);
  });

  it("opens the full-screen view and closes it on Escape", () => {
    const model = tree();
    render(<VirtualizedTree model={model} />);
    fireEvent.click(screen.getByText("⛶ Full screen"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("whole-tree depth commands", () => {
  it("collapses every section from the tree's own controls", () => {
    const model = tree();
    render(<VirtualizedTree model={model} />);
    const opened = useDashboardStore.getState().flat.length;

    fireEvent.click(screen.getByRole("button", { name: "Collapse all" }));

    const closed = useDashboardStore.getState().flat.length;
    expect(closed).toBeLessThan(opened);
    // A collapsed tree still shows its top level. Nothing left on screen would
    // read as a crash rather than a collapse.
    expect(closed).toBe(model.roots.length);
  });

  it("expands every section again", () => {
    const model = tree();
    render(<VirtualizedTree model={model} />);
    fireEvent.click(screen.getByRole("button", { name: "Collapse all" }));
    fireEvent.click(screen.getByRole("button", { name: "Expand all" }));
    expect(useDashboardStore.getState().flat).toHaveLength(model.nodes.length);
  });

  it("offers them inside the full-screen view too", () => {
    /*
     * The reason this moved. The commands lived in the dashboard's toolbar, so
     * the full-screen tree — the view with the most rows on screen and the most
     * need to close them — had no way to collapse anything at all.
     */
    const model = tree();
    render(<VirtualizedTree model={model} />);
    fireEvent.click(screen.getByText("⛶ Full screen"));

    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByRole("button", { name: "Collapse all" })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Expand all" })).toBeInTheDocument();
  });

  it("styles them above the global button reset", () => {
    /*
     * `.rk-dash button` is (0,1,1) and strips background, border and colour from
     * any button styled on a single class. Three sets of controls have already
     * been reported invisible for exactly that reason, so the class these carry
     * has to be one the stylesheet scopes under `.xctl` — (0,2,0).
     */
    const model = tree();
    const { container } = render(<VirtualizedTree model={model} />);
    const collapse = screen.getByRole("button", { name: "Collapse all" });
    expect(collapse.className).toContain("xbtn");
    expect(container.querySelector(".xctl .xdepth")).not.toBeNull();
  });
});

describe("getting back to the main tree", () => {
  it("offers a way back from the full-screen view", () => {
    /*
     * The overlay's own header carries a ✕ Close, but that strip sits above the
     * section cards and is the first thing scrolled past. The way back belongs
     * in the control row, in the slot the "Full screen" button occupies on the
     * way in.
     */
    const model = tree();
    render(<VirtualizedTree model={model} />);
    fireEvent.click(screen.getByText("⛶ Full screen"));

    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: /Main tree view/ }));

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(useDashboardStore.getState().fullScreen).toBe(false);
  });

  it("does not offer it on the dashboard, where it would go nowhere", () => {
    // Inline, the same slot means the opposite thing. A button reading "main
    // tree view" while you are looking at the main tree is a dead control.
    const model = tree();
    render(<VirtualizedTree model={model} />);
    expect(screen.queryByRole("button", { name: /Main tree view/ })).toBeNull();
    expect(screen.getByText("⛶ Full screen")).toBeInTheDocument();
  });
});

describe("Include Defaulters toggle", () => {
  it("is disabled, with the reason, when no cross-check is saved", () => {
    const model = tree();
    render(<VirtualizedTree model={model} />);
    const toggle = screen.getByLabelText("Include Defaulters") as HTMLInputElement;
    expect(toggle.disabled).toBe(true);
    expect(toggle.checked).toBe(false);
    expect(toggle.closest("label")?.title).toMatch(/No cross-check is loaded/);
  });

  it("is off by default even once a cross-check is loaded", () => {
    const model = tree();
    useCrawlStore.setState({ reconciliation: reconciliation() });
    render(<VirtualizedTree model={model} />);
    const toggle = screen.getByLabelText("Include Defaulters") as HTMLInputElement;
    expect(toggle.disabled).toBe(false);
    expect(toggle.checked).toBe(false);
  });

  it("flips the store flag on click, independent of the cross-check toggle", () => {
    const model = tree();
    useCrawlStore.setState({ reconciliation: reconciliation() });
    render(<VirtualizedTree model={model} />);

    fireEvent.click(screen.getByLabelText("Include Defaulters"));
    expect(useCrawlStore.getState().includeDefaulters).toBe(true);
    expect(useDashboardStore.getState().crossCheckOn).toBe(false);

    fireEvent.click(screen.getByLabelText("Include Defaulters"));
    expect(useCrawlStore.getState().includeDefaulters).toBe(false);
  });
});
