import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { landsOnHomepage, redirectHops } from "../../lib/audit";
import { page } from "../../test/factories";
import { RedirectTable } from "./RedirectTable";

/**
 * The redirect worklist.
 *
 * What is asserted is that the **destination** reaches the screen and the file.
 * Before this table existed the finding rendered through the orphan worklist,
 * which has no such column — so a report naming 318 redirecting URLs could not
 * say where any of them went, which is the only thing an analyst needs.
 */

const moved = page("https://e.com/about/csr-policy/", {
  discovery_sources: { sitemap: true, dom_link: false, cms_api: false },
  final_url: "https://e.com/",
  redirect_chain: ["https://e.com/about/"],
});

const chained = page("https://e.com/old/", {
  discovery_sources: { sitemap: true, dom_link: false, cms_api: false },
  final_url: "https://e.com/new/",
  redirect_chain: ["https://e.com/mid/", "https://e.com/mid2/", "https://e.com/new/"],
});

function stubDownload() {
  const clicked = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(clicked);
  URL.createObjectURL = vi.fn(() => "blob:x");
  URL.revokeObjectURL = vi.fn();
  return clicked;
}

describe("RedirectTable", () => {
  it("shows where each URL resolves to, not only that it moved", () => {
    render(<RedirectTable pages={[chained]} baseUrl="https://e.com/" />);
    const table = screen.getByRole("table");
    expect(within(table).getByText("https://e.com/old/")).toBeInTheDocument();
    expect(within(table).getByText("https://e.com/new/")).toBeInTheDocument();
  });

  it("counts the hops from the recorded chain", () => {
    render(<RedirectTable pages={[chained]} baseUrl="https://e.com/" />);
    expect(redirectHops(chained)).toBe(3);
    expect(within(screen.getByRole("table")).getByText("3")).toBeInTheDocument();
  });

  it("flags a redirect that lands on the homepage", () => {
    // Search engines read this as gone rather than moved, so it is the row an
    // analyst should look at first.
    expect(landsOnHomepage(moved)).toBe(true);
    render(<RedirectTable pages={[moved]} baseUrl="https://e.com/" />);
    expect(screen.getByText("homepage")).toBeInTheDocument();
  });

  it("filters to the homepage redirects on demand", () => {
    render(<RedirectTable pages={[moved, chained]} baseUrl="https://e.com/" />);
    fireEvent.click(screen.getByRole("button", { name: /Lands on homepage \(1\)/ }));

    const table = screen.getByRole("table");
    expect(within(table).getByText("https://e.com/about/csr-policy/")).toBeInTheDocument();
    expect(within(table).queryByText("https://e.com/old/")).not.toBeInTheDocument();
  });

  it("withholds the homepage filter when nothing lands there", () => {
    // A control that can only ever return an empty table reads as broken.
    render(<RedirectTable pages={[chained]} baseUrl="https://e.com/" />);
    expect(screen.queryByRole("button", { name: /Lands on homepage/ })).not.toBeInTheDocument();
  });

  it("searches either address, not only the listed one", () => {
    render(<RedirectTable pages={[moved, chained]} baseUrl="https://e.com/" />);
    // `new` appears only in the destination of one row.
    fireEvent.change(screen.getByLabelText("Filter redirects by URL"), {
      target: { value: "/new/" },
    });
    expect(screen.getByRole("button", { name: /Export CSV \(1\)/ })).toBeInTheDocument();
  });

  it("exports what is on screen", () => {
    const clicked = stubDownload();
    render(<RedirectTable pages={[moved, chained]} baseUrl="https://e.com/" />);

    expect(screen.getByRole("button", { name: /Export CSV \(2\)/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Export CSV/ }));
    expect(clicked).toHaveBeenCalled();
    vi.restoreAllMocks();
  });

  it("treats a crawl with no recorded chain as zero hops, not as an error", () => {
    // Stored results predating the field arrive without `redirect_chain`.
    const { redirect_chain: _dropped, ...rest } = chained;
    const legacy = rest as typeof chained;
    expect(redirectHops(legacy)).toBe(0);
    expect(() => render(<RedirectTable pages={[legacy]} baseUrl="https://e.com/" />)).not.toThrow();
  });
});
