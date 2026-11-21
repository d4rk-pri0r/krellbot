/**
 * M14.7: guided owned-strategy markets admit paper venue id `binance`.
 */
import { describe, expect, it } from "vitest";
import {
  BINANCE_PAPER_WAVE_PAIR,
  VENUES,
  buildOwnedStrategyPack,
  seedOwnedStrategyForm,
  seedOwnedStrategyPack,
} from "./ownedStrategy";

describe("owned strategy binance paper venue", () => {
  it("lists binance among paper venues and accepts BTCUSDT packs", () => {
    expect(VENUES).toEqual(["kraken", "coinbase", "binance", "gate", "pionex", "kucoin"]);
    expect((VENUES as readonly string[]).includes("binance")).toBe(true);
    expect(BINANCE_PAPER_WAVE_PAIR).toBe("BTCUSDT");

    const pack = buildOwnedStrategyPack(
      {
        ...seedOwnedStrategyForm(),
        venue: "binance",
        pair: BINANCE_PAPER_WAVE_PAIR,
        secondPair: "",
      },
      seedOwnedStrategyPack("Binance paper wave"),
    );
    expect(pack?.markets).toEqual([{ venue: "binance", pair: "BTCUSDT" }]);
  });
});
