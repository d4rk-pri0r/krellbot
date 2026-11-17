import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ModePackPicker } from "./ModePackPicker";
import type { ModePackCatalogue } from "./modePackClient";

afterEach(() => {
  cleanup();
});

const catalogue: ModePackCatalogue = {
  schema_version: "1",
  modes: [
    {
      id: "mode-dca",
      label: "DCA",
      description: "Built-in DCA trading mode. no profit or return claim.",
      pack: {
        id: "mode-dca",
        timeframe: "1d",
        indicators: { anchor: { fn: "sma", src: "close", len: 2 } },
        entry: ["anchor", ">", 0],
        exit: ["close", "<=", 0],
        mode: { kind: "dca" },
      },
    },
    {
      id: "mode-grid",
      label: "Grid",
      description: "Built-in Grid trading mode. no profit or return claim.",
      pack: {
        id: "mode-grid",
        timeframe: "1h",
        indicators: {
          band_high: { fn: "highest", src: "close", len: 20 },
          band_low: { fn: "lowest", src: "close", len: 20 },
        },
        entry: ["close", "<=", "band_low"],
        exit: ["close", ">=", "band_high"],
        mode: { kind: "grid", levels: 5 },
      },
    },
    {
      id: "mode-rebalance",
      label: "Rebalance",
      description: "Built-in Rebalance trading mode. no profit or return claim.",
      pack: {
        id: "mode-rebalance",
        timeframe: "1d",
        indicators: { sma20: { fn: "sma", src: "close", len: 20 } },
        entry: ["close", ">", "sma20"],
        exit: ["close", "<", "sma20"],
        mode: {
          kind: "rebalance",
          threshold_pct: 5,
          targets: [
            { symbol: "BTC", weight_pct: 60 },
            { symbol: "USD", weight_pct: 40 },
          ],
        },
      },
    },
  ],
};

describe("ModePackPicker", () => {
  it("lists DCA, grid, and rebalance and picks a real pack", async () => {
    const onPick = vi.fn();
    render(
      <ModePackPicker
        onPick={onPick}
        loadModes={() => Promise.resolve(catalogue)}
      />,
    );
    expect(await screen.findByTestId("studio-mode-pack-mode-dca")).toBeTruthy();
    expect(screen.getByTestId("studio-mode-pack-mode-grid")).toBeTruthy();
    expect(screen.getByTestId("studio-mode-pack-mode-rebalance")).toBeTruthy();
    fireEvent.click(screen.getByTestId("studio-mode-pack-mode-dca"));
    expect(onPick).toHaveBeenCalledTimes(1);
    expect(onPick.mock.calls[0]?.[0]?.id).toBe("mode-dca");
    expect(onPick.mock.calls[0]?.[0]?.mode).toEqual({ kind: "dca" });
  });

  it("surfaces load failures honestly", async () => {
    render(
      <ModePackPicker
        onPick={() => {}}
        loadModes={() => Promise.reject(new Error("offline"))}
      />,
    );
    expect(
      (await screen.findByTestId("studio-mode-pack-error")).textContent,
    ).toContain("offline");
  });
});
