import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { GscAccountsView } from "./GscAccountsView";

// Mock the API
vi.stubGlobal("fetch", vi.fn());

describe("GscAccountsView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the header and add button", async () => {
    (fetch as any).mockResolvedValueOnce(
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

    (fetch as any).mockResolvedValueOnce(
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

    (fetch as any).mockResolvedValueOnce(
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
    (fetch as any).mockResolvedValueOnce(
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
    (fetch as any).mockResolvedValueOnce(
      new Response(JSON.stringify({ accounts: mockAccounts }), { status: 200 }),
    );

    // Second call: delete account
    (fetch as any).mockResolvedValueOnce(
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
    (fetch as any).mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Organization not found" }), { status: 404 }),
    );

    render(<GscAccountsView orgId="test-org" />);

    await waitFor(() => {
      // The error is displayed in an error card
      expect(screen.getByText(/Failed to load accounts/i)).toBeInTheDocument();
    });
  });

  it("opens form modal on add button click", async () => {
    (fetch as any).mockResolvedValueOnce(
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
    (fetch as any).mockResolvedValueOnce(
      new Response(JSON.stringify({ accounts: [] }), { status: 200 }),
    );

    render(<GscAccountsView orgId="test-org" />);

    // Eventually resolves to empty state
    await waitFor(() => {
      expect(screen.getByText(/no accounts configured/i)).toBeInTheDocument();
    });
  });

  it("displays secret override status correctly", async () => {
    const mockAccounts = [
      { account_name: "no-secret", client_id: "123", has_secret_override: false },
      { account_name: "with-secret", client_id: "456", has_secret_override: true },
    ];

    (fetch as any).mockResolvedValueOnce(
      new Response(JSON.stringify({ accounts: mockAccounts }), { status: 200 }),
    );

    render(<GscAccountsView orgId="test-org" />);

    await waitFor(() => {
      expect(screen.getByText("no-secret")).toBeInTheDocument();
      expect(screen.getByText("with-secret")).toBeInTheDocument();
    });
  });
});
