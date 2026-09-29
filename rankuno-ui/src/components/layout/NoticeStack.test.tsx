import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import type { DashboardNotice } from "../../lib/dashboardNotices";
import { useNoticeStore } from "../../store/useNoticeStore";
import { NoticeStack } from "./NoticeStack";

/**
 * Putting a safety banner away, and getting it back.
 *
 * The banners exist because truncation, synthetic data, a zero-fetch crawl and
 * a blocked crawl are each a way to read the dashboard confidently and wrongly.
 * A close button is therefore only safe if it *hides* a finding rather than
 * deleting it, so every test here checks the way back as well as the way out.
 */

const TRUNCATED: DashboardNotice = {
  id: "truncated",
  type: "warning",
  label: "partial crawl",
  message: "Crawl stopped at its page ceiling. This is a partial view of the site, not the whole of it.",
};

const GSC: DashboardNotice = {
  id: "gsc",
  type: "info",
  label: "Search Console enrichment",
  message: "No Search Console metrics: this crawl was started without a GSC property URL.",
};

const BOTH = [TRUNCATED, GSC];

/** The close button belonging to one banner, by its own accessible name. */
function closeFor(notice: DashboardNotice): HTMLElement {
  return screen.getByRole("button", { name: `Dismiss the ${notice.label} notice` });
}

/** The restore control, if the stack is showing one. */
function restoreControl(): HTMLElement | null {
  return screen.queryByRole("button", { name: /hidden notice/i });
}

