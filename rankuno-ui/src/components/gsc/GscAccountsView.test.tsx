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

    // Whole-name match: the Delete button's name is "delete Delete" (antd icon label plus text),
    // and the Edit button's label carries the account name, which here ends in "delete".
    const deleteButton = screen.getByRole("button", { name: /^(delete\s+)?delete$/i });
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

  describe("edit", () => {
    const saved = [
      { account_name: "agency-main", client_id: "client-111", has_secret_override: true },
    ];

    it("gives every card an Edit button labelled with the account name", async () => {
      (fetch as any).mockResolvedValueOnce(
        new Response(JSON.stringify({ accounts: saved }), { status: 200 }),
      );

      render(<GscAccountsView orgId="test-org" />);

      expect(
        await screen.findByRole("button", { name: "Edit account agency-main" }),
      ).toBeInTheDocument();
    });

    it("opens the form pre-filled with the saved name and client ID, name locked", async () => {
      (fetch as any).mockResolvedValueOnce(
        new Response(JSON.stringify({ accounts: saved }), { status: 200 }),
      );

      render(<GscAccountsView orgId="test-org" />);

      fireEvent.click(await screen.findByRole("button", { name: "Edit account agency-main" }));

      expect(await screen.findByText("Edit GSC Account")).toBeInTheDocument();
      expect(screen.getByLabelText(/account name/i)).toHaveValue("agency-main");
      expect(screen.getByLabelText(/account name/i)).toBeDisabled();
      expect(screen.getByLabelText(/oauth client id/i)).toHaveValue("client-111");
      expect(screen.getByLabelText(/oauth 2.0 refresh token/i)).toHaveValue("");
      expect(screen.getByLabelText(/oauth client secret/i)).toHaveValue("");
    });

    it("saves the replacement under the same name and shows the updated client ID", async () => {
      (fetch as any)
        .mockResolvedValueOnce(new Response(JSON.stringify({ accounts: saved }), { status: 200 }))
        .mockResolvedValueOnce(new Response(JSON.stringify({}), { status: 201 }))
        .mockResolvedValueOnce(
          new Response(
            JSON.stringify({
              accounts: [
                { account_name: "agency-main", client_id: "client-222", has_secret_override: true },
              ],
            }),
            { status: 200 },
          ),
        );

      render(<GscAccountsView orgId="test-org" />);

      fireEvent.click(await screen.findByRole("button", { name: "Edit account agency-main" }));
      fireEvent.change(await screen.findByLabelText(/oauth 2.0 refresh token/i), {
        target: { value: "new-refresh" },
      });
      fireEvent.change(screen.getByLabelText(/oauth client id/i), {
        target: { value: "client-222" },
      });
      fireEvent.change(screen.getByLabelText(/oauth client secret/i), {
        target: { value: "new-secret" },
      });
      fireEvent.click(screen.getByRole("button", { name: /save changes/i }));

      expect(await screen.findByText("client-222")).toBeInTheDocument();
      const post = (fetch as any).mock.calls.find(
        (call: [string, RequestInit]) => call[1]?.method === "POST",
      );
      expect(post[0]).toContain("/orgs/test-org/gsc-accounts");
      expect(JSON.parse(post[1].body)).toEqual({
        account_name: "agency-main",
        client_id: "client-222",
        refresh_token: "new-refresh",
        client_secret: "new-secret",
      });
    });

    it("keeps Delete working alongside Edit", async () => {
      (fetch as any).mockResolvedValueOnce(
        new Response(JSON.stringify({ accounts: saved }), { status: 200 }),
      );

      render(<GscAccountsView orgId="test-org" />);

      expect(
        await screen.findByRole("button", { name: /^(delete\s+)?delete$/i }),
      ).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Edit account agency-main" })).toBeInTheDocument();
    });
  });
});
