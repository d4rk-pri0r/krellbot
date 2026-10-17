import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import { StudioNodeInspector } from "./StudioNodeInspector";

afterEach(cleanup);

const INVALID_LENGTH_INPUTS = ["", "1", "-1", "3.5", "601"];

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

describe("StudioNodeInspector", () => {
  it("renders the indicator length input bound to the indicator's len", () => {
    const onChange = vi.fn();
    render(
      <StudioNodeInspector
        nodeId="sma2"
        pack={makePack()}
        onChange={onChange}
      />,
    );
    const input = screen.getByTestId("studio-indicator-len") as HTMLInputElement;
    expect(input.value).toBe("2");
    expect(screen.getByText(/indicator length/i)).toBeDefined();
  });

  it("calls onChange with a NEW pack object whose indicator len changes", () => {
    const onChange = vi.fn();
    const pack = makePack();
    render(
      <StudioNodeInspector nodeId="sma2" pack={pack} onChange={onChange} />,
    );
    const input = screen.getByTestId("studio-indicator-len") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "20" } });
    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0] as Record<string, unknown>;
    expect(next).not.toBe(pack);
    const indicators = next.indicators as Record<string, Record<string, unknown>>;
    expect(indicators.sma2.len).toBe(20);
    // untouched indicator stays the same value
    expect(indicators.sma20.len).toBe(20);
  });

  it("does not mutate the original pack", () => {
    const onChange = vi.fn();
    const pack = makePack();
    render(
      <StudioNodeInspector nodeId="sma2" pack={pack} onChange={onChange} />,
    );
    const input = screen.getByTestId("studio-indicator-len") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "9" } });
    expect((pack.indicators as Record<string, Record<string, unknown>>).sma2.len).toBe(2);
  });

  it("renders nothing when the node is not an indicator", () => {
    const onChange = vi.fn();
    render(
      <StudioNodeInspector nodeId="entry" pack={makePack()} onChange={onChange} />,
    );
    expect(screen.queryByTestId("studio-indicator-len")).toBeNull();
  });

  describe("invalid length input", () => {
    beforeEach(() => {
      vi.restoreAllMocks();
    });

    it.each(INVALID_LENGTH_INPUTS)(
      "rejects %j without calling onChange and keeps the pack untouched",
      (invalidValue) => {
        const onChange = vi.fn();
        const pack = makePack();
        render(
          <StudioNodeInspector nodeId="sma2" pack={pack} onChange={onChange} />,
        );
        const input = screen.getByTestId("studio-indicator-len") as HTMLInputElement;
        fireEvent.change(input, { target: { value: invalidValue } });
        expect(onChange).not.toHaveBeenCalled();
        expect(pack.indicators).toEqual(makePack().indicators);
      },
    );

    it("rejects a nonnumber (the browser reports it as the empty value) without calling onChange", () => {
      const onChange = vi.fn();
      const pack = makePack();
      render(
        <StudioNodeInspector nodeId="sma2" pack={pack} onChange={onChange} />,
      );
      const input = screen.getByTestId("studio-indicator-len") as HTMLInputElement;
      fireEvent.change(input, { target: { value: "abc" } });
      expect(onChange).not.toHaveBeenCalled();
      expect(pack.indicators).toEqual(makePack().indicators);
    });

    it.each([...INVALID_LENGTH_INPUTS, "abc"])(
      "shows a field error explaining the accepted whole-number range for %j",
      (invalidValue) => {
        const onChange = vi.fn();
        render(
          <StudioNodeInspector nodeId="sma2" pack={makePack()} onChange={onChange} />,
        );
        const input = screen.getByTestId("studio-indicator-len") as HTMLInputElement;
        fireEvent.change(input, { target: { value: invalidValue } });
        expect(
          screen.getByText(/whole number between 2 and 600/i),
        ).toBeDefined();
      },
    );

    it("clears the error and emits exactly one fresh pack after correcting to 20", () => {
      const onChange = vi.fn();
      const pack = makePack();
      render(
        <StudioNodeInspector nodeId="sma2" pack={pack} onChange={onChange} />,
      );
      const input = screen.getByTestId("studio-indicator-len") as HTMLInputElement;
      for (const invalidValue of INVALID_LENGTH_INPUTS) {
        fireEvent.change(input, { target: { value: invalidValue } });
      }
      expect(onChange).not.toHaveBeenCalled();
      expect(screen.getByText(/whole number between 2 and 600/i)).toBeDefined();

      fireEvent.change(input, { target: { value: "20" } });
      expect(
        screen.queryByText(/whole number between 2 and 600/i),
      ).toBeNull();
      expect(onChange).toHaveBeenCalledTimes(1);
      const next = onChange.mock.calls[0][0] as Record<string, unknown>;
      expect(next).not.toBe(pack);
      const indicators = next.indicators as Record<string, Record<string, unknown>>;
      expect(indicators.sma2.len).toBe(20);
      expect(indicators.sma20.len).toBe(20);
      expect(indicators.sma2.src).toBe("close");
      expect(pack.indicators).toEqual(makePack().indicators);
    });
  });
});