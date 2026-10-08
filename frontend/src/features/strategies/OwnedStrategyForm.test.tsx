import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useState } from "react";
import { OwnedStrategyForm } from "./OwnedStrategyForm";
import {
  INDICATOR_NAME,
  readOwnedStrategy,
  seedOwnedStrategyForm,
  seedOwnedStrategyPack,
  validateOwnedStrategyField,
  type OwnedStrategyFormState,
} from "./ownedStrategy";
import type { Pack } from "./client";

afterEach(cleanup);

type HarnessProps = {
  initial: OwnedStrategyFormState;
  basePack: Pack;
  onApply(pack: Pack | null, problems: string[]): void;
};

// Mirrors how the Editor hosts the form: the parent owns the state.
function Harness({ initial, basePack, onApply }: HarnessProps): React.JSX.Element {
  const [state, setState] = useState(initial);
  return (
    <OwnedStrategyForm
      state={state}
      basePack={basePack}
      onStateChange={setState}
      onApply={onApply}
    />
  );
}

function setup(state: OwnedStrategyFormState = seedOwnedStrategyForm()) {
  const onApply = vi.fn();
  // The Editor always pairs a form state with the pack built from that same
  // state (see handleStartOwnedStrategy), so mirror that alignment here.
  const basePack = seedOwnedStrategyPack(state.name);
  const aligned = { ...state, id: basePack.id as string };
  render(
    <Harness initial={aligned} basePack={basePack} onApply={onApply} />,
  );
  return { onApply, basePack, state: aligned };
}

describe("OwnedStrategyForm", () => {
  it("renders every supported field", () => {
    setup();
    for (const label of [
      /strategy name/i,
      /strategy id/i,
      /kraken pair/i,
      /average length/i,
      /max account percent/i,
      /protective stop percent/i,
      /timeframe/i,
      /average type/i,
      /enter when/i,
      /exit when/i,
    ]) {
      expect(screen.getByLabelText(label)).toBeDefined();
    }
  });

  it("reports which pack fields each control owns", () => {
    setup();
    expect(screen.getByText(/one moving average of close/i)).toBeDefined();
    expect(screen.getByText(/paper-trading only/i)).toBeDefined();
  });

  it("edits length, entry and stop and emits a pack whose payload really changed", () => {
    const { onApply } = setup();
    fireEvent.change(screen.getByLabelText(/average length/i), {
      target: { value: "50" },
    });
    fireEvent.change(screen.getByLabelText(/enter when/i), {
      target: { value: "crosses_above" },
    });
    fireEvent.change(screen.getByLabelText(/exit when/i), {
      target: { value: "crosses_below" },
    });
    fireEvent.change(screen.getByLabelText(/protective stop percent/i), {
      target: { value: "2.5" },
    });

    const last = onApply.mock.calls.at(-1);
    expect(last).toBeDefined();
    const [pack, problems] = last as unknown as [
      Record<string, unknown>,
      string[],
    ];
    expect(problems).toEqual([]);
    expect(pack.indicators).toEqual({
      [INDICATOR_NAME]: { fn: "sma", src: "close", len: 50 },
    });
    expect(pack.entry).toEqual(["close", "crosses_above", INDICATOR_NAME]);
    expect(pack.exit).toEqual(["close", "crosses_below", INDICATOR_NAME]);
    expect(pack.risk).toEqual({
      max_account_pct: 25,
      stop: { type: "pct", pct: 2.5 },
    });
    expect(readOwnedStrategy(pack)).not.toBeNull();
  });

  it("switching to EMA changes the indicator fn", () => {
    const { onApply } = setup();
    fireEvent.change(screen.getByLabelText(/average type/i), {
      target: { value: "ema" },
    });
    const [pack] = onApply.mock.calls.at(-1) as unknown as [
      Record<string, unknown>,
      string[],
    ];
    expect(pack.indicators).toEqual({
      [INDICATOR_NAME]: { fn: "ema", src: "close", len: 20 },
    });
  });

  it("changing timeframe and pair changes the pack payload", () => {
    const { onApply } = setup();
    fireEvent.change(screen.getByLabelText(/timeframe/i), {
      target: { value: "1d" },
    });
    fireEvent.change(screen.getByLabelText(/kraken pair/i), {
      target: { value: "XETHZUSD" },
    });
    const [pack] = onApply.mock.calls.at(-1) as unknown as [
      Record<string, unknown>,
      string[],
    ];
    expect(pack.timeframe).toBe("1d");
    expect(pack.markets).toEqual([{ venue: "kraken", pair: "XETHZUSD" }]);
  });

  it("refuses to emit a pack for an invalid length and keeps reporting the problem", () => {
    const { onApply } = setup();
    fireEvent.change(screen.getByLabelText(/average length/i), {
      target: { value: "1" },
    });
    const [pack, problems] = onApply.mock.calls.at(-1) as unknown as [
      Record<string, unknown> | null,
      string[],
    ];
    expect(pack).toBeNull();
    expect(problems.join(" ")).toMatch(/between 2 and 599/);
    expect(
      screen.getByTestId("owned-strategy-form-problems").textContent,
    ).toMatch(/between 2 and 599/);

    // Recovering emits a valid pack again.
    fireEvent.change(screen.getByLabelText(/average length/i), {
      target: { value: "30" },
    });
    const [recovered, recoveredProblems] = onApply.mock.calls.at(-1) as unknown as [
      Record<string, unknown>,
      string[],
    ];
    expect(recoveredProblems).toEqual([]);
    expect(recovered.indicators).toEqual({
      [INDICATOR_NAME]: { fn: "sma", src: "close", len: 30 },
    });
  });

  it("refuses a non-numeric stop percent", () => {
    const { onApply } = setup();
    fireEvent.change(screen.getByLabelText(/protective stop percent/i), {
      target: { value: "abc" },
    });
    const [pack, problems] = onApply.mock.calls.at(-1) as unknown as [
      Record<string, unknown> | null,
      string[],
    ];
    expect(pack).toBeNull();
    expect(problems.join(" ")).toMatch(/stop percent/i);
  });

  it("reflects a rename in the emitted pack label", () => {
    const { onApply } = setup();
    fireEvent.change(screen.getByLabelText(/strategy name/i), {
      target: { value: "Renamed" },
    });
    const [pack, problems] = onApply.mock.calls.at(-1) as unknown as [
      Record<string, unknown>,
      string[],
    ];
    expect(problems).toEqual([]);
    expect(pack.label).toBe("Renamed");
  });

  it("keeps the base pack's id and author so Save edits the same strategy", () => {
    const { onApply, basePack } = setup();
    fireEvent.change(screen.getByLabelText(/max account percent/i), {
      target: { value: "60" },
    });
    const [pack] = onApply.mock.calls.at(-1) as unknown as [
      Record<string, unknown>,
      string[],
    ];
    expect(pack.id).toBe(basePack.id);
    expect(pack.author).toBe(basePack.author);
    expect(validateOwnedStrategyField("id", pack.id as string)).toBeUndefined();
  });
});
