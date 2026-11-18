import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { StrategyClient } from "../strategies/client";
import type { StarterCatalogue, StarterExample } from "../strategies/StarterPicker.client";
import { PaperStarterChooser } from "./PaperStarterChooser";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const example: StarterExample = {
  id: "starter-dual-ma-crossover",
  label: "Dual moving-average crossover",
  description: "Educational example for paper.",
  pack: {
    schema_version: 1,
    id: "starter-dual-ma-crossover",
    label: "Dual MA crossover (educational example)",
    timeframe: "1h",
  },
};

const catalogue: StarterCatalogue = {
  schema_version: "1",
  catalogue_version: "1",
  examples: [example],
};

function fakeStrategy(over: Partial<StrategyClient> = {}): StrategyClient {
  return {
    create: vi.fn().mockResolvedValue({
      revision_id: "rev-starter-1",
      state: "draft",
      pack: example.pack,
      errors: [],
    }),
    edit: vi.fn(),
    validate: vi.fn().mockResolvedValue({
      revision_id: "rev-starter-1",
      state: "validated",
      pack: example.pack,
      errors: [],
    }),
    arm: vi.fn(),
    ...over,
  };
}

describe("PaperStarterChooser — starter pick reaches paper arm handoff", () => {
  it("creates and validates a starter then reports the revision id", async () => {
    const strategyClient = fakeStrategy();
    const onReady = vi.fn();
    render(
      <PaperStarterChooser
        strategyClient={strategyClient}
        loadStarters={async () => catalogue}
        onReady={onReady}
      />,
    );
    await screen.findByTestId("starter-picker-item-starter-dual-ma-crossover");
    fireEvent.click(screen.getByRole("button", { name: "Use Dual moving average" }));
    await waitFor(() => {
      expect(strategyClient.create).toHaveBeenCalledWith(example.pack);
      expect(strategyClient.validate).toHaveBeenCalledWith("rev-starter-1");
      expect(onReady).toHaveBeenCalledWith({
        revisionId: "rev-starter-1",
        label: "Dual moving average",
      });
    });
  });

  it("surfaces plain validation failures without calling onReady", async () => {
    const strategyClient = fakeStrategy({
      validate: vi.fn().mockResolvedValue({
        revision_id: "rev-starter-1",
        state: "draft",
        pack: example.pack,
        errors: [{ message: "pair required" }],
      }),
    });
    const onReady = vi.fn();
    render(
      <PaperStarterChooser
        strategyClient={strategyClient}
        loadStarters={async () => catalogue}
        onReady={onReady}
      />,
    );
    await screen.findByTestId("starter-picker-item-starter-dual-ma-crossover");
    fireEvent.click(screen.getByRole("button", { name: "Use Dual moving average" }));
    expect(
      (await screen.findByTestId("paper-starter-chooser-error")).textContent,
    ).toMatch(/pair required/i);
    expect(onReady).not.toHaveBeenCalled();
  });
});