describe("NoticeStack", () => {
  beforeEach(() => {
    window.localStorage.clear();
    useNoticeStore.setState({ dismissed: {} });
  });

  it("shows every banner that applies, with nothing hidden to announce", () => {
    render(<NoticeStack notices={BOTH} crawlId="job-a" />);

    expect(screen.getByText(TRUNCATED.message)).toBeInTheDocument();
    expect(screen.getByText(GSC.message)).toBeInTheDocument();
    expect(restoreControl()).toBeNull();
  });

  it("renders nothing at all when no banner applies", () => {
    const { container } = render(<NoticeStack notices={[]} crawlId="job-a" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("hides the banner that was closed and keeps the others", () => {
    const { rerender } = render(<NoticeStack notices={BOTH} crawlId="job-a" />);

    fireEvent.click(closeFor(TRUNCATED));
    rerender(<NoticeStack notices={BOTH} crawlId="job-a" />);

    expect(screen.queryByText(TRUNCATED.message)).not.toBeInTheDocument();
    expect(screen.getByText(GSC.message)).toBeInTheDocument();
  });

  it("leaves a count of what is hidden where the banner was", () => {
    const { rerender } = render(<NoticeStack notices={BOTH} crawlId="job-a" />);

    fireEvent.click(closeFor(TRUNCATED));
    rerender(<NoticeStack notices={BOTH} crawlId="job-a" />);
    // Singular, because one banner is a notice and not notices.
    expect(screen.getByText("1 hidden notice — show again")).toBeInTheDocument();

    fireEvent.click(closeFor(GSC));
    rerender(<NoticeStack notices={BOTH} crawlId="job-a" />);
    expect(screen.getByText("2 hidden notices — show again")).toBeInTheDocument();
  });

  it("brings every hidden banner back from that control", () => {
    const { rerender } = render(<NoticeStack notices={BOTH} crawlId="job-a" />);

    fireEvent.click(closeFor(TRUNCATED));
    rerender(<NoticeStack notices={BOTH} crawlId="job-a" />);
    fireEvent.click(closeFor(GSC));
    rerender(<NoticeStack notices={BOTH} crawlId="job-a" />);

    const restore = restoreControl();
    expect(restore).not.toBeNull();
    fireEvent.click(restore as HTMLElement);
    rerender(<NoticeStack notices={BOTH} crawlId="job-a" />);

    expect(screen.getByText(TRUNCATED.message)).toBeInTheDocument();
    expect(screen.getByText(GSC.message)).toBeInTheDocument();
    expect(restoreControl()).toBeNull();
  });

  it("shows the banner again on a different crawl", () => {
    /* The finding this feature is most at risk of destroying. "This site has
       405 pages" and "I looked at 405 pages of this site" are different
       claims, and a dismissal carried across crawls would make the second one
       read as the first for a crawl nobody has looked at yet. */
    const { rerender } = render(<NoticeStack notices={BOTH} crawlId="job-a" />);
    fireEvent.click(closeFor(TRUNCATED));
    rerender(<NoticeStack notices={BOTH} crawlId="job-a" />);
    expect(screen.queryByText(TRUNCATED.message)).not.toBeInTheDocument();

    rerender(<NoticeStack notices={BOTH} crawlId="job-b" />);

    expect(screen.getByText(TRUNCATED.message)).toBeInTheDocument();
    expect(restoreControl()).toBeNull();
    // And going back to the first crawl still respects what was done there.
    rerender(<NoticeStack notices={BOTH} crawlId="job-a" />);
    expect(screen.queryByText(TRUNCATED.message)).not.toBeInTheDocument();
  });

  it("writes the dismissal down, and honours it on a fresh mount", () => {
    /* Half a reload each side of the unmount. `useNoticeStore.test.ts` pins
       the parse back out of the key; what has to be true here is that the
       write happens at all, and that a stack mounting with a restored
       dismissal already in the store starts hidden — no click involved. */
    const { rerender, unmount } = render(<NoticeStack notices={BOTH} crawlId="job-a" />);
    fireEvent.click(closeFor(TRUNCATED));
    rerender(<NoticeStack notices={BOTH} crawlId="job-a" />);

    expect(JSON.parse(window.localStorage.getItem("rankuno.notices") as string)).toEqual({
      crawls: [{ id: "job-a", ids: ["truncated"] }],
    });

    unmount();
    render(<NoticeStack notices={BOTH} crawlId="job-a" />);

    expect(screen.queryByText(TRUNCATED.message)).not.toBeInTheDocument();
    expect(screen.getByText("1 hidden notice — show again")).toBeInTheDocument();
  });

  it("does not count a dismissal for a banner that no longer applies", () => {
    /* A crawl re-run without truncation, on the same job id. The stale
       dismissal must not leave "1 hidden notice" offering to restore nothing. */
    useNoticeStore.setState({ dismissed: { "job-a": ["truncated"] } });

    render(<NoticeStack notices={[GSC]} crawlId="job-a" />);

    expect(screen.getByText(GSC.message)).toBeInTheDocument();
    expect(restoreControl()).toBeNull();
  });

  it("offers no close button when there is no crawl to record it against", () => {
    /* A dismissal has to be scoped to something. Recording one against "no
       crawl" is the global dismissal this design refuses, so the banner simply
       stays. */
    render(<NoticeStack notices={[TRUNCATED]} crawlId={null} />);

    expect(screen.getByText(TRUNCATED.message)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Dismiss/i })).toBeNull();
  });

  it("names each close button after the finding it hides", () => {
    // Seven buttons all called "Close" is a screen reader announcing the same
    // thing seven times with no way to tell which one is about to hide the
    // partial-crawl warning.
    render(<NoticeStack notices={BOTH} crawlId="job-a" />);

    expect(closeFor(TRUNCATED)).toBeInTheDocument();
    expect(closeFor(GSC)).toBeInTheDocument();
  });

  it("keeps every control reachable from the keyboard", () => {
    const { rerender } = render(<NoticeStack notices={BOTH} crawlId="job-a" />);

    const close = closeFor(TRUNCATED);
    close.focus();
    expect(close).toHaveFocus();
    expect(close.tagName).toBe("BUTTON");

    fireEvent.click(close);
    rerender(<NoticeStack notices={BOTH} crawlId="job-a" />);

    const restore = restoreControl() as HTMLElement;
    restore.focus();
    expect(restore).toHaveFocus();
    expect(restore.tagName).toBe("BUTTON");
  });
});
