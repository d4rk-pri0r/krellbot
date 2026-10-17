import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BarInspector } from "./BarInspector";
import * as observeModule from "./observe";
import type { ObserveNodeInput } from "./observe";

const here = dirname(fileURLToPath(import.meta.url));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("BarInspector — selected-bar input shape", () => {
  it("renders a single <input type=\"number\"> labeled 'Selected bar'", () => {
    render(<BarInspector node={{ bar_index: 5 }} decisionBar={10} />);
    const input = screen.getByLabelText("Selected bar");
    expect(input).toBeDefined();
    expect(input.tagName).toBe("INPUT");
    expect((input as HTMLInputElement).type).toBe("number");
  });

  it("does not disable the Selected bar input", () => {
    render(<BarInspector node={{ bar_index: 5 }} decisionBar={10} />);
    const input = screen.getByLabelText("Selected bar") as HTMLInputElement;
    expect(input.disabled).toBe(false);
  });

  it("does not set tabIndex to -1 on the Selected bar input", () => {
    render(<BarInspector node={{ bar_index: 5 }} decisionBar={10} />);
    const input = screen.getByLabelText("Selected bar") as HTMLInputElement;
    expect(input.tabIndex).not.toBe(-1);
  });

  it("shows the decision bar, not the node's bar index", () => {
    render(<BarInspector node={{ bar_index: 8 }} decisionBar={5} />);
    const input = screen.getByLabelText("Selected bar") as HTMLInputElement;
    expect(input.value).toBe("5");
  });

  it("renders exactly one Selected bar input", () => {
    render(<BarInspector node={{ bar_index: 5 }} decisionBar={10} />);
    expect(screen.getAllByLabelText("Selected bar")).toHaveLength(1);
  });
});

describe("BarInspector — calls observeNode from ./observe", () => {
  it("calls observeNode with the supplied node and decisionBar for a closed bar", () => {
    const spy = vi.spyOn(observeModule, "observeNode");
    render(<BarInspector node={{ bar_index: 7 }} decisionBar={10} />);
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith({ bar_index: 7 }, 10);
  });

  it("calls observeNode with the supplied node and decisionBar for a future bar", () => {
    const spy = vi.spyOn(observeModule, "observeNode");
    render(<BarInspector node={{ bar_index: 100 }} decisionBar={10} />);
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith({ bar_index: 100 }, 10);
  });

  it("calls observeNode with the supplied node and decisionBar for a bar-missing node", () => {
    const spy = vi.spyOn(observeModule, "observeNode");
    render(<BarInspector node={{}} decisionBar={10} />);
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith({}, 10);
  });

  it("calls observeNode with the supplied node and decisionBar for a checkpoint-missing node", () => {
    const spy = vi.spyOn(observeModule, "observeNode");
    render(
      <BarInspector
        node={{ fn: "ema", bar_index: 5 }}
        decisionBar={10}
      />,
    );
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith(
      { fn: "ema", bar_index: 5 },
      10,
    );
  });

  it("calls observeNode exactly once per render", () => {
    const spy = vi.spyOn(observeModule, "observeNode");
    render(<BarInspector node={{ bar_index: 5 }} decisionBar={10} />);
    expect(spy).toHaveBeenCalledTimes(1);
  });
});

describe("BarInspector — exact reason strings for unavailable results", () => {
  const cases: {
    name: string;
    node: ObserveNodeInput;
    decisionBar: number;
    reason: string;
  }[] = [
    {
      name: "bar missing — undefined bar_index",
      node: {},
      decisionBar: 10,
      reason: "bar missing",
    },
    {
      name: "bar missing — null bar_index",
      node: { bar_index: null },
      decisionBar: 10,
      reason: "bar missing",
    },
    {
      name: "future bar — bar_index greater than decisionBar",
      node: { bar_index: 11 },
      decisionBar: 10,
      reason: "future bar",
    },
    {
      name: "future bar — bar_index one above decisionBar",
      node: { bar_index: 1 },
      decisionBar: 0,
      reason: "future bar",
    },
    {
      name: "checkpoint missing — ema with undefined checkpoint",
      node: { fn: "ema", bar_index: 5 },
      decisionBar: 10,
      reason: "checkpoint missing",
    },
    {
      name: "checkpoint missing — atr with undefined checkpoint",
      node: { fn: "atr", bar_index: 5 },
      decisionBar: 10,
      reason: "checkpoint missing",
    },
    {
      name: "checkpoint missing — roofing_filter with undefined checkpoint",
      node: { fn: "roofing_filter", bar_index: 5 },
      decisionBar: 10,
      reason: "checkpoint missing",
    },
  ];

  for (const { name, node: caseNode, decisionBar, reason } of cases) {
    it(`renders the exact reason '${reason}' for ${name}`, () => {
      const { container } = render(
        <BarInspector node={caseNode} decisionBar={decisionBar} />,
      );
      const walker = document.createTreeWalker(
        container,
        NodeFilter.SHOW_TEXT,
      );
      const exact: Text[] = [];
      let current = walker.nextNode();
      while (current) {
        if (current.nodeValue === reason) exact.push(current as Text);
        current = walker.nextNode();
      }
      expect(exact.length).toBeGreaterThanOrEqual(1);
    });

    it(`does not paraphrase the reason '${reason}' for ${name}`, () => {
      const { container } = render(
        <BarInspector node={caseNode} decisionBar={decisionBar} />,
      );
      const padded = ` ${container.textContent ?? ""} `;
      for (const paraphrase of [
        `Reason: ${reason}`,
        `Refusal: ${reason}`,
        `Cannot observe: ${reason}`,
        `Unavailable: ${reason}`,
        `Bar ${reason}`,
        `${reason}!`,
      ]) {
        expect(padded).not.toContain(paraphrase);
      }
    });
  }
});

