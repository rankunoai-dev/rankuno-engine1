import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useCrawlStore } from "../../store/useCrawlStore";
import { useUiStore } from "../../store/useUiStore";
import { crawl, discovery, page } from "../../test/factories";
import { HeaderBar } from "./HeaderBar";

/**
 * The header bar.
 *
 * Reported as too complex for an analyst, and it was: the site address was
 * printed twice — once as a title, once in the selector beside it — and the
 * status readout spoke in tree nodes and named the rendering strategy. These
 * tests pin the reductions so they are not quietly reinstated.
 */

const NOOP = (): void => {};

function mount(result = crawl({ base_url: "https://www.gep.com/" })) {
  useCrawlStore.setState({
    result,
    jobs: [
      {
        id: "job-1",
        label: "https://www.gep.com/ (+14 from Screaming Frog)",
        baseUrl: "https://www.gep.com/",
        status: "succeeded",
        pagesClassified: result.summary.pages_classified,
        truncated: false,
        synthetic: false,
        crawledAt: "2026-08-20T12:00:00Z",
        hasCheckpoint: false,
      },
    ],
    activeJobId: "job-1",
    liveJobs: {},
    status: "succeeded",
  });
  return render(<HeaderBar navParsed onNewCrawl={NOOP} onPrint={NOOP} />);
}

beforeEach(() => {
  useCrawlStore.setState({ result: null, jobs: [], activeJobId: null, liveJobs: {} });
  useUiStore.setState({ view: "launch", lastMode: "engine", lastEngineView: "visualizer" });
});

describe("HeaderBar", () => {
  it("names the site once, as a host", () => {
    /*
     * It read `Rankuno Engine — https://www.gep.com/` next to a selector
     * reading `https://www.gep.com/ (+14 from Screaming Frog)`: the same
     * address twice, taking half the bar. The product name is on the rail.
     */
    mount();
    expect(screen.getByRole("heading")).toHaveTextContent("www.gep.com");
    expect(screen.queryByText(/Rankuno Engine/)).not.toBeInTheDocument();
  });

  it("counts pages, not tree nodes", () => {
    /*
     * `nodes` included the structural groupings the tree needs to hold its
     * children — 29,248 against 27,656 pages on kinsta — so the header
     * contradicted the KPI card beside it. That mismatch is the one cycle 0022
     * fixed in the audit; it should not survive here.
     */
    mount(
      crawl({
        base_url: "https://www.gep.com/",
        pages: [page("https://www.gep.com/a/"), page("https://www.gep.com/b/")],
      }),
    );
    expect(screen.getByText(/2 pages/)).toBeInTheDocument();
    expect(screen.queryByText(/nodes/)).not.toBeInTheDocument();
  });

  it("does not describe how the list is rendered", () => {
    /* "virtual list" is a note about our code, not a fact about the site. */
    mount();
    expect(screen.queryByText(/virtual list/)).not.toBeInTheDocument();
  });

  it("says when a crawl is only part of the site", () => {
    /* The one qualifier worth the width: a truncated crawl read as complete is
       the failure mode this dashboard has fixed repeatedly. */
    mount(
      crawl({
        base_url: "https://www.gep.com/",
        discovery: discovery({ truncated: true }),
      }),
    );
    expect(screen.getByText(/partial crawl/)).toBeInTheDocument();
  });

  it("still offers the actions an analyst came for", () => {
    mount();
    expect(screen.getByText("PDF")).toBeInTheDocument();
    expect(screen.getByText("Navigation")).toBeInTheDocument();
    expect(screen.getByText("URL path")).toBeInTheDocument();
  });

  it("says so plainly when nothing is loaded", () => {
    render(<HeaderBar navParsed={false} onNewCrawl={NOOP} onPrint={NOOP} />);
    expect(screen.getByRole("heading")).toHaveTextContent("No crawl loaded");
  });

  it("hides New crawl when the data source cannot start one", () => {
    /* Fixtures cannot crawl. A control that fails on click reads as broken. */
    useCrawlStore.setState({ adapter: null });
    mount();
    expect(screen.queryByText("New crawl")).not.toBeInTheDocument();
  });

  it("drops every engine control in Screaming Frog mode", () => {
    /* "New crawl" opens the *engine* crawl form; on the Screaming Frog page
       it would start the other product's crawl. */
    useCrawlStore.setState({
      adapter: {
        listJobs: vi.fn(),
        getResult: vi.fn(),
        getProgress: vi.fn(),
        startJob: vi.fn(),
      } as never,
    });
    useUiStore.setState({ view: "screaming-frog", lastMode: "screaming-frog" });
    mount();

    expect(screen.getByRole("heading")).toHaveTextContent("Screaming Frog");
    expect(screen.queryByText("New crawl")).not.toBeInTheDocument();
    expect(screen.queryByText("PDF")).not.toBeInTheDocument();
    expect(screen.queryByText("Navigation")).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.queryByText(/No crawl loaded/)).not.toBeInTheDocument();
  });

  it("still shows a running engine crawl in Screaming Frog mode", () => {
    /* The Crawl jobs badge is off the rail in this mode; the pill is what
       says the engine crawl is still going. */
    useUiStore.setState({ view: "screaming-frog", lastMode: "screaming-frog" });
    useCrawlStore.setState({
      liveJobs: {
        "job-9": {
          id: "job-9",
          label: "https://kinsta.com/",
          status: "running",
          message: "",
          telemetry: null,
          startedAt: 1,
          endedAt: null,
          error: null,
        },
      },
    });
    render(<HeaderBar navParsed onNewCrawl={NOOP} onPrint={NOOP} />);

    expect(screen.getByText("kinsta.com")).toBeInTheDocument();
  });

  it("shows New crawl when the adapter can start one", () => {
    useCrawlStore.setState({
      adapter: {
        listJobs: vi.fn(),
        getResult: vi.fn(),
        getProgress: vi.fn(),
        startJob: vi.fn(),
      } as never,
    });
    mount();
    expect(screen.getByText("New crawl")).toBeInTheDocument();
  });
});
