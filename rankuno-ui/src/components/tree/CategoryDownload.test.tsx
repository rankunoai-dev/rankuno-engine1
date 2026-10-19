import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { downloadCsv } from "../../lib/csv";
import { buildDashModel, EMPTY_MODEL, type DashNode } from "../../lib/dashboardModel";
import { useDashboardStore } from "../../store/useDashboardStore";
import { crawl, page } from "../../test/factories";
import { CategoryDownload } from "./CategoryDownload";
import { VirtualizedTree } from "./VirtualizedTree";

vi.mock("../../lib/csv", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../lib/csv")>()),
  downloadCsv: vi.fn(),
}));

/**
 * The per-category download control.
 *
 * Asserted on the element the user meets: its accessible name, whether it is
 * disabled and why, and what the click hands the browser. The layout (gutter,
 * theme, narrow widths) is CSS and is checked in a browser, not here.
 */

function blogModel() {
  const pages = [
    page("https://e.com/blog/"),
    page("https://e.com/blog/a/"),
    page("https://e.com/blog/a/deep/"),
    page("https://e.com/shop/"),
  ];
  return buildDashModel(crawl({ pages }), "path");
}

beforeEach(() => {
  vi.mocked(downloadCsv).mockClear();
  useDashboardStore.setState({ focus: null, open: new Set<number>() });
});

describe("CategoryDownload", () => {
  it("is labelled with its category and shows the URL count", () => {
    const model = blogModel();
    const blog = model.nodes.find((node) => node.label === "blog")!;
    render(<CategoryDownload model={model} node={blog} top={0} />);
    const button = screen.getByRole("button", { name: "Download URLs for blog" });
    expect(button).toHaveTextContent("3");
    expect(button).toBeEnabled();
  });

  it("downloads exactly the URLs under the category, as urls-<slug>.csv", () => {
    const model = blogModel();
    const blog = model.nodes.find((node) => node.label === "blog")!;
    render(<CategoryDownload model={model} node={blog} top={0} />);
    fireEvent.click(screen.getByRole("button", { name: "Download URLs for blog" }));

    expect(downloadCsv).toHaveBeenCalledTimes(1);
    const [filename, content] = vi.mocked(downloadCsv).mock.calls[0]!;
    expect(filename).toBe("urls-blog.csv");
    const urls = content
      .split("\r\n")
      .slice(1)
      .map((line) => line.split(",")[0]);
    expect(urls.sort()).toEqual([
      "https://e.com/blog/",
      "https://e.com/blog/a/",
      "https://e.com/blog/a/deep/",
    ]);
    expect(content).not.toContain("https://e.com/shop/");
  });

  it("is disabled, with a visible reason, when the category holds no URLs", () => {
    const empty: DashNode = {
      i: 0,
      lv: 0,
      label: "empty",
      url: "",
      p: null,
      kids: [0],
      cnt: 0,
      profile: null,
      src: "none",
      kind: "group",
    };
    const model = { ...EMPTY_MODEL, nodes: [empty], roots: [0] };
    render(<CategoryDownload model={model} node={empty} top={0} />);
    const button = screen.getByRole("button", { name: "Download URLs for empty" });
    expect(button).toBeDisabled();
    expect(button).toHaveTextContent("No URLs");
    expect(button).toHaveAttribute("title", "No URLs under empty to download");
    fireEvent.click(button);
    expect(downloadCsv).not.toHaveBeenCalled();
  });

  it("is a native button, so Enter and Space reach it as a click", () => {
    const model = blogModel();
    const blog = model.nodes.find((node) => node.label === "blog")!;
    render(<CategoryDownload model={model} node={blog} top={0} />);
    const button = screen.getByRole("button", { name: "Download URLs for blog" });
    expect(button.tagName).toBe("BUTTON");
    button.focus();
    expect(button).toHaveFocus();
  });
});

describe("VirtualizedTree category rows", () => {
  it("gives each category row a download control and leaf rows none", () => {
    const model = blogModel();
    useDashboardStore.getState().setModel(model);
    useDashboardStore.getState().expandAll(model, 99);
    render(<VirtualizedTree model={model} />);
    expect(screen.getByRole("button", { name: "Download URLs for blog" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download URLs for a" })).toBeInTheDocument();
    // `deep` is a leaf: no children, so no control.
    expect(screen.queryByRole("button", { name: "Download URLs for deep" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Download URLs for shop" })).toBeNull();
  });

  it("does not open or select the row when the download control is used", () => {
    const model = blogModel();
    useDashboardStore.getState().setModel(model);
    render(<VirtualizedTree model={model} />);
    // setModel seeds the selection itself, so compare against what it was
    // before the click rather than against a fixed value.
    const { focus, open } = useDashboardStore.getState();
    fireEvent.click(screen.getByRole("button", { name: "Download URLs for blog" }));
    expect(useDashboardStore.getState().focus).toBe(focus);
    expect(useDashboardStore.getState().open).toBe(open);
  });
});
