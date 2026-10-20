import { describe, it, expect } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { CREDENTIAL_GUIDE, CredentialSetupGuide, GUIDE_HEADER } from "./CredentialSetupGuide";

const APPROVED_HOSTS = ["console.cloud.google.com", "developers.google.com", "support.google.com"];

function openGuide(): void {
  fireEvent.click(screen.getByText(GUIDE_HEADER));
}

describe("CredentialSetupGuide", () => {
  it("is collapsed by default and opens to the Search Console and GA4 sections", () => {
    render(<CredentialSetupGuide />);
    expect(screen.getByText(GUIDE_HEADER)).toBeInTheDocument();
    expect(screen.queryByText("Search Console (GSC) credential")).not.toBeInTheDocument();

    openGuide();
    expect(screen.getByRole("heading", { name: "Search Console (GSC) credential" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "GA4 credential" })).toBeInTheDocument();
  });

  it("reads Search Console first, then GA4", () => {
    render(<CredentialSetupGuide />);
    openGuide();

    const gsc = screen.getByRole("heading", { name: "Search Console (GSC) credential" });
    const ga4 = screen.getByRole("heading", { name: "GA4 credential" });
    expect(gsc.compareDocumentPosition(ga4) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(CREDENTIAL_GUIDE.map((s) => s.key)).toEqual(["gsc", "ga4"]);
  });

  it("states the real credential type: an OAuth refresh token with read-only scopes", () => {
    render(<CredentialSetupGuide />);
    openGuide();

    const gscSection = screen.getByRole("region", { name: "Search Console (GSC) credential" });
    const ga4Section = screen.getByRole("region", { name: "GA4 credential" });
    expect(within(gscSection).getByText(/OAuth refresh token/i, { exact: false })).toBeInTheDocument();
    expect(within(gscSection).getByText(/webmasters\.readonly/)).toBeInTheDocument();
    expect(within(ga4Section).getByText(/OAuth refresh token/i, { exact: false })).toBeInTheDocument();
    expect(within(ga4Section).getByText(/analytics\.readonly/)).toBeInTheDocument();
    expect(screen.queryByText(/service.account/i)).not.toBeInTheDocument();
  });

  it("marks every Google Cloud console label it cannot confirm from the repository", () => {
    render(<CredentialSetupGuide />);
    openGuide();
    // Each Google-side instruction that names a console item carries the
    // marker; the Rankuno-side steps name only labels the UI shows.
    const marked = screen.getAllByText(/verify against current Google Cloud console/i);
    expect(marked.length).toBeGreaterThanOrEqual(5);
  });

  it("links only to the approved Google domains, over https", () => {
    render(<CredentialSetupGuide />);
    openGuide();

    const links = screen.getAllByRole("link");
    expect(links.length).toBeGreaterThan(0);
    for (const link of links) {
      const url = new URL(link.getAttribute("href") ?? "");
      expect(url.protocol).toBe("https:");
      expect(APPROVED_HOSTS).toContain(url.hostname);
      expect(link).toHaveAttribute("target", "_blank");
    }
  });
});
