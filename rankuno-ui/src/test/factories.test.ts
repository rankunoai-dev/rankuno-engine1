import { describe, expect, it } from "vitest";
import { page } from "./factories";

describe("page factory fetch-status fields", () => {
  it("defaults to a result stored before the capture: all three null", () => {
    const p = page("https://e.com/a/");
    expect(p.http_status).toBeNull();
    expect(p.first_redirect_status).toBeNull();
    expect(p.fetch_outcome).toBeNull();
  });

  it("accepts a captured status, redirect and outcome", () => {
    const p = page("https://e.com/old/", {
      http_status: 200,
      first_redirect_status: 301,
      fetch_outcome: "ok",
    });
    expect([p.http_status, p.first_redirect_status, p.fetch_outcome]).toEqual([200, 301, "ok"]);
  });
});