describe("BarInspector — closed result renders 'closed'", () => {
  it("renders the exact string 'closed' for a closed bar with no fn", () => {
    const { container } = render(
      <BarInspector node={{ bar_index: 5 }} decisionBar={10} />,
    );
    const walker = document.createTreeWalker(
      container,
      NodeFilter.SHOW_TEXT,
    );
    const exact: Text[] = [];
    let current = walker.nextNode();
    while (current) {
      if (current.nodeValue === "closed") exact.push(current as Text);
      current = walker.nextNode();
    }
    expect(exact.length).toBeGreaterThanOrEqual(1);
  });

  it("renders the exact string 'closed' when bar_index equals decisionBar", () => {
    render(
      <BarInspector node={{ bar_index: 10 }} decisionBar={10} />,
    );
    expect(screen.getByText("closed")).toBeDefined();
  });

  it("renders the exact string 'closed' when bar_index is zero and decisionBar is zero", () => {
    render(
      <BarInspector node={{ bar_index: 0 }} decisionBar={0} />,
    );
    expect(screen.getByText("closed")).toBeDefined();
  });

  it("renders the exact string 'closed' for a stateful fn with a dict checkpoint", () => {
    render(
      <BarInspector
        node={{ fn: "ema", bar_index: 5, checkpoint: { value: 42 } }}
        decisionBar={10}
      />,
    );
    expect(screen.getByText("closed")).toBeDefined();
  });

  it("does not paraphrase 'closed'", () => {
    const { container } = render(
      <BarInspector node={{ bar_index: 5 }} decisionBar={10} />,
    );
    const padded = ` ${container.textContent ?? ""} `;
    for (const paraphrase of [
      "Status: closed",
      "Bar closed",
      "closed!",
      "closed bar",
      "is closed",
    ]) {
      expect(padded).not.toContain(paraphrase);
    }
  });
});

describe("BarInspector — never renders 0 or fill_price as a status", () => {
  it("does not render the literal string '0' as a status when bar_index is missing", () => {
    const { container } = render(
      <BarInspector node={{}} decisionBar={10} />,
    );
    const padded = ` ${container.textContent ?? ""} `;
    expect(padded).not.toMatch(/(^|\s)0(\s|$)/);
  });

  it("does not render the literal string '0' as a status when bar_index is null", () => {
    const { container } = render(
      <BarInspector node={{ bar_index: null }} decisionBar={10} />,
    );
    const padded = ` ${container.textContent ?? ""} `;
    expect(padded).not.toMatch(/(^|\s)0(\s|$)/);
  });

  it("does not render the literal string 'fill_price' anywhere", () => {
    const { container } = render(
      <BarInspector node={{ bar_index: 5 }} decisionBar={10} />,
    );
    expect(container.textContent ?? "").not.toContain("fill_price");
    expect(container.textContent ?? "").not.toContain("Fill price");
  });

  it("does not render 'fill_price' on a missing bar", () => {
    const { container } = render(
      <BarInspector node={{}} decisionBar={10} />,
    );
    expect(container.textContent ?? "").not.toContain("fill_price");
  });

  it("does not render 'fill_price' on a future bar", () => {
    const { container } = render(
      <BarInspector node={{ bar_index: 100 }} decisionBar={10} />,
    );
    expect(container.textContent ?? "").not.toContain("fill_price");
  });

  it("does not render 'fill_price' on a checkpoint-missing result", () => {
    const { container } = render(
      <BarInspector
        node={{ fn: "ema", bar_index: 5 }}
        decisionBar={10}
      />,
    );
    expect(container.textContent ?? "").not.toContain("fill_price");
  });
});

