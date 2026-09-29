import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { WorkerJobAccepted } from "../../adapters/adapterInterface";
import { ApiError } from "../../adapters/httpAdapter";
import { dispatchPreview, urlListView } from "../../test/factories";
import { DispatchConfirmModal } from "./DispatchConfirmModal";

/**
 * The approval half of preview → confirm.
 *
 * Three of these tests are about things that are *not* errors in the operator's
 * world and read as alarming ones if handled generically: a token that ran out
 * of time, a second click on the same button, and a PC that went to sleep
 * between the two steps.
 */
function renderModal(
  overrides: {
    preview?: ReturnType<typeof dispatchPreview>;
    confirm?: (request: unknown) => Promise<WorkerJobAccepted>;
    /** Absent for a list dispatch: nobody typed an address there. */
    typedUrl?: string;
  } = {},
) {
  const confirm = vi.fn(
    overrides.confirm ?? (async () => ({ id: "wj-9", status: "queued" })),
  );
  const onDispatched = vi.fn();
  const onClose = vi.fn();
  const onStartAgain = vi.fn();
  render(
    <DispatchConfirmModal
      preview={overrides.preview ?? dispatchPreview()}
      workerName="Studio desktop"
      typedUrl={"typedUrl" in overrides ? overrides.typedUrl : "https://www.example.com/"}
      confirm={confirm}
      onDispatched={onDispatched}
      onClose={onClose}
      onStartAgain={onStartAgain}
    />,
  );
  return { confirm, onDispatched, onClose, onStartAgain };
}

