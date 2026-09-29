import { describe, expect, it } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { UnavailableSettings } from "./UnavailableSettings";

/**
 * The one defect this component exists to avoid is a control that accepts a
 * value nothing acts on, so "presents no input" is asserted as hard as the
 * prose is. RAE shipped both of these as live-looking fields that were
 * discarded before the crawl started; the whole point here is that an
 * operator hunting for that textarea finds a sentence instead.
 */

/** Open one disclosure by its header, which antd renders as a real button. */
function open(name: RegExp): HTMLElement {
  const header = screen.getByRole("button", { name });
  expect(header).toHaveAttribute("aria-expanded", "false");
  fireEvent.click(header);
  expect(header).toHaveAttribute("aria-expanded", "true");
  // antd emits no `aria-controls`; the content is the sibling of the header
  // inside the same item, which is also the DOM order a screen reader follows.
  const panel = header.parentElement?.querySelector(".ant-collapse-content");
  expect(panel).not.toBeNull();
  return panel as HTMLElement;
}

describe("UnavailableSettings", () => {
  it("is collapsed on arrival and says where each setting went in its header", () => {
    render(<UnavailableSettings template={null} />);

    // The sentence an operator reads while scanning, before opening anything.
    expect(
      screen.getByRole("button", { name: /Include & Exclude — these live in the template, not here/ }),
    ).toHaveAttribute("aria-expanded", "false");
    expect(
      screen.getByRole("button", { name: /Google Analytics 4 — not connected, and not exported/ }),
    ).toHaveAttribute("aria-expanded", "false");
  });

  it("explains that include and exclude have no command-line setting and live in the config", () => {
    render(<UnavailableSettings template={null} />);

    const panel = open(/Include & Exclude/);

    expect(
      within(panel).getByText(/no command-line setting for include or exclude patterns/i),
    ).toBeInTheDocument();
    expect(
      within(panel).getByText(/kept inside the configuration file itself/i),
    ).toBeInTheDocument();
    // And what to do instead, which is the only half that is actionable.
    expect(within(panel).getByText(/picking that template above is/i)).toBeInTheDocument();
  });

  it("quotes the chosen template's own note, as text", () => {
    render(
      <UnavailableSettings
        template={{ name: "js-crawl", description: "Skips /admin/ & /login/ <all methods>." }}
      />,
    );

    const panel = open(/Include & Exclude/);

    const note = within(panel).getByText("Skips /admin/ & /login/ <all methods>.");
    // Untrusted text from the worker: the angle brackets stay characters.
    expect(note.innerHTML).toBe("Skips /admin/ &amp; /login/ &lt;all methods&gt;.");
    expect(within(panel).getByText(/says about itself/)).toBeInTheDocument();
  });

  it("says nobody wrote a note rather than implying the template excludes nothing", () => {
    // A template with no sidecar carries `description: ""`. Under the Select
    // that renders as nothing at all, which is right there and wrong here:
    // this panel promised to show what the template skips.
    render(<UnavailableSettings template={{ name: "plain", description: "" }} />);

    const panel = open(/Include & Exclude/);

    expect(within(panel).getByText(/Nobody has written a note beside/)).toBeInTheDocument();
    expect(within(panel).getByText("plain")).toBeInTheDocument();
    expect(within(panel).getByText("plain.md")).toBeInTheDocument();
    // The claim that must never appear: silence about a binary file is not a
    // report that the file does nothing.
    expect(within(panel).queryByText(/excludes nothing/i)).not.toBeInTheDocument();
  });

  it("says the machine's own configuration applies when no template is chosen", () => {
    render(<UnavailableSettings template={null} />);

    const panel = open(/Include & Exclude/);

    expect(
      within(panel).getByText(/whatever configuration\s+Screaming Frog is already set to/i),
    ).toBeInTheDocument();
    expect(within(panel).getByText(/cannot\s+see what that is/i)).toBeInTheDocument();
  });

  it("explains that GA4 was never wired and would export nothing even if it were", () => {
    render(<UnavailableSettings template={null} />);

    const panel = open(/Google Analytics 4/);

    // Half one: the four RAE fields, named, and what became of them.
    expect(within(panel).getByText(/Gmail account, a GA4 account, a GA4 property/)).toBeInTheDocument();
    expect(within(panel).getByText(/recorded with the crawl and then dropped/)).toBeInTheDocument();
    // Half two, the part that survives someone "fixing" the connection: the
    // export manifest does not request the Analytics tab.
    expect(within(panel).getByText(/ask for the Analytics tab/)).toBeInTheDocument();
    expect(within(panel).getByText(/no Analytics data in the export/)).toBeInTheDocument();
  });

  it("offers nothing that could be mistaken for a field", () => {
    render(
      <UnavailableSettings template={{ name: "js-crawl", description: "Skips /admin/." }} />,
    );
    open(/Include & Exclude/);
    open(/Google Analytics 4/);

    for (const role of ["textbox", "combobox", "checkbox", "radio", "spinbutton", "searchbox"] as const) {
      expect(screen.queryAllByRole(role)).toHaveLength(0);
    }
    expect(document.querySelectorAll("input, textarea, select")).toHaveLength(0);
  });

  it("puts the disclosures under a labelled region with a heading", () => {
    render(<UnavailableSettings template={null} />);

    // A landmark with an accessible name, so the group is reachable by a
    // screen reader rather than being three loose paragraphs after a form.
    const region = screen.getByRole("region", { name: "Settings that are not on this form" });
    expect(
      within(region).getByRole("heading", { name: "Settings that are not on this form" }),
    ).toBeInTheDocument();
  });

  it("reaches both headers by keyboard", () => {
    render(<UnavailableSettings template={null} />);

    for (const name of [/Include & Exclude/, /Google Analytics 4/]) {
      const header = screen.getByRole("button", { name });
      // antd's header is a div; it is only usable if it is in the tab order.
      expect(header).toHaveAttribute("tabindex", "0");
      fireEvent.keyDown(header, { key: "Enter", keyCode: 13 });
      expect(header).toHaveAttribute("aria-expanded", "true");
    }
  });
});
