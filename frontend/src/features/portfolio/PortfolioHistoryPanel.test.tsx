import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PortfolioHistoryPanel } from "./PortfolioHistoryPanel";
import type { PortfolioClient, PortfolioHistory } from "./client";

/**
 * M4.4 — Portfolio history UI from ``GET /api/v1/portfolio/history``.
 *
 * Fakes implement ``PortfolioClient.getHistory``. No real venue/engine
 * lifecycle is started.
 */

function fixtureHistory(
  overrides: Partial<PortfolioHistory> = {},
): PortfolioHistory {
  return {
    schema_version: "1",
    equity: [
      { ts_ms: 2000, value: "999.6" },
      { ts_ms: 3000, value: "1019.12" },
    ],
    deployments: [
      {
        venue: "kraken",
        pair: "SUIUSD",
        pack_id: "trend-follow",
        mode: "paper",
        status: "active",
        starting_cash: "1000",
        fills_total: 2,
        first_ts_ms: 1000,
        last_ts_ms: 3000,
        last_pnl: "19.12",
        pnl: [
          { ts_ms: 2000, value: "-0.4" },
          { ts_ms: 3000, value: "19.12" },
        ],
      },
    ],
    ...overrides,
  };
}

function fakeClient(
  history: PortfolioHistory | Error,
): PortfolioClient {
  if (history instanceof Error) {
    return {
      getHistory: vi.fn().mockRejectedValue(history),
    };
  }
  return {
    getHistory: vi.fn().mockResolvedValue(history),
  };
}

describe("PortfolioHistoryPanel", () => {
  it("renders equity series and deployment cards from the history API", async () => {
    const client = fakeClient(fixtureHistory());
    render(<PortfolioHistoryPanel client={client} />);

    await screen.findByTestId("portfolio-equity-chart-svg");
    expect(client.getHistory).toHaveBeenCalledTimes(1);

    const line = screen.getByTestId("portfolio-equity-chart-line");
    expect(line.tagName).toBe("polyline");
    expect(
      (line.getAttribute("points") ?? "").split(" ").filter(Boolean).length,
    ).toBe(2);

    expect(screen.getByTestId("portfolio-history-count").textContent).toBe(
      "1 deployment",
    );
    const card = screen.getByTestId("portfolio-deployment-card");
    expect(card.textContent ?? "").toContain("SUIUSD");
    expect(card.textContent ?? "").toContain("trend-follow");
    expect(screen.getByTestId("portfolio-deployment-pnl").textContent).toContain(
      "19.12",
    );
  });

  it("shows empty equity and empty deployments without fabricating zeros", async () => {
    const client = fakeClient(
      fixtureHistory({ equity: [], deployments: [] }),
    );
    render(<PortfolioHistoryPanel client={client} />);

    await screen.findByTestId("portfolio-equity-unavailable");
    expect(
      screen.getByTestId("portfolio-equity-unavailable").textContent,
    ).toMatch(/unavailable/i);
    expect(screen.queryByTestId("portfolio-equity-chart-svg")).toBeNull();
    expect(screen.getByTestId("portfolio-deployments-empty").textContent).toMatch(
      /No journalled or armed deployments/i,
    );
    expect(screen.queryByTestId("portfolio-deployment-card")).toBeNull();
    expect(screen.getByTestId("portfolio-history-count").textContent).toBe(
      "0 deployments",
    );
  });

  it("lists a closed deployment without inventing last P&L", async () => {
    const client = fakeClient(
      fixtureHistory({
        equity: [],
        deployments: [
          {
            venue: "kraken",
            pair: "SUIUSD",
            pack_id: "retired-pack",
            mode: "paper",
            status: "closed",
            starting_cash: null,
            fills_total: 1,
            first_ts_ms: 1000,
            last_ts_ms: 2000,
            last_pnl: null,
            pnl: [],
          },
        ],
      }),
    );
    render(<PortfolioHistoryPanel client={client} />);

    await screen.findByTestId("portfolio-deployment-card");
    expect(
      screen.getByTestId("portfolio-deployment-pnl-absent").textContent,
    ).toMatch(/P&L unavailable/i);
    expect(screen.queryByTestId("portfolio-deployment-pnl")).toBeNull();
  });

  it("surfaces a failed history read", async () => {
    const client = fakeClient(new Error("portfolio history failed: 403"));
    render(<PortfolioHistoryPanel client={client} />);

    await screen.findByTestId("portfolio-history-unavailable");
    expect(
      screen.getByTestId("portfolio-history-unavailable").textContent,
    ).toMatch(/403/);
    expect(screen.queryByTestId("portfolio-equity-chart-svg")).toBeNull();
  });

  it("reloads when refreshKey changes", async () => {
    const client = fakeClient(fixtureHistory());
    const { rerender } = render(
      <PortfolioHistoryPanel client={client} refreshKey={0} />,
    );
    await screen.findByTestId("portfolio-equity-chart-svg");
    expect(client.getHistory).toHaveBeenCalledTimes(1);

    rerender(<PortfolioHistoryPanel client={client} refreshKey={1} />);
    await waitFor(() => {
      expect(client.getHistory).toHaveBeenCalledTimes(2);
    });
  });
});
