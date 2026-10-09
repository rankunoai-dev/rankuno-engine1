import { describe, expect, it } from "vitest";
import type { GscEnrichmentReport } from "../types/schema";
import {
  gscEnrichmentWarning,
  gscPropertyError,
  gscWarningFor,
  gscWarningTone,
} from "./gscEnrichment";

/**
 * One message per enrichment outcome.
 *
 * All four outcomes leave every page with `gsc_* = null`, because enrichment
 * must never fail a crawl. These assertions are on what distinguishes them for
 * the person reading the dashboard.
 */

function report(overrides: Partial<GscEnrichmentReport> = {}): GscEnrichmentReport {
  return {
    status: "succeeded",
    pages_matched: 0,
    pages_crawled: 0,
    unmatched_gsc_urls: 0,
    account: null,
    property_url: null,
    reason: "",
    ...overrides,
  };
}

describe("gscEnrichmentWarning", () => {
  it("names the missing property URL when enrichment was never requested", () => {
    // The actual cause, and the one an operator can act on: they picked an
    // account and left the property URL blank.
    const message = gscEnrichmentWarning(report({ status: "not_requested", account: "acme" }));
    expect(message).toMatch(/property URL/i);
    expect(message).toMatch(/Re-run/i);
  });

  it("says nothing when metrics arrived", () => {
    expect(
      gscEnrichmentWarning(report({ status: "succeeded", pages_matched: 40, pages_crawled: 50 })),
    ).toBe("");
  });

  it("separates a property that answered with nothing matching from a failure", () => {
    const message = gscEnrichmentWarning(
      report({ status: "succeeded", pages_matched: 0, pages_crawled: 1200 }),
    );
    expect(message).toMatch(/none of its URLs matched/i);
    expect(message).toMatch(/1,200/);
  });

  it("does not claim the credentials and property are fine when nothing matched", () => {
    /* A 0-match answer does not prove access: the account may not see the
       property's data. The message used to say the opposite. */
    const message = gscEnrichmentWarning(
      report({ status: "succeeded", pages_matched: 0, pages_crawled: 10 }),
    );
    expect(message).not.toMatch(/credentials and the property are fine/i);
    expect(message).toMatch(/account cannot see this property/i);
  });

  it("repeats the engine's explanation for a 403", () => {
    const message = gscEnrichmentWarning(
      report({
        status: "failed",
        reason: "GscAuthorizationError: this Google account cannot access this property",
        account: "acme",
      }),
    );
    expect(message).toMatch(/GscAuthorizationError/);
    expect(message).toMatch(/this Google account cannot access this property/);
    expect(message).toMatch(/"acme"/);
  });

  it("repeats the engine's explanation for a 404", () => {
    const message = gscEnrichmentWarning(
      report({
        status: "failed",
        reason: "GscPropertyNotFoundError: property not found in Search Console",
      }),
    );
    expect(message).toMatch(/GscPropertyNotFoundError/);
    expect(message).toMatch(/property not found/);
  });

  it("repeats the validator's explanation for a property mismatch", () => {
    const message = gscEnrichmentWarning(
      report({
        status: "property_mismatch",
        reason: "No match: property other.com does not cover crawl example.com",
      }),
    );
    expect(message).toMatch(/does not cover/i);
    expect(message).toMatch(/other\.com/);
  });

  it("reports a failure by class name and names the account to check", () => {
    const message = gscEnrichmentWarning(
      report({ status: "failed", reason: "TimeoutError", account: "acme" }),
    );
    expect(message).toMatch(/TimeoutError/);
    expect(message).toMatch(/"acme"/);
    // The crawl is not the casualty, and saying so stops a support ticket.
    expect(message).toMatch(/crawl itself is unaffected/i);
  });

  it("reserves the warning colour for the outcomes where something failed", () => {
    // A blank property URL is an input left empty, not a fault, and colouring
    // it like one trains the operator to ignore the banner.
    expect(gscWarningTone(report({ status: "not_requested" }))).toBe("info");
    expect(gscWarningTone(report({ status: "failed" }))).toBe("warning");
    expect(gscWarningTone(report({ status: "property_mismatch" }))).toBe("warning");
    expect(gscWarningTone(null)).toBe("info");
  });

  it("says nothing for a result stored before the outcome was recorded", () => {
    /* The backwards-compatibility case. `gsc` is typed as always present, and
       the type describes what the engine emits today — a result written months
       ago has no such key, and inventing an outcome for it would be a claim the
       data does not support. */
    expect(gscEnrichmentWarning(null)).toBe("");
    expect(gscEnrichmentWarning(undefined)).toBe("");
    expect(gscWarningFor(undefined)).toBe("");
    expect(gscWarningFor({} as never)).toBe("");
  });
});

describe("gscPropertyError", () => {
  it.each([
    "",
    "   ",
    "https://example.com/",
    "http://www.example.com/blog/",
    "https://example.com",
    "sc-domain:example.com",
    "sc-domain:rankuno.co.uk",
    "SC-DOMAIN:Example.com",
  ])("accepts %j", (value) => {
    expect(gscPropertyError(value)).toBeNull();
  });

  it.each([
    "example.com",
    "www.example.com/",
    "ftp://example.com/",
    "sc-domain:",
    "sc-domain:https://example.com",
    "sc-domain:example.com/",
    "sc-domain:localhost",
    "https://",
  ])("rejects %j", (value) => {
    expect(gscPropertyError(value)).toMatch(/sc-domain:/);
  });
});
