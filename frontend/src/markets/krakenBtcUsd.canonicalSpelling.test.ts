import { describe, expect, it } from "vitest";
import { seedOwnedStrategyForm, validateOwnedStrategyField } from "../features/strategies/ownedStrategy";
import {
  KRAKEN_BTC_USD_DISPLAY,
  KRAKEN_BTC_USD_VENUE_SYMBOL,
  KRAKEN_WAVE_PAIR_OPTIONS,
  isKrakenWavePairSymbol,
  krakenWavePairLabel,
} from "./krakenBtcUsd";

/**
 * Pins one canonical Kraken BTC/USD spelling across defaults and the
 * constrained picker — no BTC/USD, BTCUSD, XBTUSD, or XBT/USD as the
 * stored venue symbol.
 */
describe("kraken BTC/USD canonical spelling", () => {
  it("exposes one display label and one stored venue symbol", () => {
    expect(KRAKEN_BTC_USD_DISPLAY).toBe("BTC/USD");
    expect(KRAKEN_BTC_USD_VENUE_SYMBOL).toBe("XXBTZUSD");
    expect(KRAKEN_WAVE_PAIR_OPTIONS).toEqual([
      { venueSymbol: "XXBTZUSD", display: "BTC/USD" },
    ]);
  });

  it("rejects the five alternate spellings as stored venue symbols", () => {
    for (const spelling of ["BTC/USD", "BTCUSD", "XBTUSD", "XBT/USD", "btc-usd"]) {
      expect(isKrakenWavePairSymbol(spelling)).toBe(false);
      expect(validateOwnedStrategyField("pair", spelling)).toMatch(/XXBTZUSD/);
    }
    expect(isKrakenWavePairSymbol("XXBTZUSD")).toBe(true);
    expect(validateOwnedStrategyField("pair", "XXBTZUSD")).toBeUndefined();
  });

  it("seeds the owned-strategy form with the stored venue symbol", () => {
    expect(seedOwnedStrategyForm().pair).toBe(KRAKEN_BTC_USD_VENUE_SYMBOL);
  });

  it("labels the picker with display plus stored symbol", () => {
    expect(krakenWavePairLabel("XXBTZUSD")).toBe("BTC/USD (XXBTZUSD)");
  });
});
