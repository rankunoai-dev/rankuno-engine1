import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { WorkerDispatchAdapter } from "../../adapters/adapterInterface";
import { pasteCounts, pastedUrlPlan } from "../../test/factories";
import { UrlListPastePanel } from "./UrlListPastePanel";

/**
 * Pasting a list of URLs, and being told what will actually be crawled.
 *
 * The assertions here are deliberately about **what the operator is told**,
 * not about what the adapter was called with. The number on this panel is the
 * one a human reads before they approve a crawl of somebody's site, and the
 * failures worth catching are the ones where it is silently not the number
 * that runs: a paste spanning two domains reduced without saying so, lines
 * dropped without a word, an over-ceiling list offered as if it would work.
 *
 * Nothing here parses anything. That is the point — the panel posts the raw
 * text and renders the server's answer, so these tests can state the answer
 * and check the rendering rather than re-implementing a parser.
 */
function makeApi(overrides: Partial<WorkerDispatchAdapter> = {}): WorkerDispatchAdapter {
  return {
    planPastedUrlList: vi.fn().mockResolvedValue(pastedUrlPlan()),
    ...overrides,
  };
}

/** Paste text and press the check button, as an operator does. */
function paste(text: string): void {
  fireEvent.change(screen.getByLabelText("URLs to crawl"), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Check this list" }));
}

describe("UrlListPastePanel", () => {
  it("sends the raw text unsplit, so one parser owns the count", async () => {
    const api = makeApi();
    render(<UrlListPastePanel api={api} onChange={vi.fn()} />);

    paste("https://www.example.com/a\nhttps://www.example.com/b");

    await waitFor(() => {
      expect(api.planPastedUrlList).toHaveBeenCalledWith(
        "https://www.example.com/a\nhttps://www.example.com/b",
      );
    });
  });

  it("reports a clean paste as a count of URLs read from a count of lines", async () => {
    render(<UrlListPastePanel api={makeApi()} onChange={vi.fn()} />);

    paste("https://www.example.com/a");

    expect(await screen.findByText(/3 URLs read from 3 lines, before filtering/)).toBeVisible();
  });

  it("reports blank lines and whitespace as handled rather than silently", async () => {
    const api = makeApi({
      planPastedUrlList: vi.fn().mockResolvedValue(
        pastedUrlPlan({ counts: pasteCounts({ lines: 7, blank_dropped: 4, accepted: 3 }) }),
      ),
    });
    render(<UrlListPastePanel api={api} onChange={vi.fn()} />);

    paste("  https://www.example.com/a  \n\n\n");

    expect(await screen.findByText(/4 blank lines ignored/)).toBeVisible();
  });

  it("names the lines it could not read, with their line numbers", async () => {
    const api = makeApi({
      planPastedUrlList: vi.fn().mockResolvedValue(
        pastedUrlPlan({
          counts: pasteCounts({
            lines: 4,
            accepted: 2,
            malformed_dropped: 2,
            malformed_examples: ["line 2: Page Title", "line 4: mailto:a@b.test"],
          }),
        }),
      ),
    });
    render(<UrlListPastePanel api={api} onChange={vi.fn()} />);

    paste("anything");

    // A bare count says there is a problem and nothing about where it is.
    expect(
      await screen.findByText(/2 lines could not be read as a web address/),
    ).toBeVisible();
    expect(screen.getByText("line 2: Page Title")).toBeVisible();
    expect(screen.getByText("line 4: mailto:a@b.test")).toBeVisible();
  });

  it("says an assumed https:// was added rather than leaving it invisible", async () => {
    const api = makeApi({
      planPastedUrlList: vi
        .fn()
        .mockResolvedValue(pastedUrlPlan({ counts: pasteCounts({ scheme_added: 3 }) })),
    });
    render(<UrlListPastePanel api={api} onChange={vi.fn()} />);

    paste("example.com/a");

    expect(
      await screen.findByText(/3 addresses had no https:\/\/ and were assumed to be https/),
    ).toBeVisible();
  });

  it("offers both domains of a two-site paste and pre-selects the larger", async () => {
    const api = makeApi({
      planPastedUrlList: vi.fn().mockResolvedValue(
        pastedUrlPlan({
          domains: [
            {
              registrable_domain: "example.com",
              url_count: 380,
              suggested_seed_url: "https://www.example.com/",
            },
            {
              registrable_domain: "other.test",
              url_count: 20,
              suggested_seed_url: "https://other.test/",
            },
          ],
        }),
      ),
    });
    const onChange = vi.fn();
    render(<UrlListPastePanel api={api} onChange={onChange} />);

    paste("two sites worth");

    // Neither refused nor silently reduced: both are on screen with counts.
    expect(await screen.findByRole("radio", { name: /example\.com — 380 URLs/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /other\.test — 20 URLs/ })).not.toBeChecked();
    expect(
      screen.getByText(/covers more than one site, and one crawl can only audit one/),
    ).toBeVisible();
    expect(onChange).toHaveBeenLastCalledWith({
      urls: "two sites worth",
      seedUrl: "https://www.example.com/",
    });
  });

  it("switches the seed URL when the operator picks the other site", async () => {
    const api = makeApi({
      planPastedUrlList: vi.fn().mockResolvedValue(
        pastedUrlPlan({
          domains: [
            {
              registrable_domain: "example.com",
              url_count: 380,
              suggested_seed_url: "https://www.example.com/",
            },
            {
              registrable_domain: "other.test",
              url_count: 20,
              suggested_seed_url: "https://other.test/",
            },
          ],
        }),
      ),
    });
    const onChange = vi.fn();
    render(<UrlListPastePanel api={api} onChange={onChange} />);

    paste("two sites worth");
    fireEvent.click(await screen.findByRole("radio", { name: /other\.test — 20 URLs/ }));

    expect(onChange).toHaveBeenLastCalledWith({
      urls: "two sites worth",
      seedUrl: "https://other.test/",
    });
  });

  it("refuses an over-ceiling paste instead of offering a shortened one", async () => {
    const api = makeApi({
      planPastedUrlList: vi.fn().mockResolvedValue(
        pastedUrlPlan({
          exceeds_ceiling: true,
          max_urls: 10_000,
          counts: pasteCounts({ lines: 12_000, accepted: 12_000 }),
          domains: [
            {
              registrable_domain: "example.com",
              url_count: 12_000,
              suggested_seed_url: "https://www.example.com/",
            },
          ],
        }),
      ),
    });
    const onChange = vi.fn();
    render(<UrlListPastePanel api={api} onChange={onChange} />);

    paste("far too many");

    expect(await screen.findByText(/That is more than 10,000 URLs\./)).toBeVisible();
    expect(screen.getByText(/audits fewer pages than the approval says/)).toBeVisible();
    // No choice is reported, so nothing upstream can be previewed.
    expect(onChange).not.toHaveBeenCalledWith(expect.objectContaining({ urls: "far too many" }));
  });

  it("says so when nothing in the paste was a web address", async () => {
    const api = makeApi({
      planPastedUrlList: vi.fn().mockResolvedValue(
        pastedUrlPlan({
          domains: [],
          suggested_seed_url: "",
          counts: pasteCounts({ lines: 2, accepted: 0, malformed_dropped: 2 }),
        }),
      ),
    });
    const onChange = vi.fn();
    render(<UrlListPastePanel api={api} onChange={onChange} />);

    paste("Page Title\nanother title");

    expect(await screen.findByText("No web addresses in that list.")).toBeVisible();
    expect(onChange).not.toHaveBeenCalledWith(expect.objectContaining({ urls: expect.any(String) }));
  });

  it("cannot be checked while the box is empty", () => {
    render(<UrlListPastePanel api={makeApi()} onChange={vi.fn()} />);

    expect(screen.getByRole("button", { name: "Check this list" })).toBeDisabled();
  });

  it("withdraws the choice the moment the text is edited", async () => {
    const onChange = vi.fn();
    render(<UrlListPastePanel api={makeApi()} onChange={onChange} />);

    paste("https://www.example.com/a");
    await screen.findByRole("radio", { name: /example\.com/ });
    onChange.mockClear();

    // An approval describes one list. This is the moment that list changed.
    fireEvent.change(screen.getByLabelText("URLs to crawl"), {
      target: { value: "https://www.example.com/b" },
    });

    expect(onChange).toHaveBeenLastCalledWith(null);
    expect(screen.queryByRole("radio", { name: /example\.com/ })).toBeNull();
  });

  it("surfaces a server refusal rather than showing a stale reading", async () => {
    const api = makeApi({
      planPastedUrlList: vi.fn().mockRejectedValue(new Error("That list is too large to send.")),
    });
    render(<UrlListPastePanel api={api} onChange={vi.fn()} />);

    paste("anything");

    expect(await screen.findByText("That list is too large to send.")).toBeVisible();
  });

  it("is not offered at all when the engine cannot check a paste", () => {
    render(<UrlListPastePanel api={{}} onChange={vi.fn()} />);

    expect(
      screen.getByText("This mode cannot check a pasted list, so there is nothing to send."),
    ).toBeVisible();
    expect(screen.queryByLabelText("URLs to crawl")).toBeNull();
  });
});
