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
