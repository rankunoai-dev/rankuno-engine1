import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { crawl, page } from "../../test/factories";
import { useCrawlStore } from "../../store/useCrawlStore";
import { AuditView } from "./AuditView";

/**
 * The export control on a finding card.
 *
 * It existed only inside the drill-in table, behind a control styled as a 1px
 * near-black border on a near-black card. An analyst looking for the CSV could
 * not find it twice over: the button that revealed the table was invisible, and
 * the download was one level below that.
 */

vi.mock("../../lib/csv", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../lib/csv")>()),
  downloadCsv: vi.fn(),
}));

const { downloadCsv } = await import("../../lib/csv");

function withOrphans(count: number) {
  const pages = Array.from({ length: count }, (_, index) =>
    page(`https://e.com/orphan-${index}/`, { inbound_internal_links_count: 0 }),
  );
  useCrawlStore.setState({ result: crawl({ pages }) });
}

describe("downloading a finding", () => {
  it("offers the export on the card, without opening the list first", () => {
    withOrphans(3);
    render(<AuditView />);
    expect(screen.getAllByRole("button", { name: /download csv/i }).length).toBeGreaterThan(0);
  });

  it("writes a file named for the site and the finding", () => {
    withOrphans(3);
    render(<AuditView />);
    fireEvent.click(screen.getAllByRole("button", { name: /download csv/i })[0]!);

    expect(downloadCsv).toHaveBeenCalled();
    const [filename, body] = vi.mocked(downloadCsv).mock.calls.at(-1)!;
    expect(filename).toContain("orphans");
    expect(body).toContain("https://e.com/orphan-0/");
  });

  it("exports every page, not the five shown as examples", () => {
    /** The card lists five URLs; the file is the worklist. */
    withOrphans(9);
    render(<AuditView />);
    fireEvent.click(screen.getAllByRole("button", { name: /download csv/i })[0]!);

    const [, body] = vi.mocked(downloadCsv).mock.calls.at(-1)!;
    expect(body.trim().split("\n")).toHaveLength(10); // header + 9
  });

  it("keeps the drill-in available alongside it", () => {
    withOrphans(3);
    render(<AuditView />);
    expect(screen.getAllByRole("button", { name: /see all/i }).length).toBeGreaterThan(0);
  });
});
