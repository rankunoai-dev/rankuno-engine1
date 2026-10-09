import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  HttpAdapter,
  authorizedFetch,
  downloadFile,
  setAuthToken,
  setSessionExpiredHandler,
} from "./httpAdapter";

/**
 * The ADR 0016 plumbing `authorizedFetch` adds underneath every adapter call:
 * the bearer header, and treating a `401` (and only a `401`) as a dead
 * session. `HttpAdapter`'s own methods are exercised through the store tests
 * and components that call them; this file is the one place the header
 * attachment and the `401`/`403` distinction are checked directly.
 */

vi.stubGlobal("fetch", vi.fn());

afterEach(() => {
  vi.clearAllMocks();
  setAuthToken(null);
  setSessionExpiredHandler(null);
});

describe("authorizedFetch", () => {
  it("attaches the stored token as a bearer header", async () => {
    setAuthToken("session-token-abc");
    (fetch as any).mockResolvedValueOnce(new Response("{}", { status: 200 }));

    await authorizedFetch("http://engine/api/v1/jobs");

    const [, init] = (fetch as any).mock.calls[0];
    expect((init.headers as Headers).get("Authorization")).toBe("Bearer session-token-abc");
  });

  it("sends no Authorization header when signed out", async () => {
    setAuthToken(null);
    (fetch as any).mockResolvedValueOnce(new Response("{}", { status: 200 }));

    await authorizedFetch("http://engine/api/v1/jobs");

    const [, init] = (fetch as any).mock.calls[0];
    expect((init.headers as Headers).has("Authorization")).toBe(false);
  });

  it("preserves the caller's own init fields alongside the auth header", async () => {
    setAuthToken("t");
    (fetch as any).mockResolvedValueOnce(new Response("{}", { status: 200 }));

    await authorizedFetch("http://engine/api/v1/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });

    const [, init] = (fetch as any).mock.calls[0];
    expect(init.method).toBe("POST");
    expect(init.body).toBe("{}");
    expect((init.headers as Headers).get("Content-Type")).toBe("application/json");
    expect((init.headers as Headers).get("Authorization")).toBe("Bearer t");
  });

  it("runs the session-expired handler on a 401", async () => {
    const onExpired = vi.fn();
    setSessionExpiredHandler(onExpired);
    setAuthToken("stale-token");
    (fetch as any).mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "invalid or expired session" }), { status: 401 }),
    );

    await authorizedFetch("http://engine/api/v1/jobs");

    expect(onExpired).toHaveBeenCalledTimes(1);
  });

  it("does not run the session-expired handler on a 403 — a real org mismatch, not a dead session", async () => {
    const onExpired = vi.fn();
    setSessionExpiredHandler(onExpired);
    setAuthToken("valid-token");
    (fetch as any).mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "access denied" }), { status: 403 }),
    );

    await authorizedFetch("http://engine/api/v1/jobs");

    expect(onExpired).not.toHaveBeenCalled();
  });

  it("does not run the session-expired handler on a 2xx", async () => {
    const onExpired = vi.fn();
    setSessionExpiredHandler(onExpired);
    setAuthToken("valid-token");
    (fetch as any).mockResolvedValueOnce(new Response("{}", { status: 200 }));

    await authorizedFetch("http://engine/api/v1/jobs");

    expect(onExpired).not.toHaveBeenCalled();
  });
});

/**
 * `downloadFile` — the fetch-then-blob replacement for `<a href={API_BASE}...}
 * download>`. Every download link in the app used to be that anchor, and a
 * browser navigation cannot carry the `Authorization` header ADR 0016 made
 * mandatory, so every one of those links 401'd (build-log — this cycle). This
 * is the one place that saves a fetched export, so its three behaviours —
 * naming the file from what the server sent, going through the shared
 * session-expired handler on `401`, and surfacing any other failure rather
 * than swallowing it the way a bare `<a>` turning into a browser error page
 * would — are asserted directly rather than once per call site.
 */
