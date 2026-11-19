import { describe, expect, it } from "vitest";
import {
  CONSUMER_STARTER_CARDS,
  CONSUMER_STARTER_CARD_ORDER,
  consumerCardForExample,
  orderConsumerStarterExamples,
  plainStarterDescription,
  plainStarterLabel,
  wordCount,
} from "./consumerStarterCopy";

describe("consumer starter card copy stays plain English", () => {
  it("ships the three plan titles in stable order", () => {
    expect(CONSUMER_STARTER_CARD_ORDER).toEqual([
      "starter-dual-ma-crossover",
      "starter-mean-reversion-band",
      "starter-range-breakout",
    ]);
    expect(CONSUMER_STARTER_CARDS["starter-dual-ma-crossover"]?.title).toBe(
      "Dual moving average",
    );
    expect(CONSUMER_STARTER_CARDS["starter-mean-reversion-band"]?.title).toBe(
      "Mean reversion",
    );
    expect(CONSUMER_STARTER_CARDS["starter-range-breakout"]?.title).toBe(
      "Range breakout",
    );
  });

  it("keeps every consumer description at or under 20 words", () => {
    for (const id of CONSUMER_STARTER_CARD_ORDER) {
      const card = CONSUMER_STARTER_CARDS[id]!;
      expect(wordCount(card.description)).toBeLessThanOrEqual(20);
      expect(card.description.length).toBeGreaterThan(0);
    }
  });

  it("never embeds JSON seed jargon, pair codes, or Educational glue", () => {
    const blob = Object.values(CONSUMER_STARTER_CARDS)
      .map((card) => `${card.title} ${card.description}`)
      .join("\n");
    const seedPhrase = ["seeds the raw ", "JSON"].join("");
    const pairCode = ["XX", "BT"].join("");
    const glueTypo = ["crossover", "Educational"].join("");
    const nameGlue = ["Name", "Educational"].join("");
    expect(blob.includes(seedPhrase)).toBe(false);
    expect(blob.includes(pairCode)).toBe(false);
    expect(blob.includes(glueTypo)).toBe(false);
    expect(blob.includes(nameGlue)).toBe(false);
    expect(blob.toLowerCase().includes("educational example")).toBe(false);
  });
});

describe("consumer starter label cleanup avoids glued Educational typos", () => {
  it("strips educational suffixes without concatenating Educational", () => {
    const suffix = [" (educational ", "example)"].join("");
    expect(plainStarterLabel(`Dual MA crossover${suffix}`)).toBe(
      "Dual MA crossover",
    );
    const glued = ["Range breakout", "Educational"].join("");
    expect(plainStarterLabel(glued)).toBe(glued);
    expect(glued.includes(["Name", "Educational"].join(""))).toBe(false);
  });

  it("strips educational description prefixes only", () => {
    const prefix = ["Educational example", ". "].join("");
    expect(
      plainStarterDescription(
        `${prefix}Enters long when close is under a 20-bar SMA.`,
      ),
    ).toBe("Enters long when close is under a 20-bar SMA.");
  });

  it("maps known catalogue ids to consumer cards", () => {
    expect(
      consumerCardForExample({
        id: "starter-dual-ma-crossover",
        label: "Dual moving-average crossover",
        description: "Educational example. Technical jargon.",
      }),
    ).toEqual(CONSUMER_STARTER_CARDS["starter-dual-ma-crossover"]);
  });

  it("orders only known cards present in the catalogue", () => {
    const rows = orderConsumerStarterExamples([
      { id: "starter-range-breakout" },
      { id: "extra-ignored" },
      { id: "starter-dual-ma-crossover" },
    ]);
    expect(rows.map((row) => row.id)).toEqual([
      "starter-dual-ma-crossover",
      "starter-range-breakout",
    ]);
  });
});
