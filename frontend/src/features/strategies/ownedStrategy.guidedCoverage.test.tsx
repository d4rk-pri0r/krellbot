/**
 * Expanded guided / code-pack coverage (M6.4): remaining indicators, ATR
 * stops, all/any confirm nesting, multi-market Coinbase-capable packs, and
 * validate-before-arm preserved for packs the form authors.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Editor, type StrategyClient } from "./Editor";
import {
  INDICATOR_NAME,
  buildOwnedStrategyPack,
  readOwnedStrategy,
  seedOwnedStrategyForm,
  seedOwnedStrategyPack,
  type OwnedStrategyFormState,
} from "./ownedStrategy";
import type { Pack } from "./client";

afterEach(cleanup);

function makeClient(overrides: Partial<StrategyClient> = {}): StrategyClient {
  return {
    create: vi.fn().mockResolvedValue({
      revision_id: "rev-create",
      state: "draft",
      pack: {},
      errors: [],
    }),
    edit: vi.fn().mockImplementation(
      async (parentRevisionId: string, pack: Record<string, unknown>) => ({
        revision_id: "rev-edit",
        parent_revision_id: parentRevisionId,
        state: "draft",
        pack,
        errors: [],
      }),
    ),
    validate: vi.fn().mockResolvedValue({
      revision_id: "rev-1",
      state: "validated",
      pack: {},
      errors: [],
    }),
    arm: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

describe("guided code-pack coverage expansion", () => {
  it("builds a wma pack with ATR stop, all nesting, and coinbase plus kraken markets", () => {
    const seeded = seedOwnedStrategyPack("Coverage plan");
    const state: OwnedStrategyFormState = {
      ...seedOwnedStrategyForm(),
      id: seeded.id as string,
      name: "Coverage plan",
      kind: "wma",
      length: "20",
      stopKind: "atr",
      atrLen: "14",
      atrMult: "2",
      entryNesting: "all",
      entryConfirmComparison: ">",
      entryConfirmThreshold: "25000",
      venue: "coinbase",
      pair: "BTC-USD",
      secondVenue: "kraken",
      secondPair: "XXBTZUSD",
    };
    const pack = buildOwnedStrategyPack(state, seeded) as Pack;
    expect(pack.indicators).toEqual({
      [INDICATOR_NAME]: { fn: "wma", src: "close", len: 20 },
    });
    expect(pack.risk).toEqual({
      max_account_pct: 25,
      stop: { type: "atr", len: 14, mult: 2 },
    });
    expect(pack.entry).toEqual({
      all: [
        ["close", ">", INDICATOR_NAME],
        ["close", ">", 25000],
      ],
    });
    expect(pack.markets).toEqual([
      { venue: "coinbase", pair: "BTC-USD" },
      { venue: "kraken", pair: "XXBTZUSD" },
    ]);
    expect(readOwnedStrategy(pack)).not.toBeNull();
  });

  it("keeps arm disabled until validate succeeds for an expanded guided pack", async () => {
    const expanded = buildOwnedStrategyPack(
      {
        ...seedOwnedStrategyForm(),
        id: "coverage-arm",
        name: "Coverage arm",
        kind: "hma",
        stopKind: "atr",
        atrLen: "14",
        atrMult: "1.5",
        venue: "coinbase",
        pair: "ETH-USD",
        entryNesting: "any",
        entryConfirmThreshold: "10",
      },
      {},
    ) as Pack;
    const bytes = JSON.stringify(expanded, null, 2);
    const validate = vi.fn().mockResolvedValue({
      revision_id: "rev-1",
      state: "validated",
      pack: expanded,
      errors: [],
    });
    const arm = vi.fn().mockResolvedValue(undefined);
    const onOpenInRun = vi.fn();
    const client = makeClient({ validate, arm });

    render(
      <Editor
        client={client}
        onOpenInRun={onOpenInRun}
        initial={{
          revision_id: "rev-1",
          state: "draft",
          bytes,
        }}
      />,
    );

    const openRun = screen.getByTestId("editor-open-in-run") as HTMLButtonElement;
    expect(openRun.disabled).toBe(true);
    expect(screen.getByTestId("owned-strategy-form")).toBeDefined();
    expect((screen.getByLabelText(/indicator type/i) as HTMLSelectElement).value).toBe(
      "hma",
    );
    expect((screen.getByLabelText(/^protective stop$/i) as HTMLSelectElement).value).toBe(
      "atr",
    );
    expect(
      (document.getElementById("kbot-owned-strategy-venue") as HTMLSelectElement)
        .value,
    ).toBe("coinbase");

    fireEvent.click(screen.getByRole("button", { name: /validate/i }));
    await waitFor(() => {
      expect(validate).toHaveBeenCalled();
      expect(
        (screen.getByTestId("editor-open-in-run") as HTMLButtonElement).disabled,
      ).toBe(false);
    });

    fireEvent.click(screen.getByTestId("editor-open-in-run"));
    expect(onOpenInRun).toHaveBeenCalledWith("rev-1");
    expect(arm).not.toHaveBeenCalled();
  });

  it("keeps Open in Run disabled for an expanded pack that is only saved as draft", async () => {
    const expanded = buildOwnedStrategyPack(
      {
        ...seedOwnedStrategyForm(),
        id: "coverage-draft",
        kind: "stdev",
        stopKind: "atr",
        atrLen: "10",
        atrMult: "3",
      },
      {},
    ) as Pack;
    const client = makeClient({
      validate: vi.fn().mockResolvedValue({
        revision_id: "rev-1",
        state: "draft",
        pack: expanded,
        errors: [],
      }),
    });
    render(
      <Editor
        client={client}
        initial={{
          revision_id: "rev-1",
          state: "draft",
          bytes: JSON.stringify(expanded, null, 2),
        }}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /validate/i }));
    await waitFor(() => {
      expect(client.validate).toHaveBeenCalled();
    });
    expect(
      (screen.getByTestId("editor-open-in-run") as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(client.arm).not.toHaveBeenCalled();
  });
});
