import { describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { WorkerDispatchAdapter } from "../../adapters/adapterInterface";
import { crawlJob, urlListSources } from "../../test/factories";
import { UrlListSourcePicker } from "./UrlListSourcePicker";

/**
 * Picking the URLs a `--crawl-list` dispatch will send.
 *
 * The tests that matter most here are the ones about an option the operator
 * *cannot* have. "Orphans Only" is unavailable far more often than it is
 * available — it needs a saved Screaming Frog cross-check to exist at all —
 * and a greyed-out control with no sentence beside it is the single most
 * reported UI failure in this product.
 */
function makeApi(overrides: Partial<WorkerDispatchAdapter> = {}): WorkerDispatchAdapter {
  return {
    listJobs: vi.fn().mockResolvedValue([crawlJob()]),
    listUrlListSources: vi.fn().mockResolvedValue(urlListSources()),
    ...overrides,
  };
}

/**
 * Choose the one crawl the default adapter offers.
 *
 * Waits for the picker to be *enabled* rather than merely present: the label
 * renders before `listJobs` resolves, so acting on it earlier would settle the
 * fetch outside React's act window and warn.
 */
async function chooseFirstCrawl(): Promise<void> {
  await waitFor(() => {
    expect(screen.getByLabelText("Source crawl")).toBeEnabled();
  });
  fireEvent.mouseDown(screen.getByLabelText("Source crawl"));
  fireEvent.click(await screen.findByTitle("example.com — https://www.example.com/"));
  // Drain whatever the choice started, inside React's act window. `await` on
  // this helper is itself an unwrapped microtask boundary, so without it an
  // already-resolved sources fetch would settle outside act — noise about the
  // test, not about the component. A request that is still pending stays
  // pending, which is what the loading-state test below relies on.
  await act(async () => {});
}

describe("UrlListSourcePicker", () => {
  it("takes its crawls from /jobs, the engine's own id space", async () => {
    const api = makeApi();
    const onChange = vi.fn();

    render(<UrlListSourcePicker api={api} onChange={onChange} />);

    await waitFor(() => {
      expect(api.listJobs).toHaveBeenCalledTimes(1);
    });
    await chooseFirstCrawl();

    // The id handed to the sources endpoint is the `/jobs` id, never a
    // `/workers/jobs` one. The two spaces have no join, and every request in
    // the wrong one answers 404.
    await waitFor(() => {
      expect(api.listUrlListSources).toHaveBeenCalledWith("job-1");
    });
  });

  it("reports a complete choice, with the source crawl's own root", async () => {
    const onChange = vi.fn();
    render(<UrlListSourcePicker api={makeApi()} onChange={onChange} />);

    await chooseFirstCrawl();
    fireEvent.click(await screen.findByRole("radio", { name: /All Discovered URLs/ }));

    expect(onChange).toHaveBeenLastCalledWith({
      source_job_id: "job-1",
      source: "all",
      base_url: "https://www.example.com/",
    });
  });

  it("withdraws the choice when the source crawl changes", async () => {
    const api = makeApi({
      listJobs: vi
        .fn()
        .mockResolvedValue([crawlJob(), crawlJob({ id: "job-2", label: "shop" })]),
    });
    const onChange = vi.fn();
    render(<UrlListSourcePicker api={api} onChange={onChange} />);

    await chooseFirstCrawl();
    fireEvent.click(await screen.findByRole("radio", { name: /All Discovered URLs/ }));
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ source: "all" }));

    fireEvent.mouseDown(screen.getByLabelText("Source crawl"));
    fireEvent.click(await screen.findByTitle("shop — https://www.example.com/"));

    // A subset chosen from one crawl says nothing about another. Left
    // standing, it would dispatch one crawl's URLs under another's name.
    expect(onChange).toHaveBeenLastCalledWith(null);
    // And the radio does not stay lit under the new crawl's options, which
    // would show a choice the parent has already been told it does not have.
    expect(await screen.findByRole("radio", { name: /All Discovered URLs/ })).not.toBeChecked();
  });

  it("says why Orphans Only is unavailable rather than greying it out in silence", async () => {
    const onChange = vi.fn();
    render(<UrlListSourcePicker api={makeApi()} onChange={onChange} />);

    await chooseFirstCrawl();

    const orphans = await screen.findByRole("radio", { name: /Orphans Only/ });
    expect(orphans).toBeDisabled();
    expect(
      screen.getByText(/No Screaming Frog cross-check has been run/i),
    ).toBeInTheDocument();

    // Disabled means disabled: clicking it reports nothing.
    fireEvent.click(orphans);
    expect(onChange).not.toHaveBeenCalledWith(
      expect.objectContaining({ source: "orphans" }),
    );
  });

  it("tells an operator with no orphans that there is nothing to send", async () => {
    // The crawl was cross-checked and every URL was reachable by following
    // links. Not an error, and not a reason to offer a list run that would
    // start, find nothing and report success.
    const api = makeApi({
      listUrlListSources: vi.fn().mockResolvedValue(
        urlListSources({
          sources: [
            {
              source: "orphans",
              label: "Orphans Only (Recommended)",
              description: "Only the pages no internal link reaches.",
              available: false,
              unavailable_reason:
                "The cross-check for this crawl found no orphans: every URL this engine discovered was also reachable by following links. There is nothing for a list crawl to add.",
              candidate_url_count: 0,
              exceeds_ceiling: false,
            },
            ...urlListSources().sources.slice(1),
          ],
        }),
      ),
    });
    render(<UrlListSourcePicker api={api} onChange={vi.fn()} />);

    await chooseFirstCrawl();

    expect(await screen.findByText(/found no orphans/i)).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Orphans Only/ })).toBeDisabled();
    // Zero is stated, not hidden: "0 URLs" is the fact, and an absent count
    // would read as "not counted".
    expect(screen.getByText(/about 0 URLs before filtering/i)).toBeInTheDocument();
    // "All Discovered URLs" is still a real option — this crawl has URLs, they
    // are simply all reachable.
    expect(screen.getByRole("radio", { name: /All Discovered URLs/ })).toBeEnabled();
  });

  it("surfaces the server's ceiling refusal, with the ceiling and the alternative", async () => {
    const api = makeApi({
      listUrlListSources: vi.fn().mockResolvedValue(
        urlListSources({
          sources: [
            urlListSources().sources[0]!,
            {
              source: "all",
              label: "All Discovered URLs",
              description: "Every URL this crawl discovered.",
              available: false,
              unavailable_reason:
                "This crawl holds more than 10,000 URLs, the ceiling for one list (SCREAMING_FROG_URL_LIST_MAX_URLS). The list is not trimmed to fit, because a trimmed list audits fewer pages than the approval says it does. Use 'Orphans Only', which is smaller and is the recommended source.",
              candidate_url_count: 10_001,
              exceeds_ceiling: true,
            },
          ],
        }),
      ),
    });
    render(<UrlListSourcePicker api={api} onChange={vi.fn()} />);

    await chooseFirstCrawl();

    expect(await screen.findByText(/the ceiling for one list/i)).toBeInTheDocument();
    expect(screen.getByText(/not trimmed to fit/i)).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /All Discovered URLs/ })).toBeDisabled();
    // A count that stopped at the ceiling is a floor, and is worded as one.
    expect(screen.getByText(/more than 10,001 URLs/i)).toBeInTheDocument();
    // And the ceiling itself is the server's number, not a constant in here.
    expect(screen.getByText(/at most 10,000 URLs/i)).toBeInTheDocument();
  });

  it("says it is working while a large crawl is read", async () => {
    let release: (view: ReturnType<typeof urlListSources>) => void = () => {};
    const api = makeApi({
      listUrlListSources: vi.fn(
        () =>
          new Promise<ReturnType<typeof urlListSources>>((resolve) => {
            release = resolve;
          }),
      ),
    });
    render(<UrlListSourcePicker api={api} onChange={vi.fn()} />);

    await chooseFirstCrawl();

    // Building this answer streams a crawl result that can be tens of
    // megabytes. Silence there reads as a dead control.
    expect(await screen.findByRole("status")).toHaveTextContent(
      /a large crawl takes a few seconds/i,
    );

    release(urlListSources());
    await waitFor(() => {
      expect(screen.queryByRole("status")).not.toBeInTheDocument();
    });
  });

  it("offers a retry, not a blank panel, when the sources cannot be read", async () => {
    const listUrlListSources = vi
      .fn()
      .mockRejectedValueOnce(new Error("Cannot reach the engine at http://x/api/v1."))
      .mockResolvedValue(urlListSources());
    render(
      <UrlListSourcePicker api={makeApi({ listUrlListSources })} onChange={vi.fn()} />,
    );

    await chooseFirstCrawl();

    expect(
      await screen.findByText(/Cannot reach the engine at http:\/\/x\/api\/v1\./),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));

    await waitFor(() => {
      expect(listUrlListSources).toHaveBeenCalledTimes(2);
    });
    expect(await screen.findByRole("radio", { name: /All Discovered URLs/ })).toBeEnabled();
  });

  it("offers a retry when the crawl list itself cannot be read", async () => {
    const listJobs = vi
      .fn()
      .mockRejectedValueOnce(new Error("Cannot reach the engine at http://x/api/v1."))
      .mockResolvedValue([crawlJob()]);
    render(<UrlListSourcePicker api={makeApi({ listJobs })} onChange={vi.fn()} />);

    expect(
      await screen.findByText(/your finished crawls could not be read/i),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));

    await waitFor(() => {
      expect(listJobs).toHaveBeenCalledTimes(2);
    });
    expect(await screen.findByText(/1 finished crawl to choose from/i)).toBeInTheDocument();
  });

  it("offers only crawls that could hold URLs, and says so when none do", async () => {
    const api = makeApi({
      listJobs: vi
        .fn()
        .mockResolvedValue([
          crawlJob({ id: "job-r", status: "running" }),
          crawlJob({ id: "job-f", status: "failed" }),
          crawlJob({ id: "job-q", status: "queued" }),
        ]),
    });
    render(<UrlListSourcePicker api={api} onChange={vi.fn()} />);

    // A running crawl has nothing finished to take; a failed one has nothing
    // at all. Offering them would mean a picker whose entries mostly answer
    // "this crawl has not finished, so it has no URLs to send".
    expect(await screen.findByText(/No finished Rankuno crawl yet/i)).toBeInTheDocument();
    expect(screen.getByLabelText("Source crawl")).toBeDisabled();
  });

  it("says the mode cannot work rather than offering a picker fixtures cannot fill", async () => {
    // What `MockAdapter` looks like: no `listUrlListSources`.
    render(<UrlListSourcePicker api={{ listJobs: vi.fn() }} onChange={vi.fn()} />);

    expect(
      await screen.findByText(/cannot read the engine's own crawls/i),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Source crawl")).not.toBeInTheDocument();
  });
});
