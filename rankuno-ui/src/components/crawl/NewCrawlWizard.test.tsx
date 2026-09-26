/**
 * Integration tests for NewCrawlWizard.
 *
 * Covers the wizard as an operator drives it: choosing a source, being refused
 * when a required field is missing, walking to the final stage, and what the
 * wizard looks like the *second* time it is opened.
 *
 * ## Why the store mock is one frozen object
 *
 * This file used to build its `mockStore` inside the selector callback, so
 * every call - every render - produced a new `adapter` object. `NewCrawlWizard`
 * lists `adapter` in the dependency array of its GSC-account effect and stores
 * the result with `setGscAccounts`, so a fresh identity per render is a closed
 * loop: render, effect, resolve, setState, render. It never settled;
 * `listGscAccounts` was measured at 32, 70, 109, 148, 187 and 234 calls across
 * successive drains of the event loop. The three synchronous tests survived it
 * because they returned before the loop had ticked twice. The two that awaited
 * a `waitFor` handed it the event loop, and the worker grew past 3 GB and was
 * killed - taking the whole `verify.ps1` run with it, because Vitest does not
 * exit after `Worker exited unexpectedly`, it hangs.
 *
 * The real store cannot do this: `adapter` is a field zustand hands back by
 * reference. So the single module-scope `STORE` below is not a convenience, it
 * is the part of the mock that makes it a faithful stand-in. Do not move the
 * object literal inside the selector.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { message } from "antd";
import { useState } from "react";
import { NewCrawlWizard } from "./NewCrawlWizard";
import { useCrawlStore } from "../../store/useCrawlStore";

vi.mock("../../store/useCrawlStore", () => ({
  useCrawlStore: vi.fn(),
}));

const startCrawl = vi.fn<(payload: unknown) => Promise<void>>();
const listGscAccounts = vi.fn<() => Promise<string[]>>();

/**
 * One store object for the whole file, with stable field identities.
 * See the module docstring before changing this.
 */
const STORE = {
  startCrawl,
  adapter: { listGscAccounts },
};

/**
 * Host that mirrors `DashboardShell`: the wizard stays mounted for the session
 * and only `open` is toggled. Closing therefore never unmounts it, which is
 * what makes "is it clean when reopened?" a question about the component rather
 * than about React.
 */
function WizardHost(): JSX.Element {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open Wizard
      </button>
      <NewCrawlWizard open={open} onClose={() => setOpen(false)} />
    </>
  );
}

/** Click the wizard's primary advance button. */
function clickNext(): void {
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
}

/** Type a domain on the Domain stage. */
function typeDomain(value: string): void {
  fireEvent.change(screen.getByPlaceholderText("www.example.com"), {
    target: { value },
  });
}

