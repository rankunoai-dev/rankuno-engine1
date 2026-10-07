import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { useDashboardStore } from "../../store/useDashboardStore";
import { crawl } from "../../test/factories";
import { KpiMetricStrip } from "./KpiMetricStrip";

beforeEach(() => {
  useDashboardStore.setState({
    kpisExpanded: true,
  });
});

describe("KpiMetricStrip", () => {
  const result = crawl().summary ? crawl() : crawl({ summary: crawl().summary });

  it("renders the KPI header with toggle button", () => {
    render(<KpiMetricStrip result={result} />);
    expect(screen.getByText("Key Performance Indicators")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "▾" })).toBeInTheDocument();
  });

  it("displays all five KPI cards when expanded", () => {
    render(<KpiMetricStrip result={result} />);
    expect(screen.getByText("URLs classified")).toBeInTheDocument();
    expect(screen.getByText("Placed in navigation")).toBeInTheDocument();
    expect(screen.getByText("OTHERS")).toBeInTheDocument();
    expect(screen.getByText("Unclassified")).toBeInTheDocument();
    expect(screen.getByText("LLM spend")).toBeInTheDocument();
  });

  it("starts with expanded state and aria-expanded true", () => {
    const { container } = render(<KpiMetricStrip result={result} />);
    const toggle = screen.getByRole("button", { name: "▾" });
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    const grid = container.querySelector("#kpi-metrics-grid");
    expect(grid?.getAttribute("aria-hidden")).toBe("false");
  });

  it("collapses the grid when toggle is clicked", () => {
    const { container } = render(<KpiMetricStrip result={result} />);
    const toggle = screen.getByRole("button", { name: "▾" });
    fireEvent.click(toggle);

    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(toggle.textContent).toBe("▸");
    const grid = container.querySelector("#kpi-metrics-grid");
    expect(grid?.getAttribute("aria-hidden")).toBe("true");
  });

  it("expands the grid again when toggle is clicked while collapsed", () => {
    useDashboardStore.setState({ kpisExpanded: false });
    const { container } = render(<KpiMetricStrip result={result} />);
    const toggle = screen.getByRole("button", { name: "▸" });
    fireEvent.click(toggle);

    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(toggle.textContent).toBe("▾");
    const grid = container.querySelector("#kpi-metrics-grid");
    expect(grid?.getAttribute("aria-hidden")).toBe("false");
  });

  it("updates store state when toggle is clicked", () => {
    render(<KpiMetricStrip result={result} />);
    const toggle = screen.getByRole("button", { name: "▾" });
    const initialState = useDashboardStore.getState().kpisExpanded;

    fireEvent.click(toggle);
    const afterClick = useDashboardStore.getState().kpisExpanded;

    expect(afterClick).not.toBe(initialState);
  });

  it("has aria-controls attribute pointing to the grid", () => {
    render(<KpiMetricStrip result={result} />);
    const toggle = screen.getByRole("button", { name: "▾" });
    expect(toggle.getAttribute("aria-controls")).toBe("kpi-metrics-grid");
  });

  it("shows correct icon: ▾ when expanded, ▸ when collapsed", () => {
    const { rerender } = render(<KpiMetricStrip result={result} />);
    const toggle = screen.getByRole("button", { name: "▾" });
    expect(toggle.textContent).toBe("▾");

    useDashboardStore.setState({ kpisExpanded: false });
    rerender(<KpiMetricStrip result={result} />);
    const collapsedToggle = screen.getByRole("button", { name: "▸" });
    expect(collapsedToggle.textContent).toBe("▸");
  });

  it("persists toggle state across re-renders", () => {
    const { rerender } = render(<KpiMetricStrip result={result} />);
    const toggle = screen.getByRole("button", { name: "▾" });
    fireEvent.click(toggle);
    expect(useDashboardStore.getState().kpisExpanded).toBe(false);

    rerender(<KpiMetricStrip result={result} />);
    expect(screen.getByRole("button", { name: "▸" }).getAttribute("aria-expanded")).toBe("false");
  });

  it("has proper tooltip text for the toggle button", () => {
    render(<KpiMetricStrip result={result} />);
    const toggle = screen.getByRole("button", { name: "▾" });
    expect(toggle.title).toBe("Collapse KPI metrics");

    fireEvent.click(toggle);
    const collapsedToggle = screen.getByRole("button", { name: "▸" });
    expect(collapsedToggle.title).toBe("Expand KPI metrics");
  });
});
