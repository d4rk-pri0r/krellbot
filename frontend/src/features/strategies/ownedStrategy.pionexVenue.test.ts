/**
 * Guided owned-strategy markets admit paper venue id `pionex`.
 */
import { describe, expect, it } from "vitest";
import {
  PIONEX_PAPER_WAVE_PAIR,
  buildOwnedStrategyPack,
  seedOwnedStrategyForm,
  seedOwnedStrategyPack,
} from "./ownedStrategy";

describe("owned strategy pionex paper venue", () => {
  it("accepts a BTC-USDT pack on pionex", () => {
    const pack = buildOwnedStrategyPack(
      {
        ...seedOwnedStrategyForm(),
        venue: "pionex",
        pair: PIONEX_PAPER_WAVE_PAIR,
        secondPair: "",
      },
      seedOwnedStrategyPack("Pionex paper wave"),
    );
    expect(pack?.markets).toEqual([{ venue: "pionex", pair: "BTC-USDT" }]);
  });
});
