import { describe, expect, it } from "vitest";
import { dashboardNotices } from "./dashboardNotices";
import { NOTICE_IDS } from "../store/useNoticeStore";
import { crawl, discovery, page } from "../test/factories";

/**
 * Which safety banners the dashboard says about a crawl.
 *
 * This list was conditional JSX inside `DashboardShell` until the banners
 * became dismissible; it had to become a value because "2 hidden notices"
 * needs to know how many banners *apply*, not how many are rendered. Pinned
 * here rather than only through the component, because the risk that matters
 * is a banner quietly ceasing to fire, and a test that renders the shell would
 * report that as "element not found" whatever the cause.
 */

/** A crawl with a parsed header menu, so the nav fallback banner stays quiet. */
function withNav(overrides: Parameters<typeof crawl>[0] = {}) {
  return crawl({
    navigation: {
      roots: [{ url: "https://e.com/a/", label: "A", depth: 0, children: [] }],
      source: { strategy: "header", containers: 1, link_count: 1 },
    },
    ...overrides,
  });
}

describe("dashboardNotices", () => {
  it("says nothing about an unremarkable crawl", () => {
    expect(dashboardNotices(withNav(), false)).toEqual([]);
  });

  it("says nothing at all when no crawl is loaded and the job is ordinary", () => {
    expect(dashboardNotices(null, false)).toEqual([]);
  });

  it("names a synthetic dataset even before a result is loaded", () => {
    // The one banner that describes where the data came from rather than what
    // is in it, so it comes off the job row and fires without a result.
    const notices = dashboardNotices(null, true);
    expect(notices.map((n) => n.id)).toEqual(["synthetic"]);
    expect(notices[0]?.message).toMatch(/Synthetic dataset/);
  });

  it("reports the partial crawl that a page ceiling produced", () => {
    const notices = dashboardNotices(
      withNav({ discovery: discovery({ truncated: true }) }),
      false,
    );
    expect(notices.map((n) => n.id)).toEqual(["truncated"]);
    expect(notices[0]?.message).toBe(
      "Crawl stopped at its page ceiling. This is a partial view of the site, not the whole of it.",
    );
  });

  it("distinguishes a crawl abandoned early from one that hit its ceiling", () => {
    const notices = dashboardNotices(
      withNav({ discovery: discovery({ stopped_reason: "the operator cancelled it", total_urls: 1234 }) }),
      false,
    );
    expect(notices.map((n) => n.id)).toEqual(["stopped-early"]);
    expect(notices[0]?.message).toContain("1,234");
  });

  it("counts the refused requests when nothing was fetched", () => {
    const notices = dashboardNotices(
      withNav({ discovery: discovery({ pages_fetched: 0, fetch_failures: 12 }) }),
      false,
    );
    expect(notices.map((n) => n.id)).toEqual(["zero-fetch"]);
    expect(notices[0]?.type).toBe("error");
    expect(notices[0]?.message).toContain("12 requests were refused");
  });

  it("singularises the blocked-sitemap attempt count", () => {
    const one = dashboardNotices(
      withNav({ discovery: discovery({ sitemaps_blocked: true, sitemap_fetch_attempts: 1 }) }),
      false,
    );
    expect(one[0]?.message).toContain("(1 attempt)");

    const many = dashboardNotices(
      withNav({ discovery: discovery({ sitemaps_blocked: true, sitemap_fetch_attempts: 4 }) }),
      false,
    );
    expect(many[0]?.message).toContain("(4 attempts)");
  });

  it("announces the path-grouping fallback whenever no menu was parsed", () => {
    // Not gated on the grouping toggle: `selectJob` flips that to "path" the
    // moment it sees an unparsed menu, so the old condition was false exactly
    // when this needed saying.
    const notices = dashboardNotices(crawl({ pages: [page("https://e.com/a/")] }), false);
    expect(notices.map((n) => n.id)).toEqual(["nav-unparsed"]);
  });

  it("carries the Search Console outcome with its own tone", () => {
    const notices = dashboardNotices(
      withNav({
        gsc: {
          status: "failed",
          pages_matched: 0,
          pages_crawled: 3,
          unmatched_gsc_urls: 0,
          account: "ops@example.com",
          property_url: "https://e.com/",
          reason: "the credential was rejected",
        },
      }),
      false,
    );
    expect(notices.map((n) => n.id)).toEqual(["gsc"]);
    expect(notices[0]?.type).toBe("warning");
  });

  it("stacks every banner in the order the dashboard shows them", () => {
    const notices = dashboardNotices(
      crawl({
        discovery: discovery({
          pages_fetched: 0,
          sitemaps_blocked: true,
          sitemap_fetch_attempts: 2,
          stopped_reason: "it ran out of time",
          truncated: true,
        }),
        gsc: {
          status: "not_requested",
          pages_matched: 0,
          pages_crawled: 0,
          unmatched_gsc_urls: 0,
          account: null,
          property_url: null,
          reason: "",
        },
      }),
      true,
    );

    expect(notices.map((n) => n.id)).toEqual([
      "synthetic",
      "zero-fetch",
      "sitemaps-blocked",
      "stopped-early",
      "gsc",
      "truncated",
      "nav-unparsed",
    ]);
  });

  it("gives every banner an id the store can persist, and a close label of its own", () => {
    /* A banner with an id outside `NOTICE_IDS` could be dismissed and never
       restored, because nothing out of storage would validate. A banner
       sharing a label would give two close buttons the same accessible name,
       which is a screen reader hiding the wrong finding. */
    const notices = dashboardNotices(
      crawl({
        discovery: discovery({
          pages_fetched: 0,
          sitemaps_blocked: true,
          stopped_reason: "it ran out of time",
          truncated: true,
        }),
        gsc: {
          status: "not_requested",
          pages_matched: 0,
          pages_crawled: 0,
          unmatched_gsc_urls: 0,
          account: null,
          property_url: null,
          reason: "",
        },
      }),
      true,
    );

    expect(notices.map((n) => n.id).sort()).toEqual([...NOTICE_IDS].sort());
    expect(new Set(notices.map((n) => n.label)).size).toBe(notices.length);
    for (const notice of notices) expect(notice.label).not.toBe("");
  });
});
