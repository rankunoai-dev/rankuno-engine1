import { describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { WorkerDispatchAdapter } from "../../adapters/adapterInterface";
import {
  crawlJob,
  dispatchPreview,
  urlListSources,
  urlListView,
  worker,
} from "../../test/factories";
import { ApiError } from "../../adapters/httpAdapter";
import { useUiStore } from "../../store/useUiStore";
import { ScreamingFrogView } from "./ScreamingFrogView";

/**
 * The states this screen exists for.
 *
 * Every one of them used to be an empty dropdown. "No machine registered",
 * "registered but asleep" and "has never told us what it holds" are three
 * different problems with three different next actions, and a picker with
 * nothing in it is the same picture for all three.
 *
 * The adapter is built once per test and passed in by prop: it is the hook
 * dependency behind two effects, and a fresh object per render would fetch in
 * a loop — which is exactly the bug the `api`-not-`bind(api)` comments in the
 * components are about.
 */
function makeApi(overrides: Partial<WorkerDispatchAdapter> = {}): WorkerDispatchAdapter {
  return {
    listWorkers: vi.fn().mockResolvedValue({ workers: [], offline_after_s: 60 }),
    listWorkerJobs: vi.fn().mockResolvedValue([]),
    ...overrides,
  };
}


/** An online machine, which every list-mode test below needs first. */
function onlineWorker() {
  return {
    workers: [worker({ is_online: true, last_seen_at: "2026-09-21T10:00:00Z" })],
    offline_after_s: 60,
  };
}

/** Switch to list mode and pick a crawl and a subset from the default fixtures. */
async function chooseOrphanList(): Promise<void> {
  fireEvent.click(
    await screen.findByRole("radio", { name: /A list of URLs from a finished Rankuno crawl/ }),
  );
  await waitFor(() => {
    expect(screen.getByLabelText("Source crawl")).toBeEnabled();
  });
  fireEvent.mouseDown(screen.getByLabelText("Source crawl"));
  fireEvent.click(await screen.findByTitle("example.com — https://www.example.com/"));
  fireEvent.click(await screen.findByRole("radio", { name: /Orphans Only/ }));
  // Settle anything the choice started inside act; see the picker's own suite.
  await act(async () => {});
}

/** Sources with orphans available, which the factory default deliberately lacks. */
function withOrphans(candidate: number) {
  const base = urlListSources();
  return urlListSources({
    sources: [
      {
        ...base.sources[0]!,
        available: true,
        unavailable_reason: "",
        candidate_url_count: candidate,
      },
      base.sources[1]!,
    ],
  });
}

describe("ScreamingFrogView", () => {
  it("explains what a worker is when none is registered", async () => {
    const api = makeApi({ previewDispatch: vi.fn() });

    render(<ScreamingFrogView adapter={api} />);

    await waitFor(() => {
      expect(screen.getByText(/no machine is registered yet/i)).toBeInTheDocument();
    });
    // What a worker actually is, and the call that makes one — there is no
    // screen for registration yet, so the screen has to say so.
    expect(screen.getByText(/your own Windows PC/i)).toBeInTheDocument();
    expect(screen.getByText(/POST \/api\/v1\/workers/)).toBeInTheDocument();
    // And no machine picker at all, rather than an empty one.
    expect(screen.queryByLabelText("Machine")).not.toBeInTheDocument();
  });

  it("blocks the launch for an offline machine, with the reason and the threshold visible", async () => {
    const api = makeApi({
      listWorkers: vi.fn().mockResolvedValue({
        workers: [
          worker({
            display_name: "Studio desktop",
            is_online: false,
            last_seen_at: "2026-09-21T09:00:00Z",
          }),
        ],
        offline_after_s: 60,
      }),
      previewDispatch: vi.fn(),
    });

    render(<ScreamingFrogView adapter={api} />);

    await waitFor(() => {
      expect(screen.getByText(/Studio desktop is not checked in/i)).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: /review and launch/i })).toBeDisabled();
    // The reason is text on the page, not a tooltip on a disabled control:
    // a disabled button never receives hover on a touch device.
    expect(
      screen.getByText(/offline after 60s without checking in/i),
    ).toBeInTheDocument();
    expect(api.previewDispatch).not.toHaveBeenCalled();
  });

  it("distinguishes a machine that has never reported from one holding no templates", async () => {
    const api = makeApi({
      listWorkers: vi.fn().mockResolvedValue({
        workers: [worker({ is_online: true, last_seen_at: "2026-09-21T10:00:00Z" })],
        offline_after_s: 60,
      }),
      getWorkerTemplates: vi.fn().mockResolvedValue({
        worker_id: "wkr-aaaa",
        templates: [],
        unrecognised_count: 0,
        // Never checked in. Absence of a report, not a report of absence.
        reported_at: null,
      }),
      previewDispatch: vi.fn(),
    });

    render(<ScreamingFrogView adapter={api} />);

    await waitFor(() => {
      expect(
        screen.getByText(/has not reported its templates yet/i),
      ).toBeInTheDocument();
    });
    expect(screen.queryByText(/no templates available/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/reported no saved templates/i)).not.toBeInTheDocument();
  });

  it("says a machine reported none when it has actually checked in", async () => {
    const api = makeApi({
      listWorkers: vi.fn().mockResolvedValue({
        workers: [worker({ is_online: true, last_seen_at: "2026-09-21T10:00:00Z" })],
        offline_after_s: 60,
      }),
      getWorkerTemplates: vi.fn().mockResolvedValue({
        worker_id: "wkr-aaaa",
        templates: [],
        unrecognised_count: 0,
        reported_at: "2026-09-21T10:00:00Z",
      }),
      previewDispatch: vi.fn(),
    });

    render(<ScreamingFrogView adapter={api} />);

    await waitFor(() => {
      expect(screen.getByText(/reported no saved templates/i)).toBeInTheDocument();
    });
  });

  it("shows the note a human wrote about the chosen template, as text", async () => {
    // The whole point of the feature: a `.seospiderconfig` is an opaque binary,
    // so this sentence is the only description of it that can ever exist.
    const api = makeApi({
      listWorkers: vi.fn().mockResolvedValue({
        workers: [worker({ is_online: true, last_seen_at: "2026-09-21T10:00:00Z" })],
        offline_after_s: 60,
      }),
      getWorkerTemplates: vi.fn().mockResolvedValue({
        worker_id: "wkr-aaaa",
        templates: [
          { name: "js-crawl", description: "Extracts SKU, price & stock <status>." },
          { name: "plain", description: "" },
        ],
        unrecognised_count: 0,
        reported_at: "2026-09-21T10:00:00Z",
      }),
      previewDispatch: vi.fn(),
    });

    render(<ScreamingFrogView adapter={api} />);

    await waitFor(() => {
      expect(screen.getByText(/2 templates reported/i)).toBeInTheDocument();
    });
    // Nothing is shown until a template is chosen: "None" has no description.
    expect(screen.queryByText(/Extracts SKU/)).not.toBeInTheDocument();

    fireEvent.mouseDown(screen.getByLabelText("Screaming Frog template"));
    fireEvent.click(await screen.findByTitle("js-crawl"));

    const note = await screen.findByText("Extracts SKU, price & stock <status>.");
    // A text node, not markup: the string came from a machine outside the
    // trust boundary, and the angle brackets must stay visible characters.
    expect(note.innerHTML).toBe("Extracts SKU, price &amp; stock &lt;status&gt;.");
  });

  it("drops the note when the chosen template does not carry one", async () => {
    const api = makeApi({
      listWorkers: vi.fn().mockResolvedValue({
        workers: [worker({ is_online: true, last_seen_at: "2026-09-21T10:00:00Z" })],
        offline_after_s: 60,
      }),
      getWorkerTemplates: vi.fn().mockResolvedValue({
        worker_id: "wkr-aaaa",
        templates: [{ name: "plain", description: "" }],
        unrecognised_count: 0,
        reported_at: "2026-09-21T10:00:00Z",
      }),
      previewDispatch: vi.fn(),
    });

    render(<ScreamingFrogView adapter={api} />);

    await waitFor(() => {
      expect(screen.getByText(/1 template reported/i)).toBeInTheDocument();
    });
    fireEvent.mouseDown(screen.getByLabelText("Screaming Frog template"));
    fireEvent.click(await screen.findByTitle("plain"));

    expect(document.querySelector(".sfd-template-note")).toBeNull();
  });

  it("answers 'where are the include and exclude boxes' with the chosen template's own note", async () => {
    // The RAE screen had two pattern textareas here. Neither reaches
    // Screaming Frog from a command line, so the form offers a disclosure
    // rather than a box that discards what is typed into it — and the
    // disclosure ends on the one thing that is actually actionable: what the
    // config the operator just picked says it skips.
    const api = makeApi({
      listWorkers: vi.fn().mockResolvedValue(onlineWorker()),
      getWorkerTemplates: vi.fn().mockResolvedValue({
        worker_id: "wkr-aaaa",
        templates: [{ name: "js-crawl", description: "Skips /admin/ and /login/." }],
        unrecognised_count: 0,
        reported_at: "2026-09-21T10:00:00Z",
      }),
      previewDispatch: vi.fn(),
    });

    render(<ScreamingFrogView adapter={api} />);

    await waitFor(() => {
      expect(screen.getByText(/1 template reported/i)).toBeInTheDocument();
    });
    fireEvent.mouseDown(screen.getByLabelText("Screaming Frog template"));
    fireEvent.click(await screen.findByTitle("js-crawl"));

    fireEvent.click(screen.getByRole("button", { name: /Include & Exclude/ }));
    expect(
      screen.getByText(/no command-line setting for include or exclude patterns/i),
    ).toBeInTheDocument();
    // The disclosure reads the live selection, not a copy taken when it
    // rendered: this is the sentence the operator came here for.
    expect(screen.getAllByText("Skips /admin/ and /login/.")).toHaveLength(2);

    // And nowhere on the form is there anything to type a pattern into. Only
    // the seed URL takes free text.
    expect(document.querySelectorAll("textarea")).toHaveLength(0);
    expect(screen.getAllByRole("textbox")).toHaveLength(1);
  });

  it("offers no GA4 fields, and says why adding them would not be enough", async () => {
    const api = makeApi({
      listWorkers: vi.fn().mockResolvedValue(onlineWorker()),
      previewDispatch: vi.fn(),
    });

    render(<ScreamingFrogView adapter={api} />);

    await waitFor(() => {
      expect(screen.getByLabelText("Screaming Frog template")).toBeInTheDocument();
    });
    // The four boxes RAE drew, by their labels. None of them exists here.
    for (const label of [/gmail/i, /GA4 account/i, /GA4 property/i, /data stream/i]) {
      expect(screen.queryByLabelText(label)).not.toBeInTheDocument();
    }

    fireEvent.click(screen.getByRole("button", { name: /Google Analytics 4/ }));
    expect(screen.getByText(/recorded with the crawl and then dropped/)).toBeInTheDocument();
    expect(screen.getByText(/ask for the Analytics tab/)).toBeInTheDocument();
  });

  it("says how many config files the machine could not offer, and why", async () => {
    // The trap: Screaming Frog's own Save As writes
    // `SEO Spider Config - Basic.seospiderconfig`, which is not a slug. Those
    // files used to vanish, leaving an empty dropdown over a full folder.
    const api = makeApi({
      listWorkers: vi.fn().mockResolvedValue({
        workers: [worker({ is_online: true, last_seen_at: "2026-09-21T10:00:00Z" })],
        offline_after_s: 60,
      }),
      getWorkerTemplates: vi.fn().mockResolvedValue({
        worker_id: "wkr-aaaa",
        templates: [],
        unrecognised_count: 3,
        reported_at: "2026-09-21T10:00:00Z",
      }),
      previewDispatch: vi.fn(),
    });

    render(<ScreamingFrogView adapter={api} />);

    await waitFor(() => {
      expect(screen.getByText(/3 files were not recognised/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/rename it on that machine/i)).toBeInTheDocument();
  });

  it("previews before it confirms, and confirms with the server's normalized URL", async () => {
    const preview = dispatchPreview({ seed_url: "https://www.example.com/" });
    const confirmDispatch = vi.fn().mockResolvedValue({ id: "wj-9", status: "queued" });
    const api = makeApi({
      listWorkers: vi.fn().mockResolvedValue({
        workers: [worker({ is_online: true, last_seen_at: "2026-09-21T10:00:00Z" })],
        offline_after_s: 60,
      }),
      previewDispatch: vi.fn().mockResolvedValue(preview),
      confirmDispatch,
    });

    render(<ScreamingFrogView adapter={api} />);

    const input = await screen.findByLabelText("Seed URL");
    // Deliberately *not* the normalized form: the confirm must send back what
    // the server said, not what was typed here.
    fireEvent.change(input, { target: { value: "https://www.example.com" } });
    fireEvent.click(screen.getByRole("button", { name: /review and launch/i }));

    await waitFor(() => {
      expect(api.previewDispatch).toHaveBeenCalledTimes(1);
    });
    // Nothing has run yet — this is the approval step, not the launch.
    expect(confirmDispatch).not.toHaveBeenCalled();
    expect(
      await screen.findByText(/confirm this screaming frog crawl/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/normalized form of what you typed/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /launch on studio desktop/i }));

    await waitFor(() => {
      expect(confirmDispatch).toHaveBeenCalledWith("wkr-aaaa", {
        token: "tok-1",
        seed_url: "https://www.example.com/",
        template_name: null,
        correlation_id: "ui-test-1",
      });
    });
  });

  it("refuses a URL the server would refuse, without spending a round trip", async () => {
    const previewDispatch = vi.fn();
    const api = makeApi({
      listWorkers: vi.fn().mockResolvedValue({
        workers: [worker({ is_online: true, last_seen_at: "2026-09-21T10:00:00Z" })],
        offline_after_s: 60,
      }),
      previewDispatch,
    });

    render(<ScreamingFrogView adapter={api} />);

    const input = await screen.findByLabelText("Seed URL");
    fireEvent.change(input, { target: { value: "example.com" } });
    fireEvent.click(screen.getByRole("button", { name: /review and launch/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/must be a full URL/i);
    expect(previewDispatch).not.toHaveBeenCalled();
  });

  it("offers a retry, not a blank screen, when the machine list cannot be read", async () => {
    const listWorkers = vi
      .fn()
      .mockRejectedValueOnce(new Error("Cannot reach the engine at http://x/api/v1."))
      .mockResolvedValue({ workers: [], offline_after_s: 60 });
    const api = makeApi({ listWorkers, previewDispatch: vi.fn() });

    render(<ScreamingFrogView adapter={api} />);

    await waitFor(() => {
      expect(screen.getByText(/could not read the list of machines/i)).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));

    await waitFor(() => {
      expect(listWorkers).toHaveBeenCalledTimes(2);
    });
  });

  it("states that fixture mode cannot dispatch instead of failing on click", async () => {
    // `previewDispatch` absent is exactly what `MockAdapter` looks like.
    const api = makeApi();

    render(<ScreamingFrogView adapter={api} />);

    await waitFor(() => {
      expect(screen.getByText(/fixture mode/i)).toBeInTheDocument();
    });
  });

  it("sends a list dispatch, and approves the count the server built, not the estimate", async () => {
    // The two numbers differ on purpose. 4,330 is what the source picker can
    // say before filtering; 4,312 is what the preview actually generated,
    // deduped and domain-filtered, and it is the only one an approval may
    // show. A count in an approval that is not the count dispatched is the
    // exact failure this feature had at the backend level.
    const preview = dispatchPreview({
      seed_url: "https://www.example.com/",
      url_list: urlListView({ url_count: 4_312, sha256: "c".repeat(64) }),
    });
    const confirmDispatch = vi.fn().mockResolvedValue({ id: "wj-9", status: "queued" });
    const api = makeApi({
      listWorkers: vi.fn().mockResolvedValue(onlineWorker()),
      listJobs: vi.fn().mockResolvedValue([crawlJob()]),
      listUrlListSources: vi.fn().mockResolvedValue(withOrphans(4_330)),
      previewDispatch: vi.fn().mockResolvedValue(preview),
      confirmDispatch,
    });

    render(<ScreamingFrogView adapter={api} />);
    await chooseOrphanList();

    // The seed came from the source crawl, not from a keyboard: it is the
    // domain the list was filtered against.
    expect(screen.getByLabelText("Site")).toHaveValue("https://www.example.com/");
    fireEvent.click(screen.getByRole("button", { name: /review and launch/i }));

    await waitFor(() => {
      expect(api.previewDispatch).toHaveBeenCalledWith("wkr-aaaa", {
        seed_url: "https://www.example.com/",
        template_name: null,
        correlation_id: expect.stringMatching(/^ui-/),
        url_list: { source_job_id: "job-1", source: "orphans" },
      });
    });

    // Scoped to the dialog: the form behind it still shows the estimate, and
    // that is fine. What must never happen is the estimate appearing inside
    // the approval, where it would be read as the number being dispatched.
    const dialog = within(await screen.findByRole("dialog"));
    expect(dialog.getByText(/4,312 URLs from example\.com/)).toBeInTheDocument();
    expect(dialog.queryByText(/4,330/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /launch on studio desktop/i }));
    await waitFor(() => {
      expect(confirmDispatch).toHaveBeenCalledWith("wkr-aaaa", {
        token: "tok-1",
        seed_url: "https://www.example.com/",
        template_name: null,
        correlation_id: "ui-test-1",
        url_list_sha256: "c".repeat(64),
      });
    });
  });

  it("will not preview a list dispatch with no list chosen", async () => {
    const api = makeApi({
      listWorkers: vi.fn().mockResolvedValue(onlineWorker()),
      listJobs: vi.fn().mockResolvedValue([crawlJob()]),
      listUrlListSources: vi.fn().mockResolvedValue(urlListSources()),
      previewDispatch: vi.fn(),
    });

    render(<ScreamingFrogView adapter={api} />);
    const input = await screen.findByLabelText("Seed URL");
    fireEvent.change(input, { target: { value: "https://www.example.com/" } });
    fireEvent.click(
      screen.getByRole("radio", { name: /A list of URLs from a finished Rankuno crawl/ }),
    );

    // A seed alone is enough for a spidering crawl and is not enough here: a
    // list preview with no source would build no list and queue a plain site
    // crawl under a heading that says otherwise.
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /review and launch/i })).toBeDisabled();
    });
    expect(screen.getByText(/Choose the crawl to take URLs from/i)).toBeInTheDocument();
    expect(api.previewDispatch).not.toHaveBeenCalled();
  });

  it("surfaces the engine's refusal to trim an oversized list, in its own words", async () => {
    // 422 from the preview, not a generic failure: this is a decision the
    // operator has to make differently, not something to retry.
    const detail =
      "this crawl's 'all' URL list holds 12,431 URLs, over the 10,000 ceiling (SCREAMING_FROG_URL_LIST_MAX_URLS), so nothing was generated. A shorter list is not silently substituted because the run would then audit fewer pages than the approval says. Choose 'Orphans Only', which is smaller and is the recommended source.";
    const api = makeApi({
      listWorkers: vi.fn().mockResolvedValue(onlineWorker()),
      listJobs: vi.fn().mockResolvedValue([crawlJob()]),
      listUrlListSources: vi.fn().mockResolvedValue(withOrphans(4_330)),
      previewDispatch: vi.fn().mockRejectedValue(new ApiError(422, detail)),
    });

    render(<ScreamingFrogView adapter={api} />);
    await chooseOrphanList();
    fireEvent.click(screen.getByRole("button", { name: /review and launch/i }));

    // Said before the server's sentence: nothing ran, and nothing will run
    // with fewer URLs. "It went ahead with 10,000 of them" is the reasonable
    // wrong guess about a ceiling, and it is the one that would be acted on.
    expect(
      await screen.findByText(/nothing was prepared, and no shortened crawl will run/i),
    ).toBeInTheDocument();
    expect(screen.getByText(detail)).toBeInTheDocument();
    // Nothing was approved, so no dialog opened.
    expect(screen.queryByText(/confirm this screaming frog crawl/i)).not.toBeInTheDocument();
  });

  it("drops the chosen list when the operator goes back to spidering", async () => {
    const api = makeApi({
      listWorkers: vi.fn().mockResolvedValue(onlineWorker()),
      listJobs: vi.fn().mockResolvedValue([crawlJob()]),
      listUrlListSources: vi.fn().mockResolvedValue(withOrphans(4_330)),
      previewDispatch: vi.fn().mockResolvedValue(dispatchPreview()),
    });

    render(<ScreamingFrogView adapter={api} />);
    await chooseOrphanList();
    fireEvent.click(screen.getByRole("radio", { name: /Spider from a seed URL/ }));
    fireEvent.click(screen.getByRole("button", { name: /review and launch/i }));

    // No `url_list` at all — absent, not an empty one. Its presence on the
    // wire is what puts the worker into list mode.
    await waitFor(() => {
      expect(api.previewDispatch).toHaveBeenCalledWith("wkr-aaaa", {
        seed_url: "https://www.example.com/",
        template_name: null,
        correlation_id: expect.stringMatching(/^ui-/),
      });
    });
  });

  it("disables list mode, with the reason, when the engine cannot be asked", async () => {
    // `listUrlListSources` absent is what an older engine and fixture mode
    // both look like. Offering a radio that fails on click is worse.
    const api = makeApi({
      listWorkers: vi.fn().mockResolvedValue(onlineWorker()),
      previewDispatch: vi.fn(),
    });

    render(<ScreamingFrogView adapter={api} />);

    const listMode = await screen.findByRole("radio", {
      name: /A list of URLs from a finished Rankuno crawl/,
    });
    expect(listMode).toBeDisabled();
    expect(screen.getByText(/cannot read the engine's own crawls/i)).toBeInTheDocument();
    // The ordinary crawl is unaffected.
    expect(screen.getByRole("radio", { name: /Spider from a seed URL/ })).toBeChecked();
  });

  it("reports a crawl that cannot supply the URLs as a decision, not a fault", async () => {
    const detail =
      "No Screaming Frog cross-check has been run against this crawl yet, and an orphan " +
      "is defined by that comparison.";
    const api = makeApi({
      listWorkers: vi.fn().mockResolvedValue(onlineWorker()),
      listJobs: vi.fn().mockResolvedValue([crawlJob()]),
      listUrlListSources: vi.fn().mockResolvedValue(withOrphans(37)),
      previewDispatch: vi.fn().mockRejectedValue(new ApiError(409, detail)),
      confirmDispatch: vi.fn(),
    });

    render(<ScreamingFrogView adapter={api} />);
    await screen.findByLabelText("Machine");
    await chooseOrphanList();
    fireEvent.click(screen.getByRole("button", { name: /review and launch/i }));

    expect(
      await screen.findByText(/nothing was prepared — that crawl cannot supply those URLs/i),
    ).toBeInTheDocument();
    expect(screen.getByText(detail)).toBeInTheDocument();
  });

  it("opens on the crawl a cross-check sent it to, without answering which URLs", async () => {
    const api = makeApi({
      listWorkers: vi.fn().mockResolvedValue(onlineWorker()),
      listJobs: vi.fn().mockResolvedValue([crawlJob({ id: "job-1" })]),
      listUrlListSources: vi.fn().mockResolvedValue(withOrphans(37)),
      previewDispatch: vi.fn(),
    });
    // What "Run in Screaming Frog" on the reconciliation panel does.
    act(() => {
      useUiStore.getState().startListCrawl("job-1");
    });

    render(<ScreamingFrogView adapter={api} />);

    // List mode, on that crawl, with its sources already read.
    await waitFor(() => {
      expect(api.listUrlListSources).toHaveBeenCalledWith("job-1");
    });
    expect(screen.getByRole("radio", { name: /A list of URLs from a finished/ })).toBeChecked();
    // But the subset is still unanswered — that is the decision being
    // approved, and arriving here is not a choice of it.
    expect(screen.getByRole("radio", { name: /Orphans Only/ })).not.toBeChecked();
    expect(screen.getByRole("radio", { name: /All Discovered URLs/ })).not.toBeChecked();
    expect(screen.getByRole("button", { name: /review and launch/i })).toBeDisabled();
    expect(
      screen.getByText(/choose the crawl to take URLs from, and which of its URLs to send/i),
    ).toBeInTheDocument();

    // Consumed once: coming back to this screen must not re-arm list mode.
    expect(useUiStore.getState().listCrawlSourceJobId).toBeNull();
  });
});