describe("BarInspector — observeNode delegation across all branches", () => {
  it("renders 'bar missing' for a node whose bar_index is undefined", () => {
    render(<BarInspector node={{}} decisionBar={10} />);
    expect(screen.getByText("bar missing")).toBeDefined();
  });

  it("renders 'future bar' for a node whose bar_index is greater than decisionBar", () => {
    render(
      <BarInspector node={{ bar_index: 100 }} decisionBar={10} />,
    );
    expect(screen.getByText("future bar")).toBeDefined();
  });

  it("renders 'checkpoint missing' for a stateful fn with no checkpoint on a closed bar", () => {
    render(
      <BarInspector
        node={{ fn: "ema", bar_index: 5 }}
        decisionBar={10}
      />,
    );
    expect(screen.getByText("checkpoint missing")).toBeDefined();
  });

  it("renders 'closed' for a non-stateful fn on a closed bar", () => {
    render(
      <BarInspector
        node={{ fn: "sma", bar_index: 5 }}
        decisionBar={10}
      />,
    );
    expect(screen.getByText("closed")).toBeDefined();
  });

  it("renders 'closed' for no fn at all on a closed bar", () => {
    render(
      <BarInspector node={{ bar_index: 5 }} decisionBar={10} />,
    );
    expect(screen.getByText("closed")).toBeDefined();
  });
});

describe("BarInspector — side-effect freedom", () => {
  it("does not read localStorage while rendering a closed bar", () => {
    const spy = vi.spyOn(Storage.prototype, "getItem");
    render(<BarInspector node={{ bar_index: 5 }} decisionBar={10} />);
    expect(spy).not.toHaveBeenCalled();
  });

  it("does not read localStorage while rendering a missing bar", () => {
    const spy = vi.spyOn(Storage.prototype, "getItem");
    render(<BarInspector node={{}} decisionBar={10} />);
    expect(spy).not.toHaveBeenCalled();
  });

  it("does not read localStorage while rendering a future bar", () => {
    const spy = vi.spyOn(Storage.prototype, "getItem");
    render(<BarInspector node={{ bar_index: 100 }} decisionBar={10} />);
    expect(spy).not.toHaveBeenCalled();
  });

  it("does not read localStorage while rendering a checkpoint-missing result", () => {
    const spy = vi.spyOn(Storage.prototype, "getItem");
    render(
      <BarInspector
        node={{ fn: "ema", bar_index: 5 }}
        decisionBar={10}
      />,
    );
    expect(spy).not.toHaveBeenCalled();
  });

  it("does not call fetch while rendering a closed bar", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<BarInspector node={{ bar_index: 5 }} decisionBar={10} />);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("does not call fetch while rendering a missing bar", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<BarInspector node={{}} decisionBar={10} />);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("BarInspector — module surface", () => {
  it("does not import a graph library", () => {
    const source = readFileSync(
      resolve(here, "BarInspector.tsx"),
      "utf8",
    );
    expect(source).not.toMatch(/@xyflow\/react/);
    expect(source).not.toMatch(/from\s+["']reactflow["']/);
    expect(source).not.toMatch(/from\s+["']react-flow-renderer["']/);
    expect(source).not.toMatch(/from\s+["']d3["']/);
    expect(source).not.toMatch(/from\s+["']cytoscape["']/);
    expect(source).not.toMatch(/from\s+["']vis-network["']/);
  });

  it("does not import a network or fetch library", () => {
    const source = readFileSync(
      resolve(here, "BarInspector.tsx"),
      "utf8",
    );
    expect(source).not.toMatch(/from\s+["']axios["']/);
    expect(source).not.toMatch(/from\s+["']node-fetch["']/);
    expect(source).not.toMatch(/from\s+["']ky["']/);
  });

  it("does not import a storage library", () => {
    const source = readFileSync(
      resolve(here, "BarInspector.tsx"),
      "utf8",
    );
    expect(source).not.toMatch(/from\s+["']localforage["']/);
    expect(source).not.toMatch(/from\s+["']idb-keyval["']/);
  });

  it("imports observeNode from ./observe", () => {
    const source = readFileSync(
      resolve(here, "BarInspector.tsx"),
      "utf8",
    );
    expect(source).toMatch(/from\s+["']\.\/observe["']/);
    expect(source).toMatch(/observeNode/);
  });
});