import { describe, it, expect, beforeEach, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { Ga4Section } from "./Ga4Section";

/**
 * The GA4 section of the GSC account form (ADR 0038).
 *
 * Rules under test: nothing is requested until the section is opened; the
 * mapping line states exactly which of three states holds; a refusal shows the
 * engine's fixed reason and never a provider message; the token is write-only,
 * so it is never rendered back; and a property is mapped only from the list.
 */

const TOKEN = "1//0gUI-GA4-CANARY-token"; // noqa: S105 - fake canary
const OPEN = "Set up GA4 access (optional)";

function json(status: number, body: unknown) {
  return { ok: status < 400, status, statusText: "", json: async () => body };
}

function openSection(): void {
  fireEvent.click(screen.getByRole("button", { name: OPEN }));
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

describe("Ga4Section", () => {
  it("makes no GA4 request until it is opened", () => {
    render(<Ga4Section orgId="acme" />);
    expect(fetch).not.toHaveBeenCalled();
  });

  it.each([
    [{ status: "not_configured", property_id: null }, "No GA4 credential is stored for this organisation."],
    [
      { status: "unmapped", property_id: null },
      "A GA4 credential is stored. GA4 is not requested until you choose a property.",
    ],
    [{ status: "mapped", property_id: "123456789" }, "Mapped property: 123456789"],
  ])("states the mapping for %j", async (view, line) => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(json(200, view));
    render(<Ga4Section orgId="acme" />);
    openSection();
    expect(await screen.findByText(line)).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/orgs/acme/ga4"),
      expect.anything(),
    );
  });

  it("saves the token, clears the field, and never renders it back", async () => {
    (fetch as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce(json(200, { status: "not_configured", property_id: null }))
      .mockResolvedValueOnce(json(200, { status: "unmapped", property_id: null }));
    render(<Ga4Section orgId="acme" />);
    openSection();
    await screen.findByText("No GA4 credential is stored for this organisation.");

    const input = screen.getByLabelText("GA4 refresh token") as HTMLInputElement;
    fireEvent.change(input, { target: { value: TOKEN } });
    fireEvent.click(screen.getByRole("button", { name: "Verify and save GA4 token" }));

    await waitFor(() =>
      expect(screen.getByText("A GA4 credential is stored. GA4 is not requested until you choose a property.")).toBeInTheDocument(),
    );
    const [, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[1] as [string, RequestInit];
    expect(init.method).toBe("PUT");
    expect(JSON.parse(String(init.body))).toEqual({ refresh_token: TOKEN });
    expect(document.body.innerHTML).not.toContain(TOKEN);
  });

  it("shows the fixed reason when Google refuses the scope, and stores nothing", async () => {
    (fetch as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce(json(200, { status: "not_configured", property_id: null }))
      .mockResolvedValueOnce(json(422, { detail: "not authorized, re-add the account" }));
    render(<Ga4Section orgId="acme" />);
    openSection();
    await screen.findByText("No GA4 credential is stored for this organisation.");

    fireEvent.change(screen.getByLabelText("GA4 refresh token"), { target: { value: TOKEN } });
    fireEvent.click(screen.getByRole("button", { name: "Verify and save GA4 token" }));

    expect(await screen.findByText("not authorized, re-add the account")).toBeInTheDocument();
    expect(screen.getByText("No GA4 credential is stored for this organisation.")).toBeInTheDocument();
  });

  it("says why when the picker cannot list properties, rather than an empty list", async () => {
    (fetch as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce(json(200, { status: "unmapped", property_id: null }))
      .mockResolvedValueOnce(
        json(200, {
          status: "not_authorized",
          reason: "not authorized, re-add the account",
          truncated: false,
          properties: [],
        }),
      );
    render(<Ga4Section orgId="acme" />);
    openSection();
    await screen.findByText(/A GA4 credential is stored/);

    fireEvent.click(screen.getByRole("button", { name: "List GA4 properties" }));
    expect(await screen.findByText("not authorized, re-add the account")).toBeInTheDocument();
    expect(screen.queryByLabelText("GA4 property to map")).not.toBeInTheDocument();
  });

  it("lists properties and maps the one chosen", async () => {
    (fetch as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce(json(200, { status: "unmapped", property_id: null }))
      .mockResolvedValueOnce(
        json(200, {
          status: "ok",
          reason: "",
          truncated: false,
          properties: [{ property_id: "111222333", display_name: "Acme site" }],
        }),
      )
      .mockResolvedValueOnce(json(200, { status: "mapped", property_id: "111222333" }));
    render(<Ga4Section orgId="acme" />);
    openSection();
    await screen.findByText(/A GA4 credential is stored/);

    fireEvent.click(screen.getByRole("button", { name: "List GA4 properties" }));
    // The placeholder is the picker's own text; antd does not carry an
    // aria-label onto the combobox, so the placeholder is what is reachable.
    fireEvent.mouseDown(await screen.findByText("Choose a property"));
    const dropdown = await waitFor(
      () => {
        const node = document.querySelector<HTMLElement>(".ant-select-dropdown");
        if (!node) throw new Error("dropdown not open yet");
        return node;
      },
      { timeout: 15_000 },
    );
    fireEvent.click(within(dropdown).getByTitle("Acme site (111222333)"));
    fireEvent.click(screen.getByRole("button", { name: "Map this property" }));

    expect(await screen.findByText("Mapped property: 111222333")).toBeInTheDocument();
    const [, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[2] as [string, RequestInit];
    expect(init.method).toBe("PUT");
    expect(JSON.parse(String(init.body))).toEqual({ property_id: "111222333" });
  }, 30_000);

  it("removes the credential and its mapping after confirmation", async () => {
    (fetch as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce(json(200, { status: "mapped", property_id: "111222333" }))
      .mockResolvedValueOnce(json(204, undefined));
    render(<Ga4Section orgId="acme" />);
    openSection();
    await screen.findByText("Mapped property: 111222333");

    fireEvent.click(screen.getByRole("button", { name: "Remove GA4 access" }));
    fireEvent.click(await screen.findByRole("button", { name: "Remove" }));

    expect(await screen.findByText("No GA4 credential is stored for this organisation.")).toBeInTheDocument();
    const [, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[1] as [string, RequestInit];
    expect(init.method).toBe("DELETE");
  });

  it("reports a failed status read as an error rather than as not configured", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error("network down"));
    render(<Ga4Section orgId="acme" />);
    openSection();
    expect(await screen.findByText("GA4 status could not be loaded.")).toBeInTheDocument();
    expect(screen.queryByText("No GA4 credential is stored for this organisation.")).not.toBeInTheDocument();
  });
});
