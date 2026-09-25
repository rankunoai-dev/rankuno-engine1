/**
 * Integration tests for NewCrawlWizard.
 *
 * Tests the complete wizard flow from stage 1 through submission.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { NewCrawlWizard } from "./NewCrawlWizard";
import { useCrawlStore } from "../../store/useCrawlStore";

// Mock the store
vi.mock("../../store/useCrawlStore", () => ({
  useCrawlStore: vi.fn(),
}));

describe("NewCrawlWizard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (useCrawlStore as any).mockImplementation((selector: any) => {
      const mockStore = {
        startCrawl: vi.fn().mockResolvedValue(undefined),
        adapter: {
          listGscAccounts: vi.fn().mockResolvedValue([]),
        },
      };
      return selector(mockStore);
    });
  });

  it("renders stage 1 when opened", () => {
    render(<NewCrawlWizard open={true} onClose={() => {}} />);
    expect(screen.getByText("New Crawl")).toBeInTheDocument();
    expect(screen.getByText("How do you want to crawl?")).toBeInTheDocument();
  });

  it("does not render when closed", () => {
    const { container } = render(<NewCrawlWizard open={false} onClose={() => {}} />);
    expect(container.querySelector(".ant-modal")).not.toBeInTheDocument();
  });

  it("shows progress through stages", () => {
    render(<NewCrawlWizard open={true} onClose={() => {}} />);
    const steps = screen.getAllByRole("img");
    expect(steps.length).toBeGreaterThan(0);
  });

  it("navigates to next stage on Next button click", async () => {
    render(<NewCrawlWizard open={true} onClose={() => {}} />);

    // Select Full Site
    const fullSiteRadio = screen.getByRole("radio", { name: /Full Site Crawl/i });
    fireEvent.click(fullSiteRadio);

    // Click Next
    const nextButton = screen.getByRole("button", { name: "Next" });
    fireEvent.click(nextButton);

    // Should now show Domain stage
    await waitFor(() => {
      expect(screen.getByText(/Enter the domain to crawl/i)).toBeInTheDocument();
    });
  });

  it("validates required fields", async () => {
    render(<NewCrawlWizard open={true} onClose={() => {}} />);

    // Select URL List
    const urlListRadio = screen.getByRole("radio", { name: /URL List Upload/i });
    fireEvent.click(urlListRadio);

    // Try to go Next without uploading
    const nextButton = screen.getByRole("button", { name: "Next" });
    fireEvent.click(nextButton);

    // Should show error message
    await waitFor(() => {
      expect(screen.getByText(/Please upload a URL list file/i)).toBeInTheDocument();
    });
  });

  it("shows Back button on stage 2+", async () => {
    render(<NewCrawlWizard open={true} onClose={() => {}} />);

    // On stage 1, no Back button
    expect(screen.queryByRole("button", { name: "Back" })).not.toBeInTheDocument();

    // Select Full Site and go to next stage
    const fullSiteRadio = screen.getByRole("radio", { name: /Full Site Crawl/i });
    fireEvent.click(fullSiteRadio);

    const nextButton = screen.getByRole("button", { name: "Next" });
    fireEvent.click(nextButton);

    // On stage 2, Back button should appear
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Back" })).toBeInTheDocument();
    });
  });

  it("shows Submit button on final stage", async () => {
    render(<NewCrawlWizard open={true} onClose={() => {}} />);

    // Navigate through all stages
    const fullSiteRadio = screen.getByRole("radio", { name: /Full Site Crawl/i });
    fireEvent.click(fullSiteRadio);

    for (let i = 0; i < 3; i += 1) {
      const nextButton = screen.getAllByRole("button", { name: "Next" })[0];
      if (nextButton) fireEvent.click(nextButton);
    }

    // Should eventually show "Start Crawl" button on stage 4
    await waitFor(() => {
      const buttons = screen.getAllByRole("button");
      const startCrawlButton = buttons.find((b) => b.textContent?.includes("Start Crawl"));
      expect(startCrawlButton).toBeInTheDocument();
    });
  });

  it("closes modal when Cancel clicked", () => {
    const onClose = vi.fn();
    render(<NewCrawlWizard open={true} onClose={onClose} />);

    const cancelButton = screen.getByRole("button", { name: "Cancel" });
    fireEvent.click(cancelButton);

    expect(onClose).toHaveBeenCalled();
  });

  it("resets form on close", async () => {
    const onClose = vi.fn();
    const { rerender } = render(<NewCrawlWizard open={true} onClose={onClose} />);

    // Fill some data and move to next stage
    const fullSiteRadio = screen.getByRole("radio", { name: /Full Site Crawl/i });
    fireEvent.click(fullSiteRadio);

    const nextButton = screen.getByRole("button", { name: "Next" });
    fireEvent.click(nextButton);

    // Close and reopen
    rerender(<NewCrawlWizard open={false} onClose={onClose} />);
    rerender(<NewCrawlWizard open={true} onClose={onClose} />);

    // Should be back on stage 1
    await waitFor(() => {
      expect(screen.getByText("How do you want to crawl?")).toBeInTheDocument();
    });
  });
});
