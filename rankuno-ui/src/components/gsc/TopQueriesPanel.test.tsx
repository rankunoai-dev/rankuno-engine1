import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CrawlDataAdapter } from "../../adapters/adapterInterface";
import { ApiError } from "../../adapters/httpAdapter";
import { TOP_QUERIES_STOP_COPY } from "../../lib/topQueries";
import { useCrawlStore } from "../../store/useCrawlStore";
import { TopQueriesPanel } from "./TopQueriesPanel";

/**
 * The Search Console top-queries panel.
 *
 * What matters here is what the panel says and when it calls the engine. A
 * partial result must never read as the full one, a response that fails the
 * shape check must never be shown, and the engine must be asked once per click
 * and never on its own. Each test uses its own job id, because the single-flight
 * guard is shared across instances for the life of the module.
 */

const COMPLETE_BODY = {
  rows: 1200,
  complete: true,
  stop_reason: "exhausted",
  start_date: "2025-01-01",
  end_date: "2026-01-01",
};

interface Deferred {
  promise: Promise<unknown>;
  resolve: (value: unknown) => void;
  reject: (cause: unknown) => void;
}

function deferred(): Deferred {
  let resolve: (value: unknown) => void = () => {};
  let reject: (cause: unknown) => void = () => {};
  const promise = new Promise<unknown>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

/** Install a stub adapter that answers `fetchTopQueries` with `respond`. */
function stubAdapter(respond: (jobId: string) => Promise<unknown>) {
  const fetchTopQueries = vi.fn(respond);
  useCrawlStore.setState({
    adapter: { fetchTopQueries } as unknown as CrawlDataAdapter,
  });
  return fetchTopQueries;
}

/**
 * Matched by pattern: while pending antd's spinner adds "loading" to the
 * accessible name, so an exact match would only find the button when idle.
 */
function button(): HTMLElement {
  return screen.getByRole("button", { name: /Fetch Top Queries/ });
}

/**
 * Let every queued promise callback run inside `act`.
 *
 * A zero-delay timer runs after the microtask queue has drained, so the
 * `finally` update that follows an answer lands inside the test. Without it
 * React reports an update made outside `act`.
 */
async function flush(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function clickButton(): Promise<void> {
  await act(async () => {
    fireEvent.click(button());
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

afterEach(() => {
  // Unmount before resetting the store. Otherwise the mounted panel re-renders
  // on the adapter change, outside `act`.
  cleanup();
  useCrawlStore.setState({ adapter: null });
});

describe("TopQueriesPanel rendering gate", () => {
  it("renders nothing without a job id", () => {
    stubAdapter(() => Promise.resolve(COMPLETE_BODY));
    const { container } = render(<TopQueriesPanel jobId={null} finished />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing for a job without a finished result", () => {
    stubAdapter(() => Promise.resolve(COMPLETE_BODY));
    const { container } = render(<TopQueriesPanel jobId="gate-unfinished" finished={false} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when the adapter has no top-queries method", () => {
    useCrawlStore.setState({ adapter: null });
    const { container } = render(<TopQueriesPanel jobId="gate-no-adapter" finished />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders the button with a job id and does not fetch on mount", () => {
    const spy = stubAdapter(() => Promise.resolve(COMPLETE_BODY));
    render(<TopQueriesPanel jobId="mount-1" finished />);
    expect(button()).toBeEnabled();
    expect(spy).not.toHaveBeenCalled();
  });
});

describe("TopQueriesPanel fetch", () => {
  it("calls the adapter once with the job id on click", async () => {
    const spy = stubAdapter(() => Promise.resolve(COMPLETE_BODY));
    render(<TopQueriesPanel jobId="click-1" finished />);

    await clickButton();

    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith("click-1");
    await screen.findByRole("status");
  });

  it("disables the button while pending and does not call again on a second click", async () => {
    const pending = deferred();
    const spy = stubAdapter(() => pending.promise);
    render(<TopQueriesPanel jobId="pending-1" finished />);

    await clickButton();
    expect(button()).toBeDisabled();

    // A disabled button emits no click, so the second press never reaches the
    // handler. The in-flight set backs this up for any press that did.
    await clickButton();
    expect(spy).toHaveBeenCalledTimes(1);

    pending.resolve(COMPLETE_BODY);
    await flush();
    await waitFor(() => expect(button()).toBeEnabled());
  });

  it("renders a complete result as a row count with the fixed copy", async () => {
    stubAdapter(() => Promise.resolve(COMPLETE_BODY));
    render(<TopQueriesPanel jobId="success-1" finished />);

    await clickButton();

    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent("1,200 rows fetched.");
    expect(status).toHaveTextContent(TOP_QUERIES_STOP_COPY.exhausted);
    expect(status).not.toHaveTextContent("Partial");
  });

  it("labels a partial result and gives its stop reason", async () => {
    stubAdapter(() =>
      Promise.resolve({ rows: 5000, complete: false, stop_reason: "row_cap" }),
    );
    render(<TopQueriesPanel jobId="partial-1" finished />);

    await clickButton();

    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent("Partial result:");
    expect(status).toHaveTextContent("5,000 rows received.");
    expect(status).toHaveTextContent(TOP_QUERIES_STOP_COPY.row_cap);
    expect(status).toHaveTextContent("Do not read this as the full result.");
  });

  it("refuses a response whose fields fail the shape check", async () => {
    // `complete` says full while `stop_reason` says the cap was hit: the two
    // state one fact, so this is a broken answer and nothing is shown.
    stubAdapter(() =>
      Promise.resolve({ rows: 3, complete: true, stop_reason: "row_cap" }),
    );
    render(<TopQueriesPanel jobId="invalid-1" finished />);

    await clickButton();

    expect(
      await screen.findByText(/the answer could not be read\. Nothing is shown\./),
    ).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("refuses a negative or non-integer row count", async () => {
    stubAdapter(() => Promise.resolve({ ...COMPLETE_BODY, rows: -1 }));
    render(<TopQueriesPanel jobId="invalid-2" finished />);

    await clickButton();

    await screen.findByText(/could not be read/);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});

describe("TopQueriesPanel errors", () => {
  it("shows the server detail for a 409 in an error notice", async () => {
    stubAdapter(() =>
      Promise.reject(
        new ApiError(409, "this crawl was run without a Search Console property"),
      ),
    );
    render(<TopQueriesPanel jobId="err-409" finished />);

    await clickButton();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("this crawl was run without a Search Console property");
    expect(button()).toBeEnabled();
  });

  it("shows the server detail for a 403 without guessing its meaning", async () => {
    stubAdapter(() =>
      Promise.reject(new ApiError(403, "this Search Console account cannot access the property")),
    );
    render(<TopQueriesPanel jobId="err-403" finished />);

    await clickButton();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The engine refused this request. this Search Console account cannot access the property",
    );
  });

  it("says nothing was saved on a 502, starts a cooldown, and never retries on its own", async () => {
    const spy = stubAdapter(() =>
      Promise.reject(
        new ApiError(502, "Search Console did not answer; the saved query data was kept"),
      ),
    );
    render(<TopQueriesPanel jobId="err-502" finished />);

    await clickButton();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Nothing was saved, so any earlier result still stands.");
    expect(alert).toHaveTextContent("Search Console did not answer");
    expect(button()).toBeDisabled();
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("uses generic copy for an unexpected status", async () => {
    stubAdapter(() => Promise.reject(new ApiError(500, "Internal Server Error")));
    render(<TopQueriesPanel jobId="err-500" finished />);

    await clickButton();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Top queries could not be fetched. Try again in a moment.",
    );
  });
});

describe("TopQueriesPanel job change", () => {
  it("discards a response that arrives after the selected job has changed", async () => {
    const pending = deferred();
    stubAdapter((jobId) => (jobId === "switch-a" ? pending.promise : Promise.resolve(COMPLETE_BODY)));
    const { rerender } = render(<TopQueriesPanel jobId="switch-a" finished />);

    await clickButton();
    rerender(<TopQueriesPanel jobId="switch-b" finished />);

    pending.resolve(COMPLETE_BODY);
    await flush();

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(button()).toBeEnabled();
  });
});

/** A job row as the store holds it, with only the fields the panel reads. */
function listJob(id: string, hasDeletePassword: boolean): void {
  useCrawlStore.setState({
    jobs: [{ id, hasDeletePassword }] as unknown as ReturnType<typeof useCrawlStore.getState>["jobs"],
  });
}

/** Type a password into the open prompt and press its confirm button. */
async function submitPassword(password: string): Promise<void> {
  const dialog = await screen.findByRole("dialog");
  const input = dialog.querySelector("input[type=password]") as HTMLInputElement;
  fireEvent.change(input, { target: { value: password } });
  await act(async () => {
    fireEvent.click(within(dialog).getByRole("button", { name: /Fetch Top Queries/ }));
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

describe("TopQueriesPanel job password (ADR 0042)", () => {
  afterEach(() => {
    useCrawlStore.setState({ jobs: [] });
  });

  it("asks for the deletion password on a protected job and sends it in the header", async () => {
    listJob("pw-ok", true);
    const spy = stubAdapter(() => Promise.resolve(COMPLETE_BODY));
    render(<TopQueriesPanel jobId="pw-ok" finished />);

    await clickButton();
    expect(spy).not.toHaveBeenCalled();

    await submitPassword("crawl-password-12");

    expect(spy).toHaveBeenCalledTimes(1);
    const [jobId, init] = spy.mock.calls[0] as unknown as [string, RequestInit];
    expect(jobId).toBe("pw-ok");
    expect(new Headers(init.headers).get("X-Deletion-Password")).toBe("crawl-password-12");
    expect(await screen.findByRole("status")).toHaveTextContent("1,200 rows fetched");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("keeps the prompt open and shows the server reason when the password is wrong", async () => {
    listJob("pw-wrong", true);
    stubAdapter(() => Promise.reject(new ApiError(403, "incorrect password")));
    render(<TopQueriesPanel jobId="pw-wrong" finished />);

    await clickButton();
    await submitPassword("not-the-password");

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("alert")).toHaveTextContent("incorrect password");
    expect(dialog.querySelector("input[type=password]")).toBeInTheDocument();
  });

  it("prompts on a 403 'job password required' even when the list did not flag the job", async () => {
    listJob("pw-fallback", false);
    const spy = stubAdapter(() => Promise.reject(new ApiError(403, "job password required")));
    render(<TopQueriesPanel jobId="pw-fallback" finished />);

    await clickButton();

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(spy).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
