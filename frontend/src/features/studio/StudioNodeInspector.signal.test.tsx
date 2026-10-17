/**
 * StudioNodeInspector Signal presentation slice — KRELL-SIGNAL-20261010.
 *
 * Pins the readable Signal presentation of the mounted studio node
 * inspector: an inspector header (eyebrow, node id title + mono node id
 * badge, indicator-context label), a current-value display rendered as
 * an integer, a text status (never color-only), inline field-error
 * styling and a submit affordance that is disabled while the draft is
 * invalid — while preserving the strict 2..600 whole-number range, the
 * new-reference onChange invariant, the indicator-only mount guard
 * (entry/exit render null), the exact field-error message and the
 * min/max input attributes.
 *
 * The header/badge/value/status/apply assertions are RED on the flat
 * pre-signal inspector; the behavior guards prove the presentation
 * change adds no new validation or save path.
 *
 * TEST TRANSPORT NOTICE: these tests run the real component with an
 * in-memory fixture pack only. Nothing here qualifies a backend, pack
 * or graph state.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";
import { StudioNodeInspector } from "./StudioNodeInspector";

afterEach(cleanup);

const INVALID_LENGTH_INPUTS = ["", "1", "-1", "3.5", "601", "abc"];

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

describe("StudioNodeInspector signal slice — header presentation", () => {
  it("renders the inspector header with eyebrow, node id title and mono node id badge", () => {
    render(
      <StudioNodeInspector nodeId="sma2" pack={makePack()} onChange={vi.fn()} />,
    );
    const header = screen.getByTestId("studio-node-inspector-header");
    expect(header.textContent?.toLowerCase()).toContain("selected node");
    expect(screen.getByTestId("studio-node-inspector-title").textContent).toBe(
      "sma2",
    );
    const badge = screen.getByTestId("studio-node-inspector-node-id");
    expect(badge.textContent).toBe("sma2");
  });

  it("renders the indicator-context label from the pack spec fields", () => {
    render(
      <StudioNodeInspector nodeId="sma2" pack={makePack()} onChange={vi.fn()} />,
    );
    const context = screen.getByTestId("studio-node-inspector-context");
    expect(context.textContent?.toLowerCase()).toContain("indicator");
    expect(context.textContent).toContain("sma");
    expect(context.textContent).toContain("close");
  });

  it("renders the current value display as an integer", () => {
    render(
      <StudioNodeInspector nodeId="sma20" pack={makePack()} onChange={vi.fn()} />,
    );
    expect(screen.getByTestId("studio-node-inspector-value").textContent).toBe(
      "20",
    );
  });

  it("renders a text status that reads valid before any edit", () => {
    render(
      <StudioNodeInspector nodeId="sma2" pack={makePack()} onChange={vi.fn()} />,
    );
    const status = screen.getByTestId("studio-node-inspector-status");
    expect(status.textContent?.toLowerCase()).toContain("valid");
    expect(status.textContent?.toLowerCase()).not.toContain("invalid");
  });

  it("keeps the readable Indicator length label for the input field", () => {
    render(
      <StudioNodeInspector nodeId="sma2" pack={makePack()} onChange={vi.fn()} />,
    );
    expect(screen.getByText(/indicator length/i)).toBeDefined();
  });

  it("preserves the input type and min/max attributes as the range hint", () => {
    render(
      <StudioNodeInspector nodeId="sma2" pack={makePack()} onChange={vi.fn()} />,
    );
    const input = lenInput();
    expect(input.type).toBe("number");
    expect(input.getAttribute("min")).toBe("2");
    expect(input.getAttribute("max")).toBe("600");
  });
});

describe("StudioNodeInspector signal slice — mount guard", () => {
  it("renders nothing for an entry node", () => {
    render(
      <StudioNodeInspector nodeId="entry" pack={makePack()} onChange={vi.fn()} />,
    );
    expect(screen.queryByTestId("studio-node-inspector-header")).toBeNull();
    expect(screen.queryByTestId("studio-indicator-len")).toBeNull();
  });

  it("renders nothing for an exit node", () => {
    render(
      <StudioNodeInspector nodeId="exit" pack={makePack()} onChange={vi.fn()} />,
    );
    expect(screen.queryByTestId("studio-node-inspector-header")).toBeNull();
    expect(screen.queryByTestId("studio-indicator-len")).toBeNull();
  });
});

describe("StudioNodeInspector signal slice — valid input path", () => {
  it("updates onChange with a NEW pack reference on a valid whole number", () => {
    const onChange = vi.fn();
    const pack = makePack();
    render(
      <StudioNodeInspector nodeId="sma2" pack={pack} onChange={onChange} />,
    );
    fireEvent.change(lenInput(), { target: { value: "20" } });
    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0] as Record<string, unknown>;
    expect(next).not.toBe(pack);
    const indicators = next.indicators as Record<
      string,
      Record<string, unknown>
    >;
    expect(indicators.sma2.len).toBe(20);
    expect(indicators.sma20.len).toBe(20);
  });

  it("keeps the status valid after a valid edit", () => {
    render(
      <StudioNodeInspector nodeId="sma2" pack={makePack()} onChange={vi.fn()} />,
    );
    fireEvent.change(lenInput(), { target: { value: "20" } });
    const status = screen.getByTestId("studio-node-inspector-status");
    expect(status.textContent?.toLowerCase()).toContain("valid");
    expect(
      screen.queryByTestId("studio-node-inspector-len-error"),
    ).toBeNull();
  });
});

describe("StudioNodeInspector signal slice — invalid input path", () => {
  it.each(INVALID_LENGTH_INPUTS)(
    "shows the exact field error for %j and never reaches onChange",
    (invalidValue) => {
      const onChange = vi.fn();
      const pack = makePack();
      render(
        <StudioNodeInspector
          nodeId="sma2"
          pack={pack}
          onChange={onChange}
        />,
      );
      fireEvent.change(lenInput(), { target: { value: invalidValue } });
      const error = screen.getByTestId("studio-node-inspector-len-error");
      expect(error.textContent).toBe(
        "Enter a whole number between 2 and 600.",
      );
      expect(onChange).not.toHaveBeenCalled();
      expect(pack.indicators).toEqual(makePack().indicators);
    },
  );

  it.each(INVALID_LENGTH_INPUTS)(
    "flips the header status text to invalid for %j",
    (invalidValue) => {
      render(
        <StudioNodeInspector nodeId="sma2" pack={makePack()} onChange={vi.fn()} />,
      );
      fireEvent.change(lenInput(), { target: { value: invalidValue } });
      const status = screen.getByTestId("studio-node-inspector-status");
      expect(status.textContent?.toLowerCase()).toContain("invalid");
    },
  );

  it.each(INVALID_LENGTH_INPUTS)(
    "disables the submit affordance while the draft is invalid (%j)",
    (invalidValue) => {
      render(
        <StudioNodeInspector nodeId="sma2" pack={makePack()} onChange={vi.fn()} />,
      );
      fireEvent.change(lenInput(), { target: { value: invalidValue } });
      const apply = screen.getByTestId(
        "studio-node-inspector-apply",
      ) as HTMLButtonElement;
      expect(apply.disabled).toBe(true);
    },
  );

  it("clears the error, restores the valid status and re-enables submit after correcting", () => {
    const onChange = vi.fn();
    render(
      <StudioNodeInspector nodeId="sma2" pack={makePack()} onChange={onChange} />,
    );
    fireEvent.change(lenInput(), { target: { value: "601" } });
    expect(screen.getByTestId("studio-node-inspector-len-error")).toBeDefined();
    fireEvent.change(lenInput(), { target: { value: "20" } });
    expect(
      screen.queryByTestId("studio-node-inspector-len-error"),
    ).toBeNull();
    const status = screen.getByTestId("studio-node-inspector-status");
    expect(status.textContent?.toLowerCase()).toContain("valid");
    const apply = screen.getByTestId(
      "studio-node-inspector-apply",
    ) as HTMLButtonElement;
    expect(apply.disabled).toBe(false);
  });
});

describe("StudioNodeInspector signal slice — submit affordance", () => {
  it("is enabled while the draft is valid and re-emits a NEW pack reference on click", () => {
    const onChange = vi.fn();
    const pack = makePack();
    render(
      <StudioNodeInspector nodeId="sma2" pack={pack} onChange={onChange} />,
    );
    const apply = screen.getByTestId(
      "studio-node-inspector-apply",
    ) as HTMLButtonElement;
    expect(apply.disabled).toBe(false);
    fireEvent.click(apply);
    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0] as Record<string, unknown>;
    expect(next).not.toBe(pack);
    const indicators = next.indicators as Record<
      string,
      Record<string, unknown>
    >;
    expect(indicators.sma2.len).toBe(2);
    expect(indicators.sma2.src).toBe("close");
    expect(indicators.sma20.len).toBe(20);
  });

  it("applies an edited valid draft through the same new-reference path", () => {
    const onChange = vi.fn();
    const pack = makePack();
    render(
      <StudioNodeInspector nodeId="sma2" pack={pack} onChange={onChange} />,
    );
    fireEvent.change(lenInput(), { target: { value: "9" } });
    expect(onChange).toHaveBeenCalledTimes(1);
    const apply = screen.getByTestId(
      "studio-node-inspector-apply",
    ) as HTMLButtonElement;
    fireEvent.click(apply);
    expect(onChange).toHaveBeenCalledTimes(2);
    const next = onChange.mock.calls[1][0] as Record<string, unknown>;
    expect(next).not.toBe(pack);
    expect(
      (next.indicators as Record<string, Record<string, unknown>>).sma2.len,
    ).toBe(9);
    expect(pack.indicators).toEqual(makePack().indicators);
  });

  it("does nothing when clicked while invalid", () => {
    const onChange = vi.fn();
    render(
      <StudioNodeInspector nodeId="sma2" pack={makePack()} onChange={onChange} />,
    );
    fireEvent.change(lenInput(), { target: { value: "3.5" } });
    const apply = screen.getByTestId(
      "studio-node-inspector-apply",
    ) as HTMLButtonElement;
    expect(apply.disabled).toBe(true);
    fireEvent.click(apply);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("keeps the indicator spec JSON export control mounted unchanged", () => {
    render(
      <StudioNodeInspector nodeId="sma2" pack={makePack()} onChange={vi.fn()} />,
    );
    expect(
      screen.getByTestId("studio-indicator-spec-export"),
    ).toBeDefined();
  });
});

describe("StudioNodeInspector signal slice — stylesheet contract", () => {
  const stylesDir = dirname(fileURLToPath(import.meta.url));
  let css = "";
  const readCss = (): string => {
    if (css === "") {
      css = readFileSync(
        join(stylesDir, "StudioNodeInspector.signal.css"),
        "utf8",
      );
    }
    return css;
  };

  it("is root-scoped to the inspector and consumes the approved named tokens", () => {
    const css = readCss();
    expect(css).toMatch(/^\.kbot-studio-node-inspector\b/m);
    for (const token of [
      "--navy",
      "--surface",
      "--panel",
      "--line",
      "--text",
      "--muted",
      "--seafoam",
      "--sage",
      "--coral",
    ]) {
      expect(css).toContain(`var(${token}`);
    }
  });

  it("does not reintroduce the retired neon palette or remote fonts", () => {
    const css = readCss();
    for (const legacy of ["#07090d", "#5ce1ff", "#c6ff3d"]) {
      expect(css.toLowerCase()).not.toContain(legacy);
    }
    expect(css).not.toMatch(/@import|https?:\/\//);
    expect(css).not.toMatch(/font-family:\s*ui-monospace/);
  });

  it("keeps long node ids from widening the page and narrow targets reachable", () => {
    const css = readCss();
    expect(css).toMatch(/overflow-wrap:\s*anywhere/);
    const mediaIndex = css.indexOf("@media");
    expect(mediaIndex).toBeGreaterThan(-1);
    const narrow = css.slice(mediaIndex);
    expect(narrow).toMatch(/min-height:\s*44px/);
    expect(css).toMatch(/:focus-visible/);
  });
});
