/**
 * Guided owned-strategy markets admit paper venue id `okx`.
 */
import { describe, expect, it } from "vitest";
import {
  OKX_PAPER_WAVE_PAIR,
  VENUES,
  buildOwnedStrategyPack,
  seedOwnedStrategyForm,
  seedOwnedStrategyPack,
} from "./ownedStrategy";

describe("owned strategy okx paper venue", () => {
  it("lists okx among paper venues and accepts BTC-USDT packs", () => {
    expect(VENUES).toContain("okx");
    expect(OKX_PAPER_WAVE_PAIR).toBe("BTC-USDT");

    const pack = buildOwnedStrategyPack(
      {
        ...seedOwnedStrategyForm(),
        venue: "okx",
        pair: OKX_PAPER_WAVE_PAIR,
        secondPair: "",
      },
      seedOwnedStrategyPack("OKX paper wave"),
    );
    expect(pack?.markets).toEqual([{ venue: "okx", pair: "BTC-USDT" }]);
  });
});
