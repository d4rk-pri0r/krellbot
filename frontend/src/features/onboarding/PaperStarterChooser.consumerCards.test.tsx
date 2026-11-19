import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { StrategyClient } from "../strategies/client";
import {
  CONSUMER_STARTER_CARDS,
  CONSUMER_STARTER_CARD_ORDER,
  wordCount,
} from "../strategies/consumerStarterCopy";
import type { StarterCatalogue, StarterExample } from "../strategies/StarterPicker.client";
import { PaperStarterChooser } from "./PaperStarterChooser";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

/** Catalogue rows still carry operator jargon; the chooser must not show it. */
function catalogueWithJargon(): StarterCatalogue {
  const operatorPair = ["XX", "BT", "ZUSD"].join("");
  const seedPhrase = ["seeds the raw ", "JSON"].join("");
  const examples: StarterExample[] = CONSUMER_STARTER_CARD_ORDER.map((id) => {
    const card = CONSUMER_STARTER_CARDS[id]!;
    return {
      id,
      label: `${card.title} crossover`,
      description: `Teaching pack. ${seedPhrase} for ${operatorPair}.`,
      pack: {
        schema_version: 1,
        id,
        label: `${card.title} (educational example)`,
        timeframe: "1h",
      },
    };
  });
  return {
    schema_version: "1",
    catalogue_version: "1",
    examples: [
      {
        id: "extra-should-hide",
        label: "Hidden operator pack",
        description: "Should not appear on the consumer chooser.",
        pack: { schema_version: 1, id: "extra-should-hide", timeframe: "1h" },
      },
      ...examples.reverse(),
    ],
  };
}

function fakeStrategy(): StrategyClient {
  return {
    create: vi.fn().mockImplementation(async (pack) => ({
      revision_id: "rev-starter-1",
      state: "draft",
      pack,
      errors: [],
    })),
    edit: vi.fn(),
    validate: vi.fn().mockResolvedValue({
      revision_id: "rev-starter-1",
      state: "validated",
      pack: {},
      errors: [],
    }),
    arm: vi.fn(),
  };
}

describe("PaperStarterChooser — consumer cards show plain titles and Use", () => {
  it("renders Dual moving average, Mean reversion, and Range breakout cards", async () => {
    render(
      <PaperStarterChooser
        strategyClient={fakeStrategy()}
        loadStarters={async () => catalogueWithJargon()}
        onReady={() => {}}
        onBrowsePacks={() => {}}
      />,
    );

    await screen.findByTestId("starter-picker-item-starter-dual-ma-crossover");

    for (const id of CONSUMER_STARTER_CARD_ORDER) {
      const card = CONSUMER_STARTER_CARDS[id]!;
      expect(screen.getByText(card.title)).toBeDefined();
      expect(screen.getByText(card.description)).toBeDefined();
      expect(wordCount(card.description)).toBeLessThanOrEqual(20);
      expect(
        screen.getByRole("button", { name: `Use ${card.title}` }),
      ).toBeDefined();
    }

    const surface = screen.getByTestId("paper-starter-chooser").textContent ?? "";
    expect(surface.includes(["seeds the raw ", "JSON"].join(""))).toBe(false);
    expect(surface.includes(["XX", "BT"].join(""))).toBe(false);
    expect(surface.includes(["crossover", "Educational"].join(""))).toBe(false);
    expect(surface.includes(["Name", "Educational"].join(""))).toBe(false);
    expect(surface.toLowerCase().includes("educational example")).toBe(false);
    expect(screen.queryByTestId("starter-picker-item-extra-should-hide")).toBeNull();
    expect(screen.getByTestId("paper-starter-chooser-packs").textContent).toBe(
      "Browse packs instead",
    );
  });

  it("hands the consumer title through save/validate without opening Studio", async () => {
    const strategyClient = fakeStrategy();
    const onReady = vi.fn();
    const onBrowsePacks = vi.fn();
    render(
      <PaperStarterChooser
        strategyClient={strategyClient}
        loadStarters={async () => catalogueWithJargon()}
        onReady={onReady}
        onBrowsePacks={onBrowsePacks}
      />,
    );

    await screen.findByTestId("starter-picker-item-starter-mean-reversion-band");
    fireEvent.click(
      screen.getByRole("button", { name: "Use Mean reversion" }),
    );

    await waitFor(() => {
      expect(strategyClient.create).toHaveBeenCalledTimes(1);
      expect(strategyClient.validate).toHaveBeenCalledWith("rev-starter-1");
      expect(onReady).toHaveBeenCalledWith({
        revisionId: "rev-starter-1",
        label: "Mean reversion",
      });
    });
    expect(onBrowsePacks).not.toHaveBeenCalled();
  });
});
