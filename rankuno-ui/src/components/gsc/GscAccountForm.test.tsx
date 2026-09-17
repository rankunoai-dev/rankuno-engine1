import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { GscAccountForm } from "./GscAccountForm";

vi.stubGlobal("fetch", vi.fn());

describe("GscAccountForm", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders form fields when open", () => {
    render(
      <GscAccountForm open={true} orgId="test-org" onClose={() => {}} />,
    );

    expect(screen.getByLabelText(/account name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/oauth 2.0 refresh token/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/oauth client id/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/oauth client secret/i)).toBeInTheDocument();
  });

  it("does not render when closed", () => {
    render(
      <GscAccountForm open={false} orgId="test-org" onClose={() => {}} />,
    );

    expect(screen.queryByLabelText(/account name/i)).not.toBeInTheDocument();
  });

  it("validates account name format", async () => {
    render(
      <GscAccountForm open={true} orgId="test-org" onClose={() => {}} />,
    );

    const accountNameInput = screen.getByLabelText(/account name/i) as HTMLInputElement;

    // Invalid: uppercase
    fireEvent.change(accountNameInput, { target: { value: "MyAccount" } });
    fireEvent.click(screen.getByRole("button", { name: /add account/i }));

    await waitFor(() => {
      expect(screen.getByText(/must be 1-64 lowercase alphanumeric/i)).toBeInTheDocument();
    });
  });

  it("validates account name length", async () => {
    render(
      <GscAccountForm open={true} orgId="test-org" onClose={() => {}} />,
    );

    const accountNameInput = screen.getByLabelText(/account name/i) as HTMLInputElement;

    // Too long: 65 characters
    fireEvent.change(accountNameInput, { target: { value: "a".repeat(65) } });
    fireEvent.click(screen.getByRole("button", { name: /add account/i }));

    await waitFor(() => {
      expect(screen.getByText(/must be 1-64 lowercase alphanumeric/i)).toBeInTheDocument();
    });
  });

  it("accepts valid account names", async () => {
    (fetch as any).mockResolvedValueOnce(
      new Response(JSON.stringify({}), { status: 201 }),
    );

    render(
      <GscAccountForm open={true} orgId="test-org" onClose={() => {}} />,
    );

    fireEvent.change(screen.getByLabelText(/account name/i), { target: { value: "my-account-1" } });
    fireEvent.change(screen.getByLabelText(/oauth 2.0 refresh token/i), { target: { value: "test-token-123" } });

    fireEvent.click(screen.getByRole("button", { name: /add account/i }));

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/orgs/test-org/gsc-accounts"),
        expect.objectContaining({ method: "POST" }),
      );
    });
  });

  it("requires refresh token", async () => {
    render(
      <GscAccountForm open={true} orgId="test-org" onClose={() => {}} />,
    );

    fireEvent.change(screen.getByLabelText(/account name/i), { target: { value: "my-account" } });
    fireEvent.click(screen.getByRole("button", { name: /add account/i }));

    await waitFor(() => {
      expect(screen.getByText(/enter the oauth refresh token/i)).toBeInTheDocument();
    });
  });

  it("submits form with optional fields", async () => {
    (fetch as any).mockResolvedValueOnce(
      new Response(JSON.stringify({}), { status: 201 }),
    );

    render(
      <GscAccountForm open={true} orgId="test-org" onClose={() => {}} />,
    );

    fireEvent.change(screen.getByLabelText(/account name/i), { target: { value: "my-account" } });
    fireEvent.change(screen.getByLabelText(/oauth 2.0 refresh token/i), { target: { value: "token-123" } });
    // Leave client_id and client_secret empty

    fireEvent.click(screen.getByRole("button", { name: /add account/i }));

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          method: "POST",
          body: expect.stringContaining('"client_id":null'),
        }),
      );
    });
  });

  it("submits form with all fields", async () => {
    (fetch as any).mockResolvedValueOnce(
      new Response(JSON.stringify({}), { status: 201 }),
    );

    render(
      <GscAccountForm open={true} orgId="test-org" onClose={() => {}} />,
    );

    fireEvent.change(screen.getByLabelText(/account name/i), { target: { value: "my-account" } });
    fireEvent.change(screen.getByLabelText(/oauth 2.0 refresh token/i), { target: { value: "token-123" } });
    fireEvent.change(screen.getByLabelText(/oauth client id/i), { target: { value: "client-456" } });
    fireEvent.change(screen.getByLabelText(/oauth client secret/i), { target: { value: "secret-789" } });

    fireEvent.click(screen.getByRole("button", { name: /add account/i }));

    await waitFor(() => {
      const callBody = (fetch as any).mock.calls[0][1].body;
      expect(callBody).toContain("my-account");
      expect(callBody).toContain("client-456");
    });
  });

  it("calls onClose when cancelled", async () => {
    const onClose = vi.fn();

    render(
      <GscAccountForm open={true} orgId="test-org" onClose={onClose} />,
    );

    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));

    expect(onClose).toHaveBeenCalled();
  });

  it("calls onSuccess after successful submission", async () => {
    const onSuccess = vi.fn();

    (fetch as any).mockResolvedValueOnce(
      new Response(JSON.stringify({}), { status: 201 }),
    );

    render(
      <GscAccountForm open={true} orgId="test-org" onClose={() => {}} onSuccess={onSuccess} />,
    );

    fireEvent.change(screen.getByLabelText(/account name/i), { target: { value: "my-account" } });
    fireEvent.change(screen.getByLabelText(/oauth 2.0 refresh token/i), { target: { value: "token-123" } });

    fireEvent.click(screen.getByRole("button", { name: /add account/i }));

    await waitFor(() => {
      expect(onSuccess).toHaveBeenCalled();
    });
  });

  it("handles API errors gracefully", async () => {
    (fetch as any).mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Account already exists" }), { status: 400 }),
    );

    render(
      <GscAccountForm open={true} orgId="test-org" onClose={() => {}} />,
    );

    fireEvent.change(screen.getByLabelText(/account name/i), { target: { value: "my-account" } });
    fireEvent.change(screen.getByLabelText(/oauth 2.0 refresh token/i), { target: { value: "token-123" } });

    fireEvent.click(screen.getByRole("button", { name: /add account/i }));

    await waitFor(() => {
      expect(screen.getByText(/account already exists/i)).toBeInTheDocument();
    });
  });

  it("handles network errors", async () => {
    (fetch as any).mockRejectedValueOnce(new TypeError("Network error"));

    render(
      <GscAccountForm open={true} orgId="test-org" onClose={() => {}} />,
    );

    fireEvent.change(screen.getByLabelText(/account name/i), { target: { value: "my-account" } });
    fireEvent.change(screen.getByLabelText(/oauth 2.0 refresh token/i), { target: { value: "token-123" } });

    fireEvent.click(screen.getByRole("button", { name: /add account/i }));

    await waitFor(() => {
      expect(screen.getByText(/failed to add account/i)).toBeInTheDocument();
    });
  });

  it("accepts valid special characters in account name", async () => {
    (fetch as any).mockResolvedValueOnce(
      new Response(JSON.stringify({}), { status: 201 }),
    );

    render(
      <GscAccountForm open={true} orgId="test-org" onClose={() => {}} />,
    );

    fireEvent.change(screen.getByLabelText(/account name/i), { target: { value: "my-account_1-2" } });
    fireEvent.change(screen.getByLabelText(/oauth 2.0 refresh token/i), { target: { value: "token-123" } });

    fireEvent.click(screen.getByRole("button", { name: /add account/i }));

    await waitFor(() => {
      expect(fetch).toHaveBeenCalled();
    });
  });
});
