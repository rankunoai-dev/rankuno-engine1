import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { buildFindings, suggestedSurvivor } from "../../lib/audit";
import { toCsv } from "../../lib/csv";
import { crawl, page } from "../../test/factories";
import { DuplicateTable } from "./DuplicateTable";

/**
 * Duplicate URL sets.
 *
 * The assertions are about the *cluster*: which member is proposed as the one
 * to keep, and whether the export keeps a page's copies adjacent. A table that
 * lists 1,920 URLs is not the deliverable — 262 decisions are.
 */

const canonical = page("https://e.com/blog/energy-utilities", {
  inbound_internal_links_count: 12,
  breadcrumb_path: ["Blog", "Energy"],
});

const categoryCopy = page("https://e.com/blog/category/energy-utilities", {
  inbound_internal_links_count: 3,
  breadcrumb_path: ["Blog", "Categories", "Energy"],
});

const pagedCopy = page("https://e.com/blog/category/energy-utilities?page=0", {
  inbound_internal_links_count: 1,
  breadcrumb_path: ["Blog", "Categories", "Energy"],
});

const group = [pagedCopy, categoryCopy, canonical];

describe("suggestedSurvivor", () => {
  it("keeps the copy the site links to most, not the first one crawled", () => {
    expect(suggestedSurvivor(group)?.url).toBe(canonical.url);
  });

  it("breaks a tie on the shorter path", () => {
    const short = page("https://e.com/a/x", { inbound_internal_links_count: 2 });
    const long = page("https://e.com/a/b/c/x", { inbound_internal_links_count: 2 });
    expect(suggestedSurvivor([long, short])?.url).toBe(short.url);
  });

  it("prefers an address without a query string when depth ties", () => {
    const clean = page("https://e.com/a/x", { inbound_internal_links_count: 2 });
    const dirty = page("https://e.com/a/x?page=0", { inbound_internal_links_count: 2 });
    expect(suggestedSurvivor([dirty, clean])?.url).toBe(clean.url);
  });

  it("is stable rather than dependent on crawl order", () => {
    const a = page("https://e.com/a/x");
    const b = page("https://e.com/a/y");
    expect(suggestedSurvivor([a, b])?.url).toBe(suggestedSurvivor([b, a])?.url);
  });

  it("returns nothing for an empty set rather than throwing", () => {
    expect(suggestedSurvivor([])).toBeUndefined();
  });
});

describe("DuplicateTable", () => {
  it("shows one row per page, not one per URL", () => {
    render(<DuplicateTable groups={[group]} baseUrl="https://e.com/" />);
    // Three URLs, one decision.
    expect(screen.getAllByRole("row")).toHaveLength(2); // header + one group
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("flags a set whose copies disagree about their own section", () => {
    render(<DuplicateTable groups={[group]} baseUrl="https://e.com/" />);
    expect(screen.getByText("disagree")).toBeInTheDocument();
  });

  it("does not flag a set whose breadcrumbs agree", () => {
    const agreed = [
      page("https://e.com/a/x", { breadcrumb_path: ["Blog"] }),
      page("https://e.com/b/x", { breadcrumb_path: ["Blog"] }),
    ];
    render(<DuplicateTable groups={[agreed]} baseUrl="https://e.com/" />);
    expect(screen.queryByText("disagree")).not.toBeInTheDocument();
  });

  it("expands to every member of the set", () => {
    render(<DuplicateTable groups={[group]} baseUrl="https://e.com/" />);
    fireEvent.click(screen.getByRole("button", { name: /Expand row/i }));
    for (const member of group) {
      expect(screen.getAllByText(member.url).length).toBeGreaterThan(0);
    }
  });

  it("offers the URL count, not the group count, on the export", () => {
    render(<DuplicateTable groups={[group]} baseUrl="https://e.com/" />);
    expect(screen.getByRole("button", { name: /Export CSV \(3 URLs\)/ })).toBeInTheDocument();
  });

  it("downloads when asked", () => {
    const clicked = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(clicked);
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();

    render(<DuplicateTable groups={[group]} baseUrl="https://e.com/" />);
    fireEvent.click(screen.getByRole("button", { name: /Export CSV/ }));
    expect(clicked).toHaveBeenCalled();
    vi.restoreAllMocks();
  });
});

describe("the exported shape", () => {
  it("keeps a page's copies adjacent under one group id", () => {
    // What "clubbed in the spreadsheet" means: sorting by the first column puts
    // every address of a page in one block instead of scattering them.
    const rows = group.map((member) => [
      1,
      member.url === canonical.url ? "keep (suggested)" : "redirect or canonical",
      member.url,
    ]);
    const csv = toCsv(["group", "action", "url"], rows);
    const lines = csv.split("\r\n");
    expect(lines).toHaveLength(4);
    expect(lines.slice(1).every((line) => line.startsWith("1,"))).toBe(true);
    expect(lines.filter((line) => line.includes("keep (suggested)"))).toHaveLength(1);
  });
});

describe("the finding carries its groups", () => {
  it("hands the audit view clusters rather than a flat page list", () => {
    const finding = buildFindings(crawl({ pages: group })).find(
      (item) => item.id === "duplicate-urls",
    );
    expect(finding?.groups).toHaveLength(1);
    expect(finding?.groups?.[0]).toHaveLength(3);
  });

  it("puts the largest cluster first, because it is the one to fix first", () => {
    const pair = [page("https://e.com/p/y"), page("https://e.com/q/y")];
    const finding = buildFindings(crawl({ pages: [...pair, ...group] })).find(
      (item) => item.id === "duplicate-urls",
    );
    expect(finding?.groups?.[0]).toHaveLength(3);
  });
});
