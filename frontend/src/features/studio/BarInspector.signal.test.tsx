/**
 * BarInspector Signal presentation slice — KRELL-SIGNAL-20261010.
 *
 * Pins the scoped Signal presentation of the Studio bar inspector: the
 * `.kbot-feature__bar-inspector-root` wrapper, the surface/panel/line
 * token treatment, seafoam selection + focus, mono bar-index field and
 * the sage-reinforced "closed" / coral-derived unavailable status —
 * while preserving every existing attribute contract byte-identically:
 * the "Selected bar" label, the `bar-inspector-selected-bar` id, the
 * readonly number input and the exact status strings ("closed",
 * "bar missing", "future bar", "checkpoint missing") with no
 * paraphrase. This surface exposes no data-testid, role, aria-label or
 * apply/save control on the accepted base, so the preserved contract is
 * the label/id pair and the exact status text; no field, validation
 * rule or behaviour is added.
 *
 * TEST TRANSPORT NOTICE: these tests run the real component with
 * in-memory node fixtures only. Nothing here qualifies a backend, pack
 * or graph state.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { BarInspector } from "./BarInspector";

const here = dirname(fileURLToPath(import.meta.url));

afterEach(cleanup);

const UNAVAILABLE_CASES = [
  { name: "bar missing (undefined bar_index)", node: {}, reason: "bar missing" },
  {
    name: "bar missing (null bar_index)",
    node: { bar_index: null },
    reason: "bar missing",
  },
  {
    name: "future bar",
    node: { bar_index: 100 },
    decisionBar: 10,
    reason: "future bar",
  },
  {
    name: "checkpoint missing",
    node: { fn: "ema", bar_index: 5 },
    reason: "checkpoint missing",
  },
] as const;

function rootOf(container: HTMLElement): HTMLElement {
  const root = container.firstElementChild as HTMLElement | null;
  expect(root).not.toBeNull();
  expect(root?.className).toBe("kbot-feature__bar-inspector-root");
  return root as HTMLElement;
}

describe("BarInspector signal slice — scoped wrapper", () => {
  it("renders the single .kbot-feature__bar-inspector-root wrapper", () => {
    const { container } = render(
      <BarInspector node={{ bar_index: 5 }} decisionBar={10} />,
    );
    expect(
      container.querySelectorAll(".kbot-feature__bar-inspector-root"),
    ).toHaveLength(1);
    rootOf(container);
  });

  it("renders the wrapper across every branch (closed and unavailable)", () => {
    for (const { node } of UNAVAILABLE_CASES) {
      const { container } = render(
        <BarInspector node={node} decisionBar={10} />,
      );
      expect(
        container.querySelectorAll(".kbot-feature__bar-inspector-root"),
      ).toHaveLength(1);
      cleanup();
    }
    const { container } = render(
      <BarInspector node={{ bar_index: 5 }} decisionBar={10} />,
    );
    expect(
      container.querySelectorAll(".kbot-feature__bar-inspector-root"),
    ).toHaveLength(1);
  });

  it("applies the status modifier classes per branch", () => {
    const { container } = render(
      <BarInspector node={{ bar_index: 5 }} decisionBar={10} />,
    );
    const status = rootOf(container).querySelector("p");
    expect(status?.className).toBe(
      "kbot-feature__bar-inspector-root__status kbot-feature__bar-inspector-root__status--closed",
    );
    cleanup();

    const unavailable = render(
      <BarInspector node={{ bar_index: 100 }} decisionBar={10} />,
    );
    const unavailableStatus = unavailable.container.querySelector("p");
    expect(unavailableStatus?.className).toBe(
      "kbot-feature__bar-inspector-root__status kbot-feature__bar-inspector-root__status--unavailable",
    );
  });
});

describe("BarInspector signal slice — preserved attribute contract", () => {
  it("keeps the exact 'Selected bar' label bound to the existing input id", () => {
    render(<BarInspector node={{ bar_index: 5 }} decisionBar={10} />);
    const input = screen.getByLabelText("Selected bar") as HTMLInputElement;
    expect(input.id).toBe("bar-inspector-selected-bar");
    expect(input.type).toBe("number");
    expect(input.readOnly).toBe(true);
    expect(input.value).toBe("10");
    expect(screen.getAllByLabelText("Selected bar")).toHaveLength(1);
  });

  it("keeps the exact status strings byte-identical with no paraphrase", () => {
    for (const { node, reason } of UNAVAILABLE_CASES) {
      const { container } = render(
        <BarInspector node={node} decisionBar={10} />,
      );
      const padded = ` ${container.textContent ?? ""} `;
      expect(padded).toContain(reason);
      for (const paraphrase of [
        `Reason: ${reason}`,
        `Status: ${reason}`,
        `Unavailable: ${reason}`,
        `${reason}!`,
      ]) {
        expect(padded).not.toContain(paraphrase);
      }
      cleanup();
    }

    const closed = render(
      <BarInspector node={{ bar_index: 5 }} decisionBar={10} />,
    );
    expect(screen.getByText("closed")).toBeDefined();
    expect(` ${closed.container.textContent ?? ""} `).not.toContain(
      "Status: closed",
    );
  });

  it("adds no new field, control or test hook to the surface", () => {
    const { container } = render(
      <BarInspector node={{ bar_index: 5 }} decisionBar={10} />,
    );
    const root = rootOf(container);
    // The accepted base is exactly: label + readonly input + one status <p>.
    expect(root.children).toHaveLength(3);
    expect(root.querySelector("button")).toBeNull();
    expect(root.querySelector("select")).toBeNull();
    expect(root.querySelector("textarea")).toBeNull();
    expect(root.querySelectorAll("input")).toHaveLength(1);
    expect(root.querySelectorAll("label")).toHaveLength(1);
    expect(root.querySelectorAll("p")).toHaveLength(1);
  });
});

describe("BarInspector signal slice — stylesheet contract", () => {
  let css = "";
  const readCss = (): string => {
    if (css === "") {
      css = readFileSync(join(here, "BarInspector.signal.css"), "utf8");
    }
    return css;
  };

  it("is root-scoped to the inspector and consumes the approved named tokens", () => {
    const css = readCss();
    expect(css).toMatch(/^\.kbot-feature__bar-inspector-root\b/m);
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

  it("keeps seafoam focus/selection and touch-sized targets at <=640px", () => {
    const css = readCss();
    expect(css).toMatch(/overflow-wrap:\s*anywhere/);
    expect(css).toMatch(/:focus-visible/);
    expect(css).toMatch(/::selection/);
    const mediaIndex = css.indexOf("@media (max-width: 640px)");
    expect(mediaIndex).toBeGreaterThan(-1);
    const narrow = css.slice(mediaIndex);
    expect(narrow).toMatch(/min-height:\s*44px/);
    // No control on this surface is exempt from the 44px narrow rule.
    expect(narrow).toMatch(
      /input\[type="number"\]\s*\{[^}]*min-height:\s*44px/,
    );
  });

  it("carries status meaning in text with color as reinforcement only", () => {
    const css = readCss();
    expect(css).toMatch(
      /\.kbot-feature__bar-inspector-root__status--closed\b/,
    );
    expect(css).toMatch(
      /\.kbot-feature__bar-inspector-root__status--unavailable\b/,
    );
  });
});
