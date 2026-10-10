/**
 * Graph canvas — Signal sizing slice (KRELL-SIGNAL-20261010).
 *
 * These tests pin the graph-host sizing prerequisite the Studio W2
 * BLOCKED verdict named as its dependent gate:
 *
 *  - the existing root ``<div data-testid="graph-canvas">`` gets an
 *    explicit responsive height (ReactFlow error #004: it renders 0px
 *    unless its parent has a measured width AND height);
 *  - the height is responsive (viewport-relative via clamp), never a
 *    fixed desktop-only pixel value that breaks mobile;
 *  - the host stays width-contained (min-width 0, max-width 100%,
 *    contained internal overflow) so dense node graphs never widen
 *    the whole page;
 *  - the ReactFlow pane fills the sized host;
 *  - the shared Signal tokens/local fonts are reused (no new theme),
 *    with keyboard-visible focus and >=44px narrow targets for the
 *    canvas host's interactive children (the edge-refusal dismiss);
 *  - the existing behavioral contracts (onConnect routing through
 *    refuseIncompatibleEdge, onNodeClick/onSelectNode, fitView
 *    default, proOptions.hideAttribution, EdgeRefusalNotice) keep
 *    working unchanged inside the sized host.
 *
 * jsdom has no layout engine, so the viewport-height proofs resolve
 * the *actual shipped* clamp()/vh expressions from
 * GraphCanvas.signal.css against the named viewports (1600x900 and
 * 390x844). They fail loudly when the stylesheet is missing, so they
 * are RED on the unsized canvas and GREEN once the host is sized.
 * Real mounted-layout measurements at both viewports are captured by
 * the browser evidence harness outside this repository.
 */

import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { act, cleanup, render, screen } from "@testing-library/react";
import {
  afterEach,
  beforeAll,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import type { Node, NodeTypes, OnConnect, NodeMouseHandler } from "@xyflow/react";
import type { JSX } from "react";
import { GraphCanvas } from "./GraphCanvas";

const here = dirname(fileURLToPath(import.meta.url));

/* ------------------------------------------------------------------ */
/* ReactFlow capture mock (same pattern as GraphCanvas.test.tsx)       */
/* ------------------------------------------------------------------ */

type CapturedReactFlowProps = {
  onConnect?: OnConnect;
  onNodeClick?: NodeMouseHandler;
  nodes?: Node[];
  nodeTypes?: NodeTypes;
  fitView?: boolean;
  proOptions?: { hideAttribution?: boolean };
};

type CapturedReactFlowRendererProps = CapturedReactFlowProps & {
  children?: React.ReactNode;
};

let lastReactFlowProps: CapturedReactFlowProps | null = null;

vi.mock("@xyflow/react", async () => {
  const actual =
    await vi.importActual<typeof import("@xyflow/react")>("@xyflow/react");
  function CapturedReactFlow(
    props: CapturedReactFlowRendererProps,
  ): JSX.Element {
    lastReactFlowProps = props;
    return (
      <div
        data-testid="react-flow-stub"
        className="react-flow"
        role="application"
      >
        {props.children}
      </div>
    );
  }
  return {
    ...actual,
    ReactFlow: CapturedReactFlow,
  };
});

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

beforeAll(() => {
  if (typeof globalThis.ResizeObserver !== "function") {
    globalThis.ResizeObserver =
      ResizeObserverStub as unknown as typeof ResizeObserver;
  }
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  lastReactFlowProps = null;
});

function nodeOf(
  id: string,
  timeframe: string | undefined,
): Node<{ timeframe?: string }> {
  return {
    id,
    type: "default",
    position: { x: 0, y: 0 },
    data: { timeframe },
  };
}

function getCaptured(): CapturedReactFlowProps {
  expect(lastReactFlowProps).not.toBeNull();
  return lastReactFlowProps as CapturedReactFlowProps;
}

/* ------------------------------------------------------------------ */
/* Stylesheet reader + viewport-aware height resolution                */
/* ------------------------------------------------------------------ */

let cssCache = "";

function readStylesheet(): string {
  if (cssCache === "") {
    cssCache = readFileSync(
      join(here, "GraphCanvas.signal.css"),
      "utf8",
    );
  }
  return cssCache;
}

type CssBlock = { selector: string; declarations: string };

function selectorBlocks(source: string): CssBlock[] {
  const blocks: CssBlock[] = [];
  const pattern = /([^{}]+)\{([^{}]*)\}/g;
  let match = pattern.exec(source);
  while (match) {
    blocks.push({ selector: match[1].trim(), declarations: match[2] });
    match = pattern.exec(source);
  }
  return blocks;
}

/** Strips comments so declarations are matched without comment noise. */
function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "");
}

/** Media conditions this repository's slice stylesheets use. */
function mediaQueryApplies(
  query: string,
  viewportWidth: number,
): boolean {
  const max = query.match(/max-width:\s*([\d.]+)px/);
  if (max) {
    return viewportWidth <= Number(max[1]);
  }
  const min = query.match(/min-width:\s*([\d.]+)px/);
  if (min) {
    return viewportWidth >= Number(min[1]);
  }
  return false;
}

