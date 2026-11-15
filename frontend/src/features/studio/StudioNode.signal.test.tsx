/**
 * Studio graph nodes — Signal readability slice (KRELL-SIGNAL-20261010).
 *
 * Pins the white-on-white fix, human-readable labels, seafoam selection,
 * and debug-chrome hiding for the default Studio view. jsdom has no
 * layout engine, so contrast proofs read the shipped stylesheet the
 * same way other Signal suites do.
 */

import { cleanup, render, screen } from "@testing-library/react";
import { ReactFlowProvider } from "@xyflow/react";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { JSX, ReactNode } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { StudioNode } from "./StudioNode";

const here = dirname(fileURLToPath(import.meta.url));

afterEach(cleanup);

function readStylesheet(): string {
  return readFileSync(join(here, "StudioNode.signal.css"), "utf8");
}

function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "");
}

function FlowHarness({ children }: { children: ReactNode }): JSX.Element {
  return <ReactFlowProvider>{children}</ReactFlowProvider>;
}

function renderNode(
  id: string,
  opts: {
    label?: string;
    timeframe?: string;
    selected?: boolean;
  } = {},
): void {
  render(
    <FlowHarness>
      <StudioNode
        id={id}
        data={{
          timeframe: opts.timeframe ?? "1h",
          label: opts.label,
        }}
        selected={opts.selected ?? false}
        type="default"
        dragging={false}
        zIndex={0}
        selectable
        deletable
        draggable
        isConnectable
        positionAbsoluteX={0}
        positionAbsoluteY={0}
      />
    </FlowHarness>,
  );
}

describe("StudioNode signal slice — readable labels", () => {
  it("renders a human-readable Pack title instead of the raw id alone", () => {
    renderNode("pack", { label: "Pack" });
    const node = screen.getByTestId("studio-node-pack");
    expect(node.querySelector(".kbot-studio-node__label")?.textContent).toBe(
      "Pack",
    );
    expect(node.textContent).not.toMatch(/^pack$/);
  });

  it("falls back to studioNodeLabel when data.label is absent", () => {
    renderNode("sma2", { label: undefined });
    expect(
      screen.getByTestId("studio-node-sma2").querySelector(
        ".kbot-studio-node__label",
      )?.textContent,
    ).toBe("SMA 2");
  });

  it("marks selection for seafoam chrome", () => {
    renderNode("entry", { label: "Entry", selected: true });
    const node = screen.getByTestId("studio-node-entry");
    expect(node.classList.contains("kbot-studio-node--selected")).toBe(true);
    expect(node.getAttribute("data-selected")).toBe("1");
  });
});

describe("StudioNode signal slice — contrast and selection contract", () => {
  it("imports the Studio node stylesheet from StudioNode.tsx", () => {
    const source = readFileSync(join(here, "StudioNode.tsx"), "utf8");
    expect(source).toMatch(/import\s+"\.\/StudioNode\.signal\.css"/);
  });

  it("paints nodes with Signal panel fill and --text (no white-on-white)", () => {
    const css = stripComments(readStylesheet());
    expect(css).toMatch(
      /\.kbot-studio-node\s*\{[^}]*background:\s*var\(--panel/,
    );
    expect(css).toMatch(
      /\.kbot-studio-node\s*\{[^}]*color:\s*var\(--text/,
    );
    expect(css).toMatch(
      /\.kbot-studio-node__label\s*\{[^}]*color:\s*var\(--text/,
    );
    // Neutralize ReactFlow's white default chrome inside the Studio host.
    expect(css).toMatch(
      /\.kbot-graph-canvas\s+\.react-flow__node-default[\s\S]*?background:\s*transparent/,
    );
    expect(css.toLowerCase()).not.toMatch(
      /\.kbot-studio-node\s*\{[^}]*background:\s*#fff/,
    );
    expect(css.toLowerCase()).not.toMatch(
      /\.kbot-studio-node\s*\{[^}]*background:\s*white/,
    );
    for (const retired of ["#5ce1ff", "#c6ff3d", "#07090d"]) {
      expect(css.toLowerCase()).not.toContain(retired);
    }
  });

  it("uses seafoam for selected nodes", () => {
    const css = stripComments(readStylesheet());
    expect(css).toMatch(
      /\.kbot-studio-node--selected\s*\{[^}]*border-color:\s*var\(--seafoam/,
    );
  });

  it("hides debug-only Studio chrome from the default painted view", () => {
    const css = stripComments(readStylesheet());
    expect(css).toMatch(
      /\.kbot-studio-debug\s*\{[^}]*clip:\s*rect\(0,\s*0,\s*0,\s*0\)/,
    );
    expect(css).toMatch(
      /\.kbot-studio-debug\s*\{[^}]*position:\s*absolute/,
    );
  });
});