describe("downloadFile", () => {
  /** Capture a save without writing a real file. */
  function stubSave() {
    const filenames: string[] = [];
    const clicked = vi.fn(function (this: HTMLAnchorElement) {
      filenames.push(this.download);
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(clicked);
    URL.createObjectURL = vi.fn(() => "blob:mock-url");
    URL.revokeObjectURL = vi.fn();
    return { clicked, filenames };
  }

  it("saves the response body under the server's Content-Disposition filename", async () => {
    const { clicked, filenames } = stubSave();
    (fetch as any).mockResolvedValueOnce(
      new Response(new Blob(["a,b\n1,2"]), {
        status: 200,
        headers: { "Content-Disposition": 'attachment; filename="site-reconciliation.xlsx"' },
      }),
    );

    await downloadFile("http://engine/api/v1/jobs/1/reconciliation.xlsx", "fallback.xlsx");

    expect(clicked).toHaveBeenCalledTimes(1);
    expect(filenames[0]).toBe("site-reconciliation.xlsx");
  });

  it("falls back to the given filename when Content-Disposition is absent", async () => {
    const { clicked, filenames } = stubSave();
    (fetch as any).mockResolvedValueOnce(new Response(new Blob(["x"]), { status: 200 }));

    await downloadFile("http://engine/api/v1/jobs/1/matched.csv", "job-1-matched.csv");

    expect(clicked).toHaveBeenCalledTimes(1);
    expect(filenames[0]).toBe("job-1-matched.csv");
  });

  it("runs the shared session-expired handler on a 401, same as any other call", async () => {
    const onExpired = vi.fn();
    setSessionExpiredHandler(onExpired);
    (fetch as any).mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "invalid or expired session" }), { status: 401 }),
    );

    await expect(downloadFile("http://engine/api/v1/jobs/1/matched.csv", "f.csv")).rejects.toThrow(
      ApiError,
    );
    expect(onExpired).toHaveBeenCalledTimes(1);
  });

  it("throws a message-bearing error on a non-401 failure instead of swallowing it", async () => {
    // The failure a plain `<a href>` had no way to report: the browser just
    // navigated to a 404 page in the same tab. A caller here can show it.
    (fetch as any).mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "job not found" }), { status: 404 }),
    );

    await expect(
      downloadFile("http://engine/api/v1/jobs/missing/matched.csv", "f.csv"),
    ).rejects.toThrow("job not found");
  });
});

/**
 * `listAvailableMasterfiles` is the one adapter method that *decides*
 * something rather than passing a field through: whether a service is
 * offered. The server derives `measurable`; this must not invent it, and must
 * not withhold a service the server merely declined to describe.
 */
describe("HttpAdapter.listAvailableMasterfiles", () => {
  function respond(services: unknown): void {
    (fetch as any).mockResolvedValueOnce(
      new Response(JSON.stringify({ services }), { status: 200 }),
    );
  }

  it("carries the server's flag and reason through, and labels the slug", async () => {
    respond([
      { slug: "h1", measurable: true, reason: null },
      { slug: "custom_extraction", measurable: false, reason: "never requested" },
    ]);

    const services = await new HttpAdapter("http://engine/api/v1").listAvailableMasterfiles();

    expect(services).toEqual([
      { slug: "h1", label: "H1 Tags", description: "H1 tags and uniqueness", measurable: true, reason: null },
      {
        slug: "custom_extraction",
        label: "Custom Extraction",
        description: "Custom data extraction",
        measurable: false,
        reason: "never requested",
      },
    ]);
  });

  it("treats a server that never sends the flag as offering everything", async () => {
    // A server predating the field listed every service and meant it. Reading
    // its silence as "unavailable" would disable all twenty-one buttons.
    respond([{ slug: "h1" }]);

    const services = await new HttpAdapter("http://engine/api/v1").listAvailableMasterfiles();

    expect(services[0]?.measurable).toBe(true);
    expect(services[0]?.reason).toBeNull();
  });
});

