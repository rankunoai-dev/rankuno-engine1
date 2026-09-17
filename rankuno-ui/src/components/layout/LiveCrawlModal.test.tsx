import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CrawlDataAdapter } from "../../adapters/adapterInterface";
import { useCrawlStore } from "../../store/useCrawlStore";
import type { PageClassificationInput } from "../../types/schema";
import { LiveCrawlModal } from "./LiveCrawlModal";

/**
 * The Search Console account picker on the live-crawl form.
 *
 * The rule under test: the picker exists only when the engine lists at least
 * one named profile. A data source that cannot list accounts, or one that
 * lists none, gets no control at all — and whatever is submitted then carries
 * `gsc_account: null`, which the engine reads as the default credentials.
 */

const ACCOUNT_LABEL = "Search Console account";
const NOOP = (): void => {};

function adapter(listGscAccounts?: CrawlDataAdapter["listGscAccounts"]): CrawlDataAdapter {
  const base: CrawlDataAdapter = {
    listJobs: vi.fn().mockResolvedValue([]),
    getResult: vi.fn(),
    getProgress: vi.fn(),
    startJob: vi.fn().mockResolvedValue("job-1"),
  };
  return listGscAccounts ? { ...base, listGscAccounts } : base;
}

function mount(source: CrawlDataAdapter) {
  const startCrawl = vi.fn().mockResolvedValue("job-1");
  useCrawlStore.setState({ adapter: source, startCrawl });
  render(<LiveCrawlModal open onClose={NOOP} />);
  return startCrawl;
}

