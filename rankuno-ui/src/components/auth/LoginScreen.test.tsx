import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { LoginScreen } from "./LoginScreen";
import { useAuthStore } from "../../store/useAuthStore";

vi.stubGlobal("fetch", vi.fn());

function resetStore(): void {
  useAuthStore.setState({
    token: null,
    orgId: null,
    expiresAt: null,
    loggingIn: false,
    loginError: null,
  });
}

describe("LoginScreen", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    resetStore();
  });

  it("renders the operator id and password fields", () => {
    render(<LoginScreen />);

    expect(screen.getByLabelText(/operator id/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^password$/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument();
  });

  it("requires both fields before submitting", async () => {
    render(<LoginScreen />);

    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByText(/enter your operator id/i)).toBeInTheDocument();
      expect(screen.getByText(/enter your password/i)).toBeInTheDocument();
    });
    expect(fetch).not.toHaveBeenCalled();
  });

  it("logs in successfully and stores the session", async () => {
    (fetch as any).mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          token: "session-token",
          token_type: "bearer",
          org_id: "acme",
          expires_at: "2099-01-01T00:00:00Z",
        }),
        { status: 200 },
      ),
    );

    render(<LoginScreen />);

    fireEvent.change(screen.getByLabelText(/operator id/i), { target: { value: "op-1" } });
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: "correct-horse" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(useAuthStore.getState().token).toBe("session-token");
    });
    expect(useAuthStore.getState().orgId).toBe("acme");
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/auth/login"),
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ operator_id: "op-1", password: "correct-horse" }),
      }),
    );
  });

  it("shows the server's generic message on rejected credentials, without naming which field was wrong", async () => {
    (fetch as any).mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "invalid operator id or password" }), { status: 401 }),
    );

    render(<LoginScreen />);

    fireEvent.change(screen.getByLabelText(/operator id/i), { target: { value: "nobody" } });
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: "wrong" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByText(/invalid operator id or password/i)).toBeInTheDocument();
    });
    // Nothing on screen says whether "nobody" doesn't exist or the password
    // was wrong — the alert text is the server's own single, generic detail.
    expect(screen.queryByText(/unknown operator/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/wrong password/i)).not.toBeInTheDocument();
    expect(useAuthStore.getState().token).toBeNull();
  });

  it("shows a distinct message for a network failure", async () => {
    (fetch as any).mockRejectedValueOnce(new TypeError("Failed to fetch"));

    render(<LoginScreen />);

    fireEvent.change(screen.getByLabelText(/operator id/i), { target: { value: "op-1" } });
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: "pw" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByText(/cannot reach the engine/i)).toBeInTheDocument();
    });
    expect(screen.queryByText(/invalid operator id or password/i)).not.toBeInTheDocument();
  });

  it("disables the submit button while a login request is in flight", async () => {
    let resolveFetch: (value: Response) => void = () => {};
    (fetch as any).mockReturnValueOnce(
      new Promise<Response>((resolve) => {
        resolveFetch = resolve;
      }),
    );

    render(<LoginScreen />);

    fireEvent.change(screen.getByLabelText(/operator id/i), { target: { value: "op-1" } });
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: "pw" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /signing in/i })).toBeDisabled();
    });

    resolveFetch(
      new Response(
        JSON.stringify({
          token: "t",
          token_type: "bearer",
          org_id: "acme",
          expires_at: "2099-01-01T00:00:00Z",
        }),
        { status: 200 },
      ),
    );

    await waitFor(() => {
      expect(useAuthStore.getState().loggingIn).toBe(false);
    });
  });

  it("clears the password field after a rejected login", async () => {
    (fetch as any).mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "invalid operator id or password" }), { status: 401 }),
    );

    render(<LoginScreen />);

    const passwordInput = screen.getByLabelText(/^password$/i) as HTMLInputElement;
    fireEvent.change(screen.getByLabelText(/operator id/i), { target: { value: "op-1" } });
    fireEvent.change(passwordInput, { target: { value: "wrong" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByText(/invalid operator id or password/i)).toBeInTheDocument();
    });
    expect(passwordInput.value).toBe("");
  });
});
