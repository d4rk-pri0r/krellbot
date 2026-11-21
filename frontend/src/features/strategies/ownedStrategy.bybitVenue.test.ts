/**
 * Guided owned-strategy markets admit paper venue id `bybit`.
 */
import { describe, expect, it } from "vitest";
import {
  BYBIT_PAPER_WAVE_PAIR,
  buildOwnedStrategyPack,
  seedOwnedStrategyForm,
  seedOwnedStrategyPack,
} from "./ownedStrategy";

describe("owned strategy bybit paper venue", () => {
  it("accepts a BTCUSDT pack on bybit", () => {
    const pack = buildOwnedStrategyPack(
      {
        ...seedOwnedStrategyForm(),
        venue: "bybit",
        pair: BYBIT_PAPER_WAVE_PAIR,
        secondPair: "",
      },
      seedOwnedStrategyPack("Bybit paper wave"),
    );
    expect(pack?.markets).toEqual([{ venue: "bybit", pair: "BTCUSDT" }]);
  });
});
