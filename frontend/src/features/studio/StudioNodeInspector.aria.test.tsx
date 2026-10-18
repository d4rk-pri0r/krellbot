/**
 * StudioNodeInspector aria-invalid / aria-describedby honesty slice.
 *
 * A keyboard-only / screen-reader operator editing an indicator length
 * must hear the field announce its error state truthfully: while the
 * parsed value is outside 2..600 (or empty/non-integer) the input
 * carries ``aria-invalid="true"`` and its ``aria-describedby`` points
 * at the live per-field error node; once the value is valid the
 * announcement returns to the persistent helper hint and the error
 * node is removed.
 *
 * Every ``aria-describedby`` value asserted here is also resolved
 * against the real document so the wiring can never reference a
 * detached id.
 *
 * RED on the base where the input carried neither attribute and the
 * error node was never referenced.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { StudioNodeInspector } from "./StudioNodeInspector";

afterEach(cleanup);

const ERROR_ID = "studio-node-inspector-len-error";
const HINT_ID = "studio-indicator-len-hint";

function makePack() {
  return {
    id: "ns20-e2e",
    timeframe: "1h",
    indicators: {
      sma2: { fn: "sma", src: "close", len: 2 },
      sma20: { fn: "sma", src: "close", len: 20 },
    },
    entry: ["close", "crosses_above", "sma2"],
    exit: ["close", "crosses_below", "sma2"],
  };
}

function lenInput(): HTMLInputElement {
  return screen.getByTestId("studio-indicator-len") as HTMLInputElement;
}

function resolveDescribedBy(input: HTMLInputElement): HTMLElement | null {
  const ids = (input.getAttribute("aria-describedby") ?? "").trim();
  if (ids === "") {
    return null;
  }
  return ids
    .split(/\s+/)
    .map((id) => input.ownerDocument.getElementById(id))
    .find((element): element is HTMLElement => element !== null) ?? null;
}

describe("StudioNodeInspector aria honesty — mounted valid state", () => {
  it("carries aria-invalid=false and describes the persistent helper hint", () => {
    render(
      <StudioNodeInspector nodeId="sma2" pack={makePack()} onChange={vi.fn()} />,
    );
    const input = lenInput();
    expect(input.getAttribute("aria-invalid")).toBe("false");
    expect(input.getAttribute("aria-describedby")).toBe(HINT_ID);
  });

  it("renders the always-present helper hint element with the range text", () => {
    render(
      <StudioNodeInspector nodeId="sma2" pack={makePack()} onChange={vi.fn()} />,
    );
    const hint = document.getElementById(HINT_ID);
    expect(hint).not.toBeNull();
    expect(hint?.textContent).toBe("Whole number between 2 and 600");
  });

  it("describes a real mounted element while the draft is valid", () => {
    render(
      <StudioNodeInspector nodeId="sma2" pack={makePack()} onChange={vi.fn()} />,
    );
    const input = lenInput();
    const described = resolveDescribedBy(input);
    expect(described).not.toBeNull();
    expect(described?.getAttribute("id")).toBe(HINT_ID);
    expect(
      screen.queryByTestId("studio-node-inspector-len-error"),
    ).toBeNull();
  });
});

describe("StudioNodeInspector aria honesty — invalid state", () => {
  it.each(["", "1", "-1", "3.5", "601", "abc"])(
    "marks the input aria-invalid=true and points describedby at the error node for %j",
    (invalidValue) => {
      render(
        <StudioNodeInspector
          nodeId="sma2"
          pack={makePack()}
          onChange={vi.fn()}
        />,
      );
      const input = lenInput();
      fireEvent.change(input, { target: { value: invalidValue } });
      expect(input.getAttribute("aria-invalid")).toBe("true");
      expect(input.getAttribute("aria-describedby")).toBe(ERROR_ID);
      const described = resolveDescribedBy(input);
      expect(described).not.toBeNull();
      expect(described?.getAttribute("id")).toBe(ERROR_ID);
      expect(described?.getAttribute("role")).toBe("alert");
      expect(described?.textContent).toBe("Enter a whole number between 2 and 600.");
    },
  );

  it("keeps the helper hint mounted while the error is announced", () => {
    render(
      <StudioNodeInspector nodeId="sma2" pack={makePack()} onChange={vi.fn()} />,
    );
    fireEvent.change(lenInput(), { target: { value: "601" } });
    expect(document.getElementById(HINT_ID)).not.toBeNull();
  });

  it("keeps the visible Apply affordance disabled while invalid", () => {
    render(
      <StudioNodeInspector nodeId="sma2" pack={makePack()} onChange={vi.fn()} />,
    );
    const input = lenInput();
    fireEvent.change(input, { target: { value: "1" } });
    const apply = screen.getByTestId(
      "studio-node-inspector-apply",
    ) as HTMLButtonElement;
    expect(apply.disabled).toBe(true);
  });
});

describe("StudioNodeInspector aria honesty — recovery to valid", () => {
  it("clears aria-invalid and returns describedby to the helper after fixing the value", () => {
    render(
      <StudioNodeInspector nodeId="sma2" pack={makePack()} onChange={vi.fn()} />,
    );
    const input = lenInput();
    fireEvent.change(input, { target: { value: "1" } });
    expect(input.getAttribute("aria-invalid")).toBe("true");

    fireEvent.change(input, { target: { value: "14" } });
    expect(input.getAttribute("aria-invalid")).toBe("false");
    expect(input.getAttribute("aria-describedby")).toBe(HINT_ID);
    const described = resolveDescribedBy(input);
    expect(described?.getAttribute("id")).toBe(HINT_ID);
    expect(
      screen.queryByTestId("studio-node-inspector-len-error"),
    ).toBeNull();
  });

  it("re-enables the visible Apply affordance after the value is fixed", () => {
    render(
      <StudioNodeInspector nodeId="sma2" pack={makePack()} onChange={vi.fn()} />,
    );
    const input = lenInput();
    fireEvent.change(input, { target: { value: "1" } });
    fireEvent.change(input, { target: { value: "14" } });
    const apply = screen.getByTestId(
      "studio-node-inspector-apply",
    ) as HTMLButtonElement;
    expect(apply.disabled).toBe(false);
  });

  it("keeps the existing status text summary and export control alongside the wiring", () => {
    render(
      <StudioNodeInspector nodeId="sma2" pack={makePack()} onChange={vi.fn()} />,
    );
    fireEvent.change(lenInput(), { target: { value: "1" } });
    const status = screen.getByTestId("studio-node-inspector-status");
    expect(status.textContent).toBe("Invalid");
    expect(
      screen.getByTestId("studio-indicator-spec-export"),
    ).toBeDefined();
  });
});
