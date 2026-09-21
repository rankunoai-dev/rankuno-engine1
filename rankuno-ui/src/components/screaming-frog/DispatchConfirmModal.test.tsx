import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { WorkerJobAccepted } from "../../adapters/adapterInterface";
import { ApiError } from "../../adapters/httpAdapter";
import { dispatchPreview } from "../../test/factories";
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
      typedUrl="https://www.example.com/"
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
});
