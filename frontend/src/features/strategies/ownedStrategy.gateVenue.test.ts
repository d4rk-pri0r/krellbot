/**
 * Guided owned-strategy markets admit paper venue id `gate`.
 */
import { describe, expect, it } from "vitest";
import {
  GATE_PAPER_WAVE_PAIR,
  buildOwnedStrategyPack,
  seedOwnedStrategyForm,
  seedOwnedStrategyPack,
} from "./ownedStrategy";

describe("owned strategy gate paper venue", () => {
  it("accepts a BTC-USDT pack on gate", () => {
    const pack = buildOwnedStrategyPack(
      {
        ...seedOwnedStrategyForm(),
        venue: "gate",
        pair: GATE_PAPER_WAVE_PAIR,
        secondPair: "",
      },
      seedOwnedStrategyPack("Gate paper wave"),
    );
    expect(pack?.markets).toEqual([{ venue: "gate", pair: "BTC-USDT" }]);
  });
});
