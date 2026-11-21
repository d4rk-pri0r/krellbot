/**
 * Guided owned-strategy markets admit paper venue id `kucoin`.
 */
import { describe, expect, it } from "vitest";
import {
  KUCOIN_PAPER_WAVE_PAIR,
  buildOwnedStrategyPack,
  seedOwnedStrategyForm,
  seedOwnedStrategyPack,
} from "./ownedStrategy";

describe("owned strategy kucoin paper venue", () => {
  it("accepts a BTC-USDT pack on kucoin", () => {
    const pack = buildOwnedStrategyPack(
      {
        ...seedOwnedStrategyForm(),
        venue: "kucoin",
        pair: KUCOIN_PAPER_WAVE_PAIR,
        secondPair: "",
      },
      seedOwnedStrategyPack("KuCoin paper wave"),
    );
    expect(pack?.markets).toEqual([{ venue: "kucoin", pair: "BTC-USDT" }]);
  });
});
