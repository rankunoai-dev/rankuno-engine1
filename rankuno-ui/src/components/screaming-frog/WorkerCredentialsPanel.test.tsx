import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { message } from "antd";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { WorkerDispatchAdapter } from "../../adapters/adapterInterface";
import { worker } from "../../test/factories";
import { WorkerCredentialsPanel } from "./WorkerCredentialsPanel";

const SECRET = "fresh-secret-value-123";

function fakeApi(overrides: Partial<WorkerDispatchAdapter> = {}): WorkerDispatchAdapter {
  return {
    revokeWorker: vi.fn(async (id: string) => worker({ worker_id: id, is_active: false })),
    rotateWorkerCredential: vi.fn(async (id: string) => ({
      worker_id: id,
      worker_secret: SECRET,
      org_id: "acme",
    })),
    ...overrides,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("WorkerCredentialsPanel", () => {
  it("offers Revoke and Rotate token for an active machine", () => {
    render(<WorkerCredentialsPanel api={fakeApi()} workers={[worker()]} onChanged={vi.fn()} />);

    expect(screen.getByRole("button", { name: "Revoke Studio desktop" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Rotate token for Studio desktop" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("REVOKED")).not.toBeInTheDocument();
  });

  it("tags a revoked machine and offers only rotation as the way back", () => {
    render(
      <WorkerCredentialsPanel
        api={fakeApi()}
        workers={[worker({ is_active: false })]}
        onChanged={vi.fn()}
      />,
    );

    expect(screen.getByText("REVOKED")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Revoke/ })).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Rotate token for Studio desktop" }),
    ).toBeInTheDocument();
  });

  it("offers no actions when the adapter cannot perform them", () => {
    render(<WorkerCredentialsPanel api={{}} workers={[worker()]} onChanged={vi.fn()} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("does not revoke until the confirmation is accepted", async () => {
    const api = fakeApi();
    const onChanged = vi.fn();
    render(<WorkerCredentialsPanel api={api} workers={[worker()]} onChanged={onChanged} />);

    fireEvent.click(screen.getByRole("button", { name: "Revoke Studio desktop" }));
    expect(await screen.findByText(/stops working immediately/)).toBeInTheDocument();
    expect(api.revokeWorker).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Revoke" }));

    await waitFor(() => expect(api.revokeWorker).toHaveBeenCalledWith("wkr-aaaa"));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it("shows a rotated token exactly once, and forgets it on close", async () => {
    const api = fakeApi();
    const log = vi.spyOn(console, "log");
    const success = vi.spyOn(message, "success");
    render(<WorkerCredentialsPanel api={api} workers={[worker()]} onChanged={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Rotate token for Studio desktop" }));
    fireEvent.click(await screen.findByRole("button", { name: "Issue new token" }));

    const field = await screen.findByLabelText("New worker token");
    expect(field).toHaveValue(SECRET);
    expect(screen.getByText("You will not see this token again.")).toBeInTheDocument();
    const occurrences = Array.from(document.querySelectorAll("input, code, p, span, div"))
      .filter((node) => node.children.length === 0)
      .filter(
        (node) =>
          node.textContent?.includes(SECRET) ||
          (node as HTMLInputElement).value === SECRET,
      );
    expect(occurrences).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "I have saved it, close" }));

    await waitFor(() =>
      expect(screen.queryByLabelText("New worker token")).not.toBeInTheDocument(),
    );
    expect(document.body.innerHTML).not.toContain(SECRET);
    for (const call of [...log.mock.calls, ...success.mock.calls]) {
      expect(JSON.stringify(call)).not.toContain(SECRET);
    }
  });

  it("copies the token without echoing it in the toast", async () => {
    const writeText = vi.fn(async () => undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const success = vi.spyOn(message, "success");
    render(<WorkerCredentialsPanel api={fakeApi()} workers={[worker()]} onChanged={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Rotate token for Studio desktop" }));
    fireEvent.click(await screen.findByRole("button", { name: "Issue new token" }));
    fireEvent.click(await screen.findByRole("button", { name: "Copy" }));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith(SECRET));
    await waitFor(() => expect(success).toHaveBeenCalledWith("Token copied."));
  });

  it("reports a failed revoke and leaves the list alone", async () => {
    const error = vi.spyOn(message, "error");
    const onChanged = vi.fn();
    const api = fakeApi({
      revokeWorker: vi.fn(async () => {
        throw new Error("no worker wkr-aaaa");
      }),
    });
    render(<WorkerCredentialsPanel api={api} workers={[worker()]} onChanged={onChanged} />);

    fireEvent.click(screen.getByRole("button", { name: "Revoke Studio desktop" }));
    fireEvent.click(await screen.findByRole("button", { name: "Revoke" }));

    await waitFor(() => expect(error).toHaveBeenCalledWith("no worker wkr-aaaa"));
    expect(onChanged).not.toHaveBeenCalled();
  });
});