describe("HttpAdapter.buildAllMasterfiles", () => {
  it("posts to the batch endpoint and returns the deliverable id", async () => {
    (fetch as any).mockResolvedValueOnce(
      new Response(JSON.stringify({ id: "dl-batch", status: "dispatched", label: "all" }), {
        status: 202,
      }),
    );

    const id = await new HttpAdapter("http://engine/api/v1").buildAllMasterfiles("wj-1");

    expect(id).toBe("dl-batch");
    expect(fetch).toHaveBeenCalledWith(
      "http://engine/api/v1/jobs/wj-1/masterfiles/all",
      expect.objectContaining({ method: "POST" }),
    );
  });
});

describe("HttpAdapter.listJobs provenance", () => {
  const record = {
    id: "job-1",
    tool_name: "page_classifier",
    label: "https://e.com/",
    status: "succeeded",
    created_at: "2026-10-01T09:00:00Z",
    updated_at: "2026-10-01T10:00:00Z",
    started_at: "2026-10-01T09:00:05Z",
    finished_at: "2026-10-01T10:00:00Z",
    error: null,
    has_result: true,
    has_checkpoint: false,
    telemetry: {},
  };

  function respond(records: unknown[]): void {
    (fetch as any).mockResolvedValueOnce(new Response(JSON.stringify(records), { status: 200 }));
  }

  it("maps an imported job's label and import time, and nothing else", async () => {
    respond([
      {
        ...record,
        provenance: {
          origin: "local_import",
          source_instance_id: "inst-9",
          source_label: "gaurav-workstation",
          source_job_id: "local-42",
          crawl_started_at: "2026-10-01T09:00:05Z",
          crawl_finished_at: "2026-10-01T10:00:00Z",
          imported_by: "operator-7",
          imported_at: "2026-10-02T08:30:00Z",
          bundle_sha256: "a".repeat(64),
        },
      },
    ]);

    const [job] = await new HttpAdapter("http://engine/api/v1").listJobs();

    expect(job?.importedFrom).toEqual({
      sourceLabel: "gaurav-workstation",
      importedAt: "2026-10-02T08:30:00Z",
    });
  });

  it("keeps a null source label rather than inventing one", async () => {
    respond([
      {
        ...record,
        provenance: {
          origin: "local_import",
          source_instance_id: "inst-9",
          source_label: null,
          source_job_id: "local-42",
          crawl_started_at: "2026-10-01T09:00:05Z",
          crawl_finished_at: "2026-10-01T10:00:00Z",
          imported_by: "operator-7",
          imported_at: "2026-10-02T08:30:00Z",
          bundle_sha256: "a".repeat(64),
        },
      },
    ]);

    const [job] = await new HttpAdapter("http://engine/api/v1").listJobs();

    expect(job?.importedFrom?.sourceLabel).toBeNull();
  });

  it("carries the server's telemetry through to the summary", async () => {
    const telemetry = {
      completed: 10,
      discovered: 40,
      rate_per_sec: 2,
      eta_seconds: 15,
      recent_items: ["https://e.com/x"],
      updated_at: "2026-10-01T09:05:00Z",
    };
    respond([{ ...record, status: "running", telemetry }]);

    const [job] = await new HttpAdapter("http://engine/api/v1").listJobs();

    expect(job?.telemetry).toEqual(telemetry);
  });

  it.each([
    ["null", { ...record, provenance: null }],
    // A server predating ADR 0034 omits the field entirely.
    ["absent", record],
  ])("reads a %s provenance as a job this server ran", async (_case, wire) => {
    respond([wire]);

    const [job] = await new HttpAdapter("http://engine/api/v1").listJobs();

    expect(job?.importedFrom).toBeNull();
  });
});
