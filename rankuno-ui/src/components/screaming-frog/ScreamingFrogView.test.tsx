import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { WorkerDispatchAdapter } from "../../adapters/adapterInterface";
import { dispatchPreview, worker } from "../../test/factories";
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
        reported_at: "2026-09-21T10:00:00Z",
      }),
      previewDispatch: vi.fn(),
    });

    render(<ScreamingFrogView adapter={api} />);

    await waitFor(() => {
      expect(screen.getByText(/reported no saved templates/i)).toBeInTheDocument();
    });
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
});