async function submit(startCrawl: ReturnType<typeof vi.fn>): Promise<PageClassificationInput> {
  fireEvent.change(screen.getByPlaceholderText("https://www.example.com/"), {
    target: { value: "https://e.com/" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Start crawl" }));
  await waitFor(() => expect(startCrawl).toHaveBeenCalledTimes(1));
  return startCrawl.mock.calls[0]?.[0] as PageClassificationInput;
}

beforeEach(() => {
  useCrawlStore.setState({ adapter: null, error: null });
});

describe("LiveCrawlModal account picker", () => {
  it("is absent when the data source cannot list accounts", async () => {
    /* Fixtures. A picker whose choices cannot be fetched reads as broken. */
    const startCrawl = mount(adapter());
    expect(screen.queryByText(ACCOUNT_LABEL)).not.toBeInTheDocument();

    const request = await submit(startCrawl);
    expect(request.gsc_account).toBeNull();
  });

  it("is absent when the engine lists no accounts", async () => {
    const list = vi.fn().mockResolvedValue([]);
    const startCrawl = mount(adapter(list));
    await waitFor(() => expect(list).toHaveBeenCalledTimes(1));
    expect(screen.queryByText(ACCOUNT_LABEL)).not.toBeInTheDocument();

    const request = await submit(startCrawl);
    expect(request.gsc_account).toBeNull();
  });

  it("is absent when the account list cannot be fetched", async () => {
    /* An engine that answers `/jobs` but not `/gsc/accounts` is an older
       build. The crawl must still be startable, on the default account. */
    const list = vi.fn().mockRejectedValue(new Error("404 Not Found"));
    const startCrawl = mount(adapter(list));
    await waitFor(() => expect(list).toHaveBeenCalledTimes(1));
    expect(screen.queryByText(ACCOUNT_LABEL)).not.toBeInTheDocument();

    const request = await submit(startCrawl);
    expect(request.gsc_account).toBeNull();
  });

  it(
    "lists the names and submits the chosen one",
    async () => {
      const startCrawl = mount(adapter(vi.fn().mockResolvedValue(["acme", "globex"])));
      expect(await screen.findByText(ACCOUNT_LABEL)).toBeInTheDocument();

      fireEvent.mouseDown(screen.getByRole("combobox", { name: ACCOUNT_LABEL }));
      // Scoped to the dropdown portal: the closed Select's own selection box
      // carries the same `title` as the option row, so an unscoped query finds
      // two. The portal is behind a motion wrapper and a cold jsdom takes
      // several seconds to produce it — well past the 1 s default.
      const dropdown = await waitFor(
        () => {
          const node = document.querySelector<HTMLElement>(".ant-select-dropdown");
          if (!node) throw new Error("dropdown not open yet");
          return node;
        },
        { timeout: 15_000 },
      );
      expect(within(dropdown).getByTitle("Default (.env.local)")).toBeInTheDocument();
      expect(within(dropdown).getByTitle("globex")).toBeInTheDocument();
      fireEvent.click(within(dropdown).getByTitle("acme"));

      const request = await submit(startCrawl);
      expect(request.gsc_account).toBe("acme");
    },
    30_000,
  );

  it("submits null when the operator leaves the default selected", async () => {
    const startCrawl = mount(adapter(vi.fn().mockResolvedValue(["acme"])));
    expect(await screen.findByText(ACCOUNT_LABEL)).toBeInTheDocument();

    const request = await submit(startCrawl);
    expect(request.gsc_account).toBeNull();
  });
});

/**
 * The fourth "Custom" crawl speed.
 *
 * The rule under test: presets keep reading their own bundled
 * rate/concurrency pair unchanged, while "custom" reads two independent
 * operator-entered values instead — with its own bounds, its own seeded
 * concurrency default, and a non-blocking slow-crawl advisory.
 */
describe("LiveCrawlModal custom speed", () => {
  function fillBaseUrl(): void {
    fireEvent.change(screen.getByPlaceholderText("https://www.example.com/"), {
      target: { value: "https://e.com/" },
    });
  }

  function selectCustom(): void {
    fireEvent.click(screen.getByText("Custom"));
  }

  it("reveals independent rate and concurrency inputs seeded with Polite's concurrency", () => {
    mount(adapter());
    selectCustom();

    const rateInput = screen.getByRole("spinbutton", { name: "Requests per second" });
    const concurrencyInput = screen.getByRole("spinbutton", { name: "Concurrency" });
    expect(rateInput).toHaveValue("");
    expect(concurrencyInput).toHaveValue("5");
  });

  it("blocks submission on a blank custom rate", async () => {
    const startCrawl = mount(adapter());
    fillBaseUrl();
    selectCustom();

    fireEvent.click(screen.getByRole("button", { name: "Start crawl" }));
    expect(await screen.findByText("Enter a requests-per-second value.")).toBeInTheDocument();
    expect(startCrawl).not.toHaveBeenCalled();
  });

  it("submits the custom rate and concurrency instead of a preset's", async () => {
    const startCrawl = mount(adapter());
    fillBaseUrl();
    selectCustom();

    fireEvent.change(screen.getByRole("spinbutton", { name: "Requests per second" }), {
      target: { value: "0.2" },
    });
    fireEvent.change(screen.getByRole("spinbutton", { name: "Concurrency" }), {
      target: { value: "8" },
    });

    const request = await submit(startCrawl);
    expect(request.rate_limit_rps).toBe(0.2);
    expect(request.concurrency).toBe(8);
  });

  it("still submits a preset's own rate and concurrency when custom is never selected", async () => {
    const startCrawl = mount(adapter());
    fillBaseUrl();
    fireEvent.click(screen.getByText("Standard"));

    const request = await submit(startCrawl);
    expect(request.rate_limit_rps).toBe(10);
    expect(request.concurrency).toBe(20);
  });

  it("warns, without blocking, when a slow custom rate implies a very long crawl", async () => {
    const startCrawl = mount(adapter());
    fillBaseUrl();
    selectCustom();

    fireEvent.change(screen.getByRole("spinbutton", { name: "Requests per second" }), {
      target: { value: "0.05" },
    });
    fireEvent.change(screen.getByLabelText("Page ceiling"), { target: { value: "5000" } });

    expect(
      await screen.findByText("This rate and page ceiling could take well over 6 hours."),
    ).toBeInTheDocument();

    // Advisory only: submission still succeeds.
    const request = await submit(startCrawl);
    expect(request.rate_limit_rps).toBe(0.05);
    expect(startCrawl).toHaveBeenCalledTimes(1);
  });
});
