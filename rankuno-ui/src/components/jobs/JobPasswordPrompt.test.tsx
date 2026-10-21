import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { JobPasswordPrompt } from "./JobPasswordPrompt";

/**
 * The prompt that stands between an operator and a write to a protected crawl
 * (ADR 0042). It sends nothing without a password, and keeps itself open when
 * the server refuses one, so a mistyped password can be corrected in place.
 */
function mount(onSubmit: (password: string) => Promise<boolean>) {
  render(
    <JobPasswordPrompt
      open
      title="Deletion password"
      okText="Cancel crawl"
      description="This crawl is protected."
      onSubmit={onSubmit}
      onCancel={vi.fn()}
    />,
  );
}

describe("JobPasswordPrompt", () => {
  it("sends nothing when the password is blank", async () => {
    const onSubmit = vi.fn().mockResolvedValue(true);
    mount(onSubmit);
    fireEvent.click(screen.getByRole("button", { name: "Cancel crawl" }));
    expect(await screen.findByText("Enter the crawl's deletion password.")).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("keeps itself open with a message when the server refuses the password", async () => {
    const onSubmit = vi.fn().mockResolvedValue(false);
    mount(onSubmit);
    fireEvent.change(screen.getByPlaceholderText("Deletion password"), {
      target: { value: "wrong-password-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Cancel crawl" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith("wrong-password-1"));
    expect(await screen.findByText(/was not accepted/)).toBeInTheDocument();
  });
});
