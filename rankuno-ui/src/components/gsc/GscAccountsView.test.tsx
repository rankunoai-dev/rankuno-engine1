import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { GscAccountsView } from "./GscAccountsView";

// Mock the API. Responses are routed by URL: the GSC calls draw from a queue
// in call order, while the org GA4 read (`/ga4`) has its own handler, so the
// two reads cannot steal each other's canned responses.
vi.stubGlobal("fetch", vi.fn());

const gscQueue: Response[] = [];
const queueGsc = (response: Response): void => {
  gscQueue.push(response);
};
let ga4Handler: () => Promise<Response>;

describe("GscAccountsView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    gscQueue.length = 0;
    ga4Handler = async () => new Response(JSON.stringify({ status: "mapped", property_id: "123" }), { status: 200 });
    (fetch as any).mockImplementation(async (url: string) => {
      if (url.includes("/ga4")) return ga4Handler();
      return gscQueue.shift() ?? new Response("", { status: 500 });
    });
  });

  it("renders the header and add button", async () => {
    queueGsc(
      new Response(JSON.stringify({ accounts: [] }), { status: 200 }),
    );

    render(<GscAccountsView orgId="test-org" />);

    expect(screen.getByText("GSC Accounts")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /add account/i })).toBeInTheDocument();
  });

  it("fetches and displays accounts", async () => {
    const mockAccounts = [
      { account_name: "account-1", client_id: "123", has_secret_override: false },
      { account_name: "account-2", client_id: null, has_secret_override: true },
    ];

    queueGsc(
      new Response(JSON.stringify({ accounts: mockAccounts }), { status: 200 }),
    );

    render(<GscAccountsView orgId="test-org" />);

    await waitFor(() => {
      expect(screen.getByText("account-1")).toBeInTheDocument();
      expect(screen.getByText("account-2")).toBeInTheDocument();
    });
  });

  it("displays account details correctly", async () => {
    const mockAccounts = [
      { account_name: "my-account", client_id: "client-123", has_secret_override: true },
    ];

    queueGsc(
      new Response(JSON.stringify({ accounts: mockAccounts }), { status: 200 }),
    );

    render(<GscAccountsView orgId="test-org" />);

    await waitFor(() => {
      expect(screen.getByText("my-account")).toBeInTheDocument();
      expect(screen.getByText("client-123")).toBeInTheDocument();
      expect(screen.getByText(/custom secret configured/i)).toBeInTheDocument();
    });
  });

  it("shows empty state when no accounts", async () => {
    queueGsc(
      new Response(JSON.stringify({ accounts: [] }), { status: 200 }),
    );

    render(<GscAccountsView orgId="test-org" />);

    await waitFor(() => {
      expect(screen.getByText(/no accounts configured/i)).toBeInTheDocument();
    });
  });

  it("handles delete confirmation and calls API", async () => {
    const mockAccounts = [
      { account_name: "to-delete", client_id: "123", has_secret_override: false },
    ];

    // First call: fetch accounts
    queueGsc(
      new Response(JSON.stringify({ accounts: mockAccounts }), { status: 200 }),
    );

    // Second call: delete account
    queueGsc(
      new Response("", { status: 200 }),
    );

    render(<GscAccountsView orgId="test-org" />);

    await waitFor(() => {
      expect(screen.getByText("to-delete")).toBeInTheDocument();
    });

    const deleteButton = screen.getByRole("button", { name: /delete/i });
    fireEvent.click(deleteButton);

    // Confirm deletion
    const confirmButton = await screen.findByRole("button", { name: /^Delete$/ });
    fireEvent.click(confirmButton);

    await waitFor(() => {
      // `objectContaining`, not an exact match: `authorizedFetch` (ADR 0016)
      // always attaches a `Headers` object, present or not, for the bearer
      // token an authenticated session would carry.
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/orgs/test-org/gsc-accounts/to-delete"),
        expect.objectContaining({ method: "DELETE" }),
      );
    });
  });

  it("displays error state on fetch failure", async () => {
    queueGsc(
      new Response(JSON.stringify({ detail: "Organization not found" }), { status: 404 }),
    );

    render(<GscAccountsView orgId="test-org" />);

    await waitFor(() => {
      // The error is displayed in an error card
      expect(screen.getByText(/Failed to load accounts/i)).toBeInTheDocument();
    });
  });

  it("opens form modal on add button click", async () => {
    queueGsc(
      new Response(JSON.stringify({ accounts: [] }), { status: 200 }),
    );

    render(<GscAccountsView orgId="test-org" />);

    const addButton = screen.getByRole("button", { name: /add account/i });
    fireEvent.click(addButton);

    await waitFor(() => {
      expect(screen.getByText(/add gsc account/i)).toBeInTheDocument();
    });
  });

  it("shows loading state while fetching", async () => {
    queueGsc(
      new Response(JSON.stringify({ accounts: [] }), { status: 200 }),
    );

    render(<GscAccountsView orgId="test-org" />);

    // Eventually resolves to empty state
    await waitFor(() => {
      expect(screen.getByText(/no accounts configured/i)).toBeInTheDocument();
    });
  });

  it("carries the Search Console and GA4 setup guide on this tab", async () => {
    queueGsc(
      new Response(JSON.stringify({ accounts: [] }), { status: 200 }),
    );

    render(<GscAccountsView orgId="test-org" />);

    const toggle = screen.getByText("Setup guide: Search Console and GA4 credentials");
    fireEvent.click(toggle);
    expect(screen.getByRole("heading", { name: "Search Console (GSC) credential" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "GA4 credential" })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText(/no accounts configured/i)).toBeInTheDocument();
    });
  });

  it("displays secret override status correctly", async () => {
    const mockAccounts = [
      { account_name: "no-secret", client_id: "123", has_secret_override: false },
      { account_name: "with-secret", client_id: "456", has_secret_override: true },
    ];

    queueGsc(
      new Response(JSON.stringify({ accounts: mockAccounts }), { status: 200 }),
    );

    render(<GscAccountsView orgId="test-org" />);

    await waitFor(() => {
      expect(screen.getByText("no-secret")).toBeInTheDocument();
      expect(screen.getByText("with-secret")).toBeInTheDocument();
    });
  });

  describe("organisation GA4 status line", () => {
    const ga4Reply =
      (body: unknown, status = 200) =>
      async (): Promise<Response> =>
        new Response(JSON.stringify(body), { status });

    const ga4CallCount = (): number =>
      (fetch as any).mock.calls.filter(([url]: [string]) => String(url).includes("/orgs/test-org/ga4")).length;

    /** The focusable span that carries the dot, label and tooltip. */
    const triggerFor = (label: string): HTMLElement =>
      screen.getByText(label).closest(".gsa-ga4-trigger") as HTMLElement;

    const dotOf = (label: string): Element =>
      triggerFor(label).querySelector(".gsa-ga4-dot") as Element;

    it("shows a green 'GA4 credential stored' line when a property is mapped", async () => {
      ga4Handler = ga4Reply({ status: "mapped", property_id: "123" });
      queueGsc(new Response(JSON.stringify({ accounts: [] }), { status: 200 }));

      render(<GscAccountsView orgId="test-org" />);

      await waitFor(() => {
        expect(screen.getByText("GA4 credential stored")).toBeInTheDocument();
      });
      expect(dotOf("GA4 credential stored")).toHaveClass("gsa-ga4-dot-ok");
    });

    it("shows the same green line for unmapped, not red, with a tooltip saying no property is mapped", async () => {
      ga4Handler = ga4Reply({ status: "unmapped", property_id: null });
      queueGsc(new Response(JSON.stringify({ accounts: [] }), { status: 200 }));

      render(<GscAccountsView orgId="test-org" />);

      await waitFor(() => {
        expect(screen.getByText("GA4 credential stored")).toBeInTheDocument();
      });
      expect(dotOf("GA4 credential stored")).toHaveClass("gsa-ga4-dot-ok");
      expect(dotOf("GA4 credential stored")).not.toHaveClass("gsa-ga4-dot-missing");

      fireEvent.focus(triggerFor("GA4 credential stored"));
      expect(await screen.findByRole("tooltip")).toHaveTextContent(/no property is mapped yet/i);
    });

    it("shows a red 'No GA4 credential' line when not configured", async () => {
      ga4Handler = ga4Reply({ status: "not_configured", property_id: null });
      queueGsc(new Response(JSON.stringify({ accounts: [] }), { status: 200 }));

      render(<GscAccountsView orgId="test-org" />);

      await waitFor(() => {
        expect(screen.getByText("No GA4 credential")).toBeInTheDocument();
      });
      expect(dotOf("No GA4 credential")).toHaveClass("gsa-ga4-dot-missing");
    });

    it("shows a grey 'GA4 status unavailable' line on an error response, not red", async () => {
      ga4Handler = ga4Reply({ detail: "GA4 is not configured" }, 503);
      queueGsc(
        new Response(
          JSON.stringify({ accounts: [{ account_name: "still-listed", client_id: null, has_secret_override: false }] }),
          { status: 200 },
        ),
      );

      render(<GscAccountsView orgId="test-org" />);

      await waitFor(() => {
        expect(screen.getByText("GA4 status unavailable")).toBeInTheDocument();
      });
      expect(dotOf("GA4 status unavailable")).toHaveClass("gsa-ga4-dot-muted");
      expect(dotOf("GA4 status unavailable")).not.toHaveClass("gsa-ga4-dot-missing");
      // A failed GA4 read never hides the GSC list.
      expect(screen.getByText("still-listed")).toBeInTheDocument();
    });

    it("treats a network failure as unavailable, not red", async () => {
      ga4Handler = () => Promise.reject(new TypeError("Failed to fetch"));
      queueGsc(new Response(JSON.stringify({ accounts: [] }), { status: 200 }));

      render(<GscAccountsView orgId="test-org" />);

      await waitFor(() => {
        expect(screen.getByText("GA4 status unavailable")).toBeInTheDocument();
      });
      expect(dotOf("GA4 status unavailable")).toHaveClass("gsa-ga4-dot-muted");
    });

    it("shows a grey 'GA4 status unavailable' line while loading, not red", () => {
      ga4Handler = () => new Promise<Response>(() => {});
      queueGsc(new Response(JSON.stringify({ accounts: [] }), { status: 200 }));

      render(<GscAccountsView orgId="test-org" />);

      expect(screen.getByText("GA4 status unavailable")).toBeInTheDocument();
      expect(dotOf("GA4 status unavailable")).toHaveClass("gsa-ga4-dot-muted");
    });

    it("opens the explanation on keyboard focus and not only on hover", async () => {
      ga4Handler = ga4Reply({ status: "not_configured", property_id: null });
      queueGsc(new Response(JSON.stringify({ accounts: [] }), { status: 200 }));

      render(<GscAccountsView orgId="test-org" />);

      await waitFor(() => {
        expect(screen.getByText("No GA4 credential")).toBeInTheDocument();
      });
      expect(triggerFor("No GA4 credential")).toHaveAttribute("tabindex", "0");

      fireEvent.focus(triggerFor("No GA4 credential"));
      expect(await screen.findByRole("tooltip")).toHaveTextContent(/no GA4 credential stored/i);
    });

    it("reads the org GA4 status once per page load", async () => {
      ga4Handler = ga4Reply({ status: "mapped", property_id: "123" });
      queueGsc(new Response(JSON.stringify({ accounts: [] }), { status: 200 }));

      render(<GscAccountsView orgId="test-org" />);

      await waitFor(() => {
        expect(screen.getByText("GA4 credential stored")).toBeInTheDocument();
      });
      expect(ga4CallCount()).toBe(1);
    });
  });
});