describe("NewCrawlWizard", () => {
  beforeEach(() => {
    startCrawl.mockReset().mockResolvedValue(undefined);
    listGscAccounts.mockReset().mockResolvedValue([]);
    vi.mocked(useCrawlStore).mockImplementation(
      (selector: (state: never) => unknown) => selector(STORE as never),
    );
  });

  afterEach(() => {
    // antd's `message` is a singleton portalled onto document.body, outside the
    // container RTL's `cleanup` clears. Left alone, a toast from one test is
    // still in the DOM for the next one and an unambiguous `getByText` starts
    // reporting multiple matches.
    message.destroy();
  });

  it("renders stage 1 when opened", () => {
    render(<NewCrawlWizard open onClose={() => {}} />);
    expect(screen.getByText("New Crawl")).toBeInTheDocument();
    expect(screen.getByText("How do you want to crawl?")).toBeInTheDocument();
  });

  it("renders nothing at all when closed", () => {
    render(<NewCrawlWizard open={false} onClose={() => {}} />);
    // Queried against document.body, not the render container: antd portals the
    // Modal onto the body, so a container-scoped query finds no `.ant-modal`
    // whether the wizard is open or shut and can never fail.
    expect(document.body.querySelector(".ant-modal")).toBeNull();
    expect(screen.queryByText("How do you want to crawl?")).not.toBeInTheDocument();
  });

  it("marks the current stage in the step indicator and advances it", async () => {
    render(<NewCrawlWizard open onClose={() => {}} />);

    // The indicator is what tells the operator where they are, so assert the
    // active step by name rather than counting rendered icons.
    //
    // Scoped to the step bar: the Domain stage renders a Form.Item labelled
    // "Domain" too, so an unscoped `getByText("Domain")` starts matching two
    // nodes the moment the wizard advances.
    const stepFor = (label: string): Element | null => {
      const steps = document.body.querySelector(".ant-steps");
      if (!steps) throw new Error("step indicator not rendered");
      return within(steps as HTMLElement)
        .getByText(label)
        .closest(".ant-steps-item");
    };

    expect(stepFor("Source")).toHaveClass("ant-steps-item-process");
    expect(stepFor("Domain")).toHaveClass("ant-steps-item-wait");

    clickNext();

    await waitFor(() => {
      expect(stepFor("Domain")).toHaveClass("ant-steps-item-process");
    });
    expect(stepFor("Source")).toHaveClass("ant-steps-item-finish");
  });

  it("navigates to next stage on Next button click", async () => {
    render(<NewCrawlWizard open onClose={() => {}} />);

    fireEvent.click(screen.getByRole("radio", { name: /Full Site Crawl/i }));
    clickNext();

    await waitFor(() => {
      expect(screen.getByText(/Enter the domain to crawl/i)).toBeInTheDocument();
    });
  });

  it("refuses to leave the source stage when URL List is chosen with no file", async () => {
    render(<NewCrawlWizard open onClose={() => {}} />);

    fireEvent.click(screen.getByRole("radio", { name: /URL List Upload/i }));
    clickNext();

    await waitFor(() => {
      expect(screen.getByText(/Please upload a URL list file/i)).toBeInTheDocument();
    });
    // The point of the error is that it blocks: still on the Source stage.
    expect(screen.getByText("How do you want to crawl?")).toBeInTheDocument();
  });

  it("refuses to leave the domain stage without a domain", async () => {
    render(<NewCrawlWizard open onClose={() => {}} />);

    clickNext();
    await waitFor(() => {
      expect(screen.getByText(/Enter the domain to crawl/i)).toBeInTheDocument();
    });

    clickNext();

    await waitFor(() => {
      expect(screen.getByText("Domain is required")).toBeInTheDocument();
    });
    expect(screen.getByText(/Enter the domain to crawl/i)).toBeInTheDocument();
    expect(screen.queryByText("Choose crawl speed")).not.toBeInTheDocument();
  });

  it("rejects a malformed domain rather than crawling it", async () => {
    render(<NewCrawlWizard open onClose={() => {}} />);

    clickNext();
    await waitFor(() => {
      expect(screen.getByText(/Enter the domain to crawl/i)).toBeInTheDocument();
    });

    // `example..com` has an empty label. It used to pass validation and would
    // have been sent to the crawler as `https://example..com`.
    typeDomain("example..com");
    clickNext();

    await waitFor(() => {
      expect(screen.getAllByText(/Invalid domain format/i).length).toBeGreaterThan(0);
    });
    expect(screen.getByText(/Enter the domain to crawl/i)).toBeInTheDocument();
  });

  it("shows Back button on stage 2+", async () => {
    render(<NewCrawlWizard open onClose={() => {}} />);

    expect(screen.queryByRole("button", { name: "Back" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("radio", { name: /Full Site Crawl/i }));
    clickNext();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Back" })).toBeInTheDocument();
    });

    // Back must actually go back, not merely appear.
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    await waitFor(() => {
      expect(screen.getByText("How do you want to crawl?")).toBeInTheDocument();
    });
  });

  it("reaches the final stage and swaps Next for Start Crawl", async () => {
    render(<NewCrawlWizard open onClose={() => {}} />);

    clickNext();
    await waitFor(() => {
      expect(screen.getByText(/Enter the domain to crawl/i)).toBeInTheDocument();
    });

    // A domain is mandatory to get past stage 2; a walkthrough that omits it is
    // testing the validation, not the navigation.
    typeDomain("www.example.com");
    clickNext();
    await waitFor(() => {
      expect(screen.getByText("Choose crawl speed")).toBeInTheDocument();
    });

    clickNext();
    await waitFor(() => {
      expect(screen.getByText("Advanced options (optional)")).toBeInTheDocument();
    });

    expect(screen.getByRole("button", { name: /Start Crawl/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Next" })).not.toBeInTheDocument();
  });

  it("submits the typed domain as the crawl base_url", async () => {
    render(<WizardHost />);
    fireEvent.click(screen.getByRole("button", { name: "Open Wizard" }));

    clickNext();
    await waitFor(() => {
      expect(screen.getByText(/Enter the domain to crawl/i)).toBeInTheDocument();
    });
    typeDomain("shop.example.co.uk");
    clickNext();
    clickNext();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Start Crawl/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /Start Crawl/i }));

    await waitFor(() => {
      expect(startCrawl).toHaveBeenCalledTimes(1);
    });
    expect(startCrawl.mock.calls[0]?.[0]).toMatchObject({
      base_url: "https://shop.example.co.uk",
    });
  });

  it("closes modal when Cancel clicked", () => {
    const onClose = vi.fn();
    render(<NewCrawlWizard open onClose={onClose} />);

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onClose).toHaveBeenCalled();
  });

  it("reopens on stage 1 with an empty domain after Cancel", async () => {
    render(<WizardHost />);
    fireEvent.click(screen.getByRole("button", { name: "Open Wizard" }));

    clickNext();
    await waitFor(() => {
      expect(screen.getByText(/Enter the domain to crawl/i)).toBeInTheDocument();
    });
    typeDomain("stale-domain.example");

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.click(screen.getByRole("button", { name: "Open Wizard" }));

    // Regression: Cancel called `onClose` without `reset()`, and because
    // `DashboardShell` never unmounts this component the operator reopened onto
    // the Domain stage with `stale-domain.example` still in the field.
    await waitFor(() => {
      expect(screen.getByText("How do you want to crawl?")).toBeInTheDocument();
    });
    expect(screen.queryByDisplayValue("stale-domain.example")).not.toBeInTheDocument();
  });

  it("can start a second crawl after a successful one", async () => {
    render(<WizardHost />);
    fireEvent.click(screen.getByRole("button", { name: "Open Wizard" }));

    clickNext();
    await waitFor(() => {
      expect(screen.getByText(/Enter the domain to crawl/i)).toBeInTheDocument();
    });
    typeDomain("www.example.com");
    clickNext();
    clickNext();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Start Crawl/i })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: /Start Crawl/i }));
    await waitFor(() => {
      expect(startCrawl).toHaveBeenCalledTimes(1);
    });

    fireEvent.click(screen.getByRole("button", { name: "Open Wizard" }));
    await waitFor(() => {
      expect(screen.getByText("How do you want to crawl?")).toBeInTheDocument();
    });

    // Regression: `submitting` was cleared only on the failure path, so after
    // one successful crawl the primary button spun forever and Cancel stayed
    // disabled for the life of the page - one crawl per reload.
    expect(screen.getByRole("button", { name: "Cancel" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Next" })).not.toHaveClass(
      "ant-btn-loading",
    );
  });

  it("keeps what was typed when the crawl fails to start", async () => {
    startCrawl.mockRejectedValue(new Error("queue is full"));
    render(<WizardHost />);
    fireEvent.click(screen.getByRole("button", { name: "Open Wizard" }));

    clickNext();
    await waitFor(() => {
      expect(screen.getByText(/Enter the domain to crawl/i)).toBeInTheDocument();
    });
    typeDomain("retry.example.com");
    clickNext();
    clickNext();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Start Crawl/i })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: /Start Crawl/i }));

    await waitFor(() => {
      expect(screen.getByText("queue is full")).toBeInTheDocument();
    });

    // Nothing was crawled, so the form is worth keeping: reopening lands back
    // on the final stage and Start Crawl is live again for a retry.
    fireEvent.click(screen.getByRole("button", { name: "Open Wizard" }));
    await waitFor(() => {
      expect(screen.getByText("Advanced options (optional)")).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: /Start Crawl/i })).toBeEnabled();
  });

  it("fetches the GSC account list once per open", async () => {
    listGscAccounts.mockResolvedValue(["acme", "globex"]);
    render(<NewCrawlWizard open onClose={() => {}} />);

    await waitFor(() => {
      expect(listGscAccounts).toHaveBeenCalledTimes(1);
    });

    // Hold the count across a drain of the event loop. One call is the
    // behaviour; "one call and then it stops" is what the 3 GB worker did not
    // do, and this is the assertion that would have caught it.
    for (let i = 0; i < 25; i += 1) {
      await new Promise((resolve) => setTimeout(resolve, 0));
    }
    expect(listGscAccounts).toHaveBeenCalledTimes(1);
  });
});