type MediaQueryBlock = { query: string; body: string };

/** Splits a stylesheet into its top-level rules and its @media blocks. */
function splitMedia(source: string): {
  base: string;
  media: MediaQueryBlock[];
} {
  const media: MediaQueryBlock[] = [];
  let base = "";
  let i = 0;
  while (i < source.length) {
    const at = source.indexOf("@media", i);
    if (at === -1) {
      base += source.slice(i);
      break;
    }
    base += source.slice(i, at);
    const open = source.indexOf("{", at);
    const query = source.slice(at, open);
    let depth = 1;
    let j = open + 1;
    while (j < source.length && depth > 0) {
      if (source[j] === "{") {
        depth += 1;
      } else if (source[j] === "}") {
        depth -= 1;
      }
      j += 1;
    }
    media.push({ query, body: source.slice(open + 1, j - 1) });
    i = j;
  }
  return { base, media };
}

/**
 * Resolves the ``height`` the shipped stylesheet gives
 * ``.kbot-graph-canvas`` at a given viewport. Top-level rules always
 * apply; ``@media`` rules apply per their condition and override in
 * source order, exactly like the cascade. Accepts clamp(), vh and px
 * values.
 */
function resolvedHostHeightPx(
  viewportWidth: number,
  viewportHeight: number,
): number {
  const { base, media } = splitMedia(stripComments(readStylesheet()));
  let height: number | null = null;
  for (const block of selectorBlocks(base)) {
    if (!isHostSelector(block.selector)) {
      continue;
    }
    const value = declarationValue(block.declarations, "height");
    if (value !== null) {
      height = lengthToPx(value, viewportHeight);
    }
  }
  for (const block of media) {
    if (!mediaQueryApplies(block.query, viewportWidth)) {
      continue;
    }
    for (const rule of selectorBlocks(block.body)) {
      if (!isHostSelector(rule.selector)) {
        continue;
      }
      const value = declarationValue(rule.declarations, "height");
      if (value !== null) {
        height = lengthToPx(value, viewportHeight);
      }
    }
  }
  if (height === null) {
    throw new Error(
      "GraphCanvas.signal.css gives .kbot-graph-canvas no applicable height",
    );
  }
  return height;
}

function isHostSelector(selector: string): boolean {
  return selector
    .split(",")
    .some((part) => part.trim() === ".kbot-graph-canvas");
}

function declarationValue(
  declarations: string,
  property: string,
): string | null {
  const pattern = new RegExp(
    `(?:^|;)\\s*${property}\\s*:\\s*([^;]+)\\s*(?:;|$)`,
  );
  const match = declarations.match(pattern);
  return match ? match[1].trim() : null;
}

function lengthToPx(value: string, viewportHeight: number): number {
  const clamp = value.match(
    /^clamp\(\s*([\d.]+)px\s*,\s*([\d.]+)vh\s*,\s*([\d.]+)px\s*\)$/,
  );
  if (clamp) {
    const min = Number(clamp[1]);
    const preferred = (Number(clamp[2]) / 100) * viewportHeight;
    const max = Number(clamp[3]);
    return Math.min(Math.max(preferred, min), max);
  }
  const vh = value.match(/^([\d.]+)vh$/);
  if (vh) {
    return (Number(vh[1]) / 100) * viewportHeight;
  }
  const px = value.match(/^([\d.]+)px$/);
  if (px) {
    return Number(px[1]);
  }
  throw new Error(`unsupported height value in GraphCanvas.signal.css: ${value}`);
}

/* ------------------------------------------------------------------ */
/* 1. DOM: the existing root host is the sized element                 */
/* ------------------------------------------------------------------ */

describe("GraphCanvas signal slice — sized host root", () => {
  it("keeps data-testid=\"graph-canvas\" and applies the studio host sizing class", () => {
    render(
      <GraphCanvas
        nodes={[nodeOf("a", "1h")]}
        onAddConnection={() => {}}
      />,
    );
    const host = screen.getByTestId("graph-canvas");
    expect(host).toBeInstanceOf(HTMLElement);
    expect(host.classList.contains("kbot-graph-canvas")).toBe(true);
  });

  it("imports the studio host stylesheet from GraphCanvas.tsx", () => {
    const source = readFileSync(resolve(here, "GraphCanvas.tsx"), "utf8");
    expect(source).toMatch(/import\s+"\.\/GraphCanvas\.signal\.css"/);
  });
});

/* ------------------------------------------------------------------ */
/* 2. Stylesheet contract: responsive, contained, token-based          */
/* ------------------------------------------------------------------ */