describe("DispatchConfirmModal", () => {
  it("shows exactly what was approved, and that nothing has run", () => {
    renderModal({
      preview: dispatchPreview({
        seed_url: "https://shop.example.com/",
        template_name: "deep-crawl",
      }),
    });

    expect(screen.getByText("https://shop.example.com/")).toBeInTheDocument();
    expect(screen.getByText("deep-crawl")).toBeInTheDocument();
    expect(screen.getByText(/nothing has started yet/i)).toBeInTheDocument();
    expect(screen.getByText(/approval expires in/i)).toBeInTheDocument();
  });

  it("names the absence of a template rather than leaving the row blank", () => {
    renderModal({ preview: dispatchPreview({ template_name: null }) });

    expect(screen.getByText(/own default configuration/i)).toBeInTheDocument();
  });

  it("dispatches once when the launch button is double-clicked", async () => {
    let release: (accepted: WorkerJobAccepted) => void = () => {};
    const confirm = () =>
      new Promise<WorkerJobAccepted>((resolve) => {
        release = resolve;
      });
    const { confirm: spy, onDispatched } = renderModal({ confirm });

    const button = screen.getByRole("button", { name: /launch on studio desktop/i });
    fireEvent.click(button);
    fireEvent.click(button);

    // The second POST would 403 with "already used" — a true statement about a
    // token and a frightening one about a crawl. It is never sent.
    expect(spy).toHaveBeenCalledTimes(1);

    release({ id: "wj-9", status: "queued" });
    await waitFor(() => {
      expect(onDispatched).toHaveBeenCalledTimes(1);
    });
  });

  it("offers a fresh start, not a dead button, once the approval expires", async () => {
    const { confirm } = renderModal({
      // One second of life: expiry has to be observed on the clock this
      // component runs, not simulated by rendering something already dead.
      preview: dispatchPreview({ expires_at: new Date(Date.now() + 1_000).toISOString() }),
    });

    expect(screen.getByRole("button", { name: /launch on studio desktop/i })).toBeEnabled();

    await waitFor(
      () => {
        expect(screen.getByText(/this approval has expired/i)).toBeInTheDocument();
      },
      { timeout: 4_000 },
    );
    expect(
      screen.queryByRole("button", { name: /launch on studio desktop/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /start again/i })).toBeInTheDocument();
    expect(confirm).not.toHaveBeenCalled();
  });

  it("warns before the operator commits when the preview says the machine is offline", () => {
    renderModal({
      preview: dispatchPreview({
        worker_online: false,
        worker_last_seen_at: null,
      }),
    });

    expect(screen.getByText(/Studio desktop is not checked in/i)).toBeInTheDocument();
    expect(screen.getByText(/has never checked in/i)).toBeInTheDocument();
    // Blocked here rather than left to come back as a 409 after the click.
    expect(screen.getByRole("button", { name: /launch on studio desktop/i })).toBeDisabled();
  });

  it("surfaces the server's own 409 wording, which already says what to do", async () => {
    const detail =
      "worker wkr-aaaa is offline (last seen 2026-09-21T09:00:00+00:00); start the Rankuno worker daemon on that machine and try again";
    renderModal({
      confirm: () => Promise.reject(new ApiError(409, detail)),
    });

    fireEvent.click(screen.getByRole("button", { name: /launch on studio desktop/i }));

    expect(await screen.findByText(detail)).toBeInTheDocument();
    // The token was never spent, so launching again is a real option.
    expect(screen.getByRole("button", { name: /launch on studio desktop/i })).toBeEnabled();
  });

  it("treats a spent token calmly, and does not offer to post it again", async () => {
    renderModal({
      confirm: () =>
        Promise.reject(
          new ApiError(403, "dispatch preview token is invalid, expired, or already used"),
        ),
    });

    fireEvent.click(screen.getByRole("button", { name: /launch on studio desktop/i }));

    expect(await screen.findByText(/nothing was dispatched twice/i)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /launch on studio desktop/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /start again/i })).toBeInTheDocument();
  });

  it("explains a capacity refusal instead of showing a raw 429", async () => {
    renderModal({
      confirm: () => Promise.reject(new ApiError(429, "facet is at capacity (1 concurrent)")),
    });

    fireEvent.click(screen.getByRole("button", { name: /launch on studio desktop/i }));

    expect(
      await screen.findByText(/only one Screaming Frog crawl runs at a time/i),
    ).toBeInTheDocument();
  });

  it("shows what a list run will actually audit, not only where it starts", async () => {
    renderModal({
      typedUrl: undefined,
      preview: dispatchPreview({
        seed_url: "https://www.example.com/",
        url_list: urlListView({
          url_count: 4_312,
          source_label: "example.com weekly",
          counts: {
            source_rows: 4_360,
            duplicates_dropped: 30,
            non_http_dropped: 0,
            off_domain_dropped: 18,
            unsafe_host_dropped: 0,
            kept: 4_312,
          },
        }),
      }),
    });

    // The count, in the heading, with the crawl it came from beside it. An
    // operator approving "4,312 orphan URLs" and getting a site crawl is the
    // failure this whole summary exists to prevent.
    expect(screen.getByText(/4,312 URLs from example\.com weekly/)).toBeInTheDocument();
    // And that this is not a crawl of the site, said in the dialog.
    expect(screen.getByText(/does not spider outward/i)).toBeInTheDocument();
    expect(screen.getByText(/\(orphans only\)/i)).toBeInTheDocument();
    // The exclusion count with the rule that produced it: a number with no
    // rule beside it cannot be checked by the person approving it.
    expect(screen.getByText(/18 external URLs/)).toBeInTheDocument();
    expect(screen.getByText(/outside example\.com/)).toBeInTheDocument();
    // A sample, verbatim, so a five-figure count is checkable at all.
    expect(screen.getByText("https://www.example.com/orphan-a")).toBeInTheDocument();
    // The seed is labelled as the site, not as where the spider starts.
    expect(screen.getByText("Site")).toBeInTheDocument();
    expect(screen.queryByText("Seed URL")).not.toBeInTheDocument();
  });

  it("echoes the approved digest back verbatim and nothing else", async () => {
    const list = urlListView({ sha256: "b".repeat(64) });
    const { confirm } = renderModal({
      typedUrl: undefined,
      preview: dispatchPreview({ url_list: list }),
    });

    fireEvent.click(screen.getByRole("button", { name: /launch on studio desktop/i }));

    await waitFor(() => {
      expect(confirm).toHaveBeenCalledWith({
        token: "tok-1",
        seed_url: "https://www.example.com/",
        template_name: null,
        correlation_id: "ui-test-1",
        // Not recomputed from `sample`, which holds three of 4,312 URLs, and
        // not normalised: the digest names the exact bytes the worker fetches.
        url_list_sha256: "b".repeat(64),
      });
    });
  });

  it("omits the digest entirely for an ordinary spidering crawl", async () => {
    const { confirm } = renderModal();

    fireEvent.click(screen.getByRole("button", { name: /launch on studio desktop/i }));

    await waitFor(() => {
      expect(confirm).toHaveBeenCalledTimes(1);
    });
    // Absent, not `null` or `""`: the field's presence is what puts the worker
    // into list mode, and an empty string would fail the server's pattern.
    expect(Object.keys(confirm.mock.calls[0]?.[0] as object)).not.toContain(
      "url_list_sha256",
    );
  });

  it("does not blame the machine when it is the approved list that is gone", async () => {
    // Both are 404s on the same route. The list is stored under a retention
    // window, so an approval can outlive the bytes it names — and sending that
    // operator to check a PC that is fine is the wrong errand entirely.
    const detail =
      "the approved URL list is no longer available; it expired or was never generated for this organization. Preview again.";
    renderModal({
      typedUrl: undefined,
      preview: dispatchPreview({ url_list: urlListView() }),
      confirm: () => Promise.reject(new ApiError(404, detail)),
    });

    fireEvent.click(screen.getByRole("button", { name: /launch on studio desktop/i }));

    expect(await screen.findByText(detail)).toBeInTheDocument();
    expect(screen.queryByText(/no longer registered/i)).not.toBeInTheDocument();
    // Re-posting the same digest would fail identically forever.
    expect(screen.getByRole("button", { name: /start again/i })).toBeInTheDocument();
  });

  it("still names the machine for a 404 on an ordinary crawl", async () => {
    renderModal({ confirm: () => Promise.reject(new ApiError(404, "no worker wkr-aaaa")) });

    fireEvent.click(screen.getByRole("button", { name: /launch on studio desktop/i }));

    expect(await screen.findByText(/no longer registered/i)).toBeInTheDocument();
  });

  it("says nothing about a normalization when nobody typed an address", () => {
    renderModal({
      typedUrl: undefined,
      preview: dispatchPreview({ url_list: urlListView() }),
    });

    // The seed was filled in from the source crawl. A note comparing it to
    // "what you typed" would be about text that was never entered.
    expect(screen.queryByText(/normalized form of what you typed/i)).not.toBeInTheDocument();
  });

  it("says Screaming Frog is busy in its own words, and keeps the approval alive", async () => {
    // One crawl at a time, on purpose: Screaming Frog appends to a `trace.txt`
    // shared by every invocation on the machine, and the licence read depends
    // on exactly one supervised process writing to it. The server explains all
    // of that; paraphrasing it would leave "409" on screen instead.
    const detail =
      "Screaming Frog runs 1 crawl at a time on a worker, because its licence log is " +
      "shared across every invocation on that machine. Job wj-7 is already running. " +
      "Wait for it to finish, or cancel it, then try again.";
    renderModal({
      typedUrl: undefined,
      preview: dispatchPreview({ url_list: urlListView() }),
      confirm: () => Promise.reject(new ApiError(409, detail)),
    });

    fireEvent.click(screen.getByRole("button", { name: /launch on studio desktop/i }));

    expect(await screen.findByText(detail)).toBeInTheDocument();
    // The token was refused before it was spent, so the same approval still
    // stands: the operator waits and launches, rather than starting over.
    expect(
      screen.getByRole("button", { name: /launch on studio desktop/i }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /start again/i })).not.toBeInTheDocument();
  });
});
