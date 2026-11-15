import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  PaperPnlPositionChart,
  type PaperPnlPositionChartProps,
} from "./PaperPnlPositionChart";
import type { PaperChart, PaperClient } from "./client";

afterEach(cleanup);

/**
 * M4.3 — Workstation P&L + position chart from journal/export APIs.
 *
 * Transport note: every client here is an in-memory vi.fn() fake standing
 * in for ``GET /api/v1/paper/chart``. No real venue/engine lifecycle is
 * exercised or implied by these tests.
 */

function fixtureChart(overrides: Partial<PaperChart> = {}): PaperChart {
  return {
    schema_version: "1",
    armed: true,
    venue: "kraken",
    pair: "SUIUSD",
    mode: "paper",
    pack_id: "pack-fixture",
    starting_cash: "1000",
    pnl: [
      { ts_ms: 1000, value: "0" },
      { ts_ms: 2000, value: "-0.4" },
      { ts_ms: 3000, value: "19.12" },
    ],
    position: [
      { ts_ms: 1000, qty: "0" },
      { ts_ms: 2000, qty: "10" },
      { ts_ms: 3000, qty: "0" },
    ],
    marks: [
      { ts_ms: 2000, price: "10" },
      { ts_ms: 3000, price: "12" },
    ],
    ...overrides,
  };
}

function makeClient(
  chart: PaperChart | Promise<PaperChart> | Error,
): Pick<PaperClient, "getChart"> {
  if (chart instanceof Error) {
    return {
      getChart: vi.fn().mockRejectedValue(chart),
    };
  }
  return {
    getChart: vi.fn().mockResolvedValue(chart),
  };
}

function renderChart(
  overrides: Partial<PaperPnlPositionChartProps> = {},
): Pick<PaperClient, "getChart"> {
  const client = overrides.client ?? makeClient(fixtureChart());
  render(
    <PaperPnlPositionChart
      client={client}
      armed={overrides.armed ?? true}
      refreshKey={overrides.refreshKey}
    />,
  );
  return client;
}

describe("PaperPnlPositionChart (armed paper fixture)", () => {
  it("renders P&L and position series charts from the chart API", async () => {
    const client = renderChart();

    await screen.findByTestId("paper-pnl-chart-svg");
    expect(client.getChart).toHaveBeenCalledTimes(1);

    const pnlPanel = screen.getByTestId("paper-pnl-chart");
    expect(pnlPanel.textContent ?? "").toContain(
      "paper fills · cash + qty×mark − starting_cash",
    );
    const pnlLine = screen.getByTestId("paper-pnl-chart-line");
    expect(pnlLine.tagName).toBe("polyline");
    expect(
      (pnlLine.getAttribute("points") ?? "").split(" ").filter(Boolean).length,
    ).toBe(3);

    const positionPanel = screen.getByTestId("paper-position-chart");
    expect(positionPanel.textContent ?? "").toContain(
      "journal.owned_qty_after · base qty over time",
    );
    const positionLine = screen.getByTestId("paper-position-chart-line");
    expect(
      (positionLine.getAttribute("points") ?? "")
        .split(" ")
        .filter(Boolean).length,
    ).toBe(3);
  });

  it("falls back to the mark series when position points are empty", async () => {
    renderChart({
      client: makeClient(
        fixtureChart({
          position: [],
          marks: [
            { ts_ms: 1, price: "4.0" },
            { ts_ms: 2, price: "4.2" },
          ],
        }),
      ),
    });

    await screen.findByTestId("paper-marks-chart-svg");
    expect(screen.queryByTestId("paper-position-chart")).toBeNull();
    const markLine = screen.getByTestId("paper-marks-chart-line");
    expect(
      (markLine.getAttribute("points") ?? "").split(" ").filter(Boolean)
        .length,
    ).toBe(2);
  });

  it("keeps charts unavailable when series are empty", async () => {
    renderChart({
      client: makeClient(
        fixtureChart({ pnl: [], position: [], marks: [] }),
      ),
    });

    await screen.findByTestId("paper-pnl-chart-unavailable");
    expect(
      screen.getByTestId("paper-pnl-chart-unavailable").textContent,
    ).toBe("unavailable");
    // Empty position falls back to the marks panel; both stay unavailable.
    expect(
      screen.getByTestId("paper-marks-chart-unavailable").textContent,
    ).toBe("unavailable");
    expect(screen.queryByTestId("paper-pnl-chart-svg")).toBeNull();
    expect(screen.queryByTestId("paper-position-chart")).toBeNull();
  });

  it("surfaces a failed chart read without inventing series", async () => {
    renderChart({
      client: makeClient(new Error("paper chart failed: 403")),
    });

    await screen.findByTestId("paper-chart-unavailable");
    expect(screen.getByTestId("paper-chart-unavailable").textContent).toMatch(
      /paper chart failed: 403/i,
    );
    expect(screen.queryByTestId("paper-pnl-chart-svg")).toBeNull();
  });

  it("does not mount or fetch when the pack is not armed", async () => {
    const client = makeClient(fixtureChart());
    const { container } = render(
      <PaperPnlPositionChart client={client} armed={false} />,
    );
    expect(container.firstChild).toBeNull();
    expect(client.getChart).not.toHaveBeenCalled();
  });

  it("refetches when refreshKey changes after arm", async () => {
    const client = makeClient(fixtureChart());
    const view = render(
      <PaperPnlPositionChart client={client} armed={true} refreshKey={0} />,
    );
    await screen.findByTestId("paper-pnl-chart-svg");
    expect(client.getChart).toHaveBeenCalledTimes(1);

    view.rerender(
      <PaperPnlPositionChart client={client} armed={true} refreshKey={1} />,
    );
    await waitFor(() => {
      expect(client.getChart).toHaveBeenCalledTimes(2);
    });
  });
});
