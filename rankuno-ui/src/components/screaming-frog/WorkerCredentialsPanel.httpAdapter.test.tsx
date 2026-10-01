import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { message } from "antd";
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";
import { HttpAdapter } from "../../adapters/httpAdapter";
import { worker } from "../../test/factories";
import { WorkerCredentialsPanel } from "./WorkerCredentialsPanel";

/**
 * Revoke and rotate driven through a real `HttpAdapter`, not a mock object.
 *
 * A plain `vi.fn()` never reads `this`, so a component that pulled
 * `adapter.revokeWorker` off the instance and called it detached would pass
 * every mock-based test and throw on `this.baseUrl` in production — the bug
 * `CrawlJobsView.httpAdapter.test.tsx` was written for. Only `fetch` is
 * stubbed here.
 */

const API = "http://engine.test";
const SECRET = "rotated-secret-from-server";

let fetchMock: ReturnType<typeof vi.fn>;
let errorToast: MockInstance<typeof message.error>;

function respond(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  fetchMock = vi.fn(async (url: string) =>
    url.endsWith("/rotate-credential")
      ? respond({ worker_id: "wkr-aaaa", worker_secret: SECRET, org_id: "acme" })
      : respond(worker({ is_active: false })),
  );
  vi.stubGlobal("fetch", fetchMock);
  errorToast = vi.spyOn(message, "error");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("WorkerCredentialsPanel through a real HttpAdapter", () => {
  it("Revoke posts to the revoke route", async () => {
    const onChanged = vi.fn();
    render(
      <WorkerCredentialsPanel
        api={new HttpAdapter(API)}
        workers={[worker()]}
        onChanged={onChanged}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Revoke Studio desktop" }));
    fireEvent.click(await screen.findByRole("button", { name: "Revoke" }));

    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(errorToast).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledWith(
      `${API}/workers/wkr-aaaa/revoke`,
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("Rotate token posts to the rotate route and shows the returned secret", async () => {
    render(
      <WorkerCredentialsPanel
        api={new HttpAdapter(API)}
        workers={[worker()]}
        onChanged={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Rotate token for Studio desktop" }));
    fireEvent.click(await screen.findByRole("button", { name: "Issue new token" }));

    expect(await screen.findByLabelText("New worker token")).toHaveValue(SECRET);
    expect(errorToast).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledWith(
      `${API}/workers/wkr-aaaa/rotate-credential`,
      expect.objectContaining({ method: "POST" }),
    );
  });
});