describe("GraphCanvas signal slice — responsive height contract", () => {
  it("gives the host an explicit responsive height (viewport-relative clamp, no fixed-only pixels)", () => {
    const css = stripComments(readStylesheet());
    const hostBlocks = selectorBlocks(splitMedia(css).base).filter((block) =>
      isHostSelector(block.selector),
    );
    expect(hostBlocks.length).toBeGreaterThanOrEqual(1);
    const heights = hostBlocks
      .map((block) => declarationValue(block.declarations, "height"))
      .filter((value): value is string => value !== null);
    expect(heights.length).toBeGreaterThanOrEqual(1);
    for (const value of heights) {
      expect(value).toMatch(/clamp\(\s*[\d.]+px\s*,\s*[\d.]+vh\s*,\s*[\d.]+px\s*\)/);
      expect(value).not.toMatch(/^\d+px$/);
    }
  });

  it("measures at least 400px at a 1600x900 viewport", () => {
    // ReactFlow error #004: without a parent height the production
    // container measures 0px and no node is reachable.
    expect(resolvedHostHeightPx(1600, 900)).toBeGreaterThanOrEqual(400);
  });

  it("measures a non-zero, viewport-bounded height at 390x844", () => {
    const height = resolvedHostHeightPx(390, 844);
    expect(height).toBeGreaterThan(0);
    expect(height).toBeGreaterThanOrEqual(300);
    expect(height).toBeLessThanOrEqual(844);
  });

  it("stays width-contained so dense node graphs never widen the page", () => {
    const css = stripComments(readStylesheet());
    const host = selectorBlocks(splitMedia(css).base).find((block) =>
      isHostSelector(block.selector),
    );
    expect(host).toBeDefined();
    const declarations = host!.declarations;
    expect(declarationValue(declarations, "min-width")).toBe("0");
    const maxWidth = declarationValue(declarations, "max-width");
    const width = declarationValue(declarations, "width");
    expect(maxWidth === "100%" || width === "100%").toBe(true);
    const overflow = declarationValue(declarations, "overflow");
    expect(overflow === "hidden" || overflow === "clip").toBe(true);
  });

  it("makes the ReactFlow pane fill the sized host", () => {
    const css = stripComments(readStylesheet());
    const pane = selectorBlocks(splitMedia(css).base).find((block) =>
      block.selector.includes(".kbot-graph-canvas > .react-flow"),
    );
    expect(pane).toBeDefined();
    const declarations = pane!.declarations;
    expect(declarationValue(declarations, "width")).toBe("100%");
    expect(declarationValue(declarations, "height")).toBe("100%");
    expect(declarationValue(declarations, "min-height")).toBe("0");
  });

  it("reuses the approved Signal tokens with their approved fallbacks", () => {
    const css = readStylesheet();
    for (const token of ["--surface", "--line", "--radius-panel", "--focus-ring"]) {
      expect(css).toContain(`var(${token}`);
    }
    // No new theme: local tokens only, nothing remote.
    expect(css).not.toMatch(/@import|https?:\/\//);
    for (const retired of ["#5ce1ff", "#c6ff3d", "#07090d"]) {
      expect(css.toLowerCase()).not.toContain(retired);
    }
  });

  it("keeps narrow interactive children >=44px and focus keyboard-visible", () => {
    const css = stripComments(readStylesheet());
    const mediaIndex = css.indexOf("@media");
    expect(mediaIndex).toBeGreaterThan(-1);
    const narrow = css.slice(mediaIndex);
    expect(narrow).toMatch(/min-height:\s*44px/);
    expect(css).toMatch(
      /:focus-visible\s*\{[^}]*outline:\s*2px solid var\(--focus-ring/,
    );
  });
});

/* ------------------------------------------------------------------ */
/* 3. The sized host preserves every existing canvas contract          */
/* ------------------------------------------------------------------ */

describe("GraphCanvas signal slice — sized host preserves canvas behavior", () => {
  it("still forwards onNodeClick so node selection reaches the parent", () => {
    const onSelectNode = vi.fn();
    render(
      <GraphCanvas
        nodes={[nodeOf("a", "1h")]}
        onAddConnection={() => {}}
        onSelectNode={onSelectNode}
      />,
    );
    const { onNodeClick } = getCaptured();
    expect(onNodeClick).toBeDefined();
    act(() => {
      onNodeClick!(
        {} as unknown as React.MouseEvent,
        nodeOf("a", "1h") as never,
      );
    });
    expect(onSelectNode).toHaveBeenCalledWith("a");
  });

  it("renders EdgeRefusalNotice inside the sized host on a refused connect and dismisses it", () => {
    const onAddConnection = vi.fn();
    render(
      <GraphCanvas
        nodes={[nodeOf("a", "1h"), nodeOf("b", "4h")]}
        onAddConnection={onAddConnection}
      />,
    );
    const host = screen.getByTestId("graph-canvas");
    const captured = getCaptured();
    act(() => {
      captured.onConnect!({
        source: "a",
        target: "b",
        sourceHandle: null,
        targetHandle: null,
      });
    });
    expect(onAddConnection).not.toHaveBeenCalled();
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("Timeframe mismatch");
    expect(host.contains(alert)).toBe(true);
    act(() => {
      screen
        .getByRole("button", { name: "Dismiss edge refusal" })
        .click();
    });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("keeps the fitView default and hidden attribution", () => {
    render(
      <GraphCanvas nodes={[nodeOf("a", "1h")]} onAddConnection={() => {}} />,
    );
    const captured = getCaptured();
    expect(captured.fitView).toBe(false);
    expect(captured.proOptions).toEqual({ hideAttribution: true });
  });
});
