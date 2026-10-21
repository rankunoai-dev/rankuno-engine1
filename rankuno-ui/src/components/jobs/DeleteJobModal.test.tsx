import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DeleteJobModal } from "./DeleteJobModal";

describe("DeleteJobModal", () => {
  it("offers the saved password to a password manager, not a new one (ADR 0042)", () => {
    render(<DeleteJobModal label="e.com" open onClose={vi.fn()} onConfirm={vi.fn()} />);
    const input = document.getElementById("delete-password");
    expect(input).not.toBeNull();
    expect(input).toHaveAttribute("autocomplete", "current-password");
  });
});
