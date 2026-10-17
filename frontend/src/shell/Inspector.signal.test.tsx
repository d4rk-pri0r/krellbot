import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { Inspector } from "./Inspector";

afterEach(cleanup);

const cssSource = readFileSync(
  resolve(__dirname, "Inspector.signal.css"),
  "utf8",
);

describe("Inspector Signal presentation", () => {
  it("keeps the region role and aria-label the shell queries rely on", () => {
    render(<Inspector />);
    const region = screen.getByRole("region", { name: "Inspector" });
    expect(region).not.toBeNull();
  });

  it("mounts the scoped Signal root class instead of the unscoped generic root", () => {
    render(<Inspector />);
    const region = screen.getByRole("region", { name: "Inspector" });
    expect(region.className).toBe("kbot-shell__inspector-root");
    expect(region.className).not.toContain("kbot-inspector ");
    expect(region.getAttribute("data-testid")).toBe("inspector-root");
  });

  it("renders the honest empty state copy verbatim with no invented subject", () => {
    render(<Inspector />);
    const empty = screen.getByTestId("inspector-empty");
    expect(empty.textContent).toBe(
      "Nothing selected — pick a revision on Strategies or a node in Studio to inspect it here.",
    );
    expect(screen.queryByTestId("inspector-selection")).toBeNull();
    expect(screen.queryByTestId("inspector-loading")).toBeNull();
    expect(screen.queryByTestId("inspector-error")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("keeps the title heading and inner block classes under the scoped root", () => {
    render(<Inspector />);
    const root = screen.getByTestId("inspector-root");
    const title = root.querySelector(".kbot-inspector__title");
    const head = root.querySelector(".kbot-inspector__head");
    const body = root.querySelector(".kbot-inspector__body");
    expect(title?.textContent).toBe("Inspector");
    expect(head).not.toBeNull();
    expect(body).not.toBeNull();
    expect(root.querySelector("h2")).toBe(title);
  });

  it("defaults to the empty state when explicitly given null selection", () => {
    render(<Inspector selection={null} loading={false} error={null} />);
    expect(screen.getByTestId("inspector-empty").textContent).toMatch(
      /Nothing selected/,
    );
    expect(screen.queryByTestId("inspector-selection")).toBeNull();
  });

  it("presents a passed selection without inventing a subject", () => {
    render(
      <Inspector selection={{ id: "sma20", label: "Indicator · sma(20)" }} />,
    );
    const selected = screen.getByTestId("inspector-selection");
    expect(selected.textContent).toContain("sma20");
    expect(selected.textContent).toContain("Indicator · sma(20)");
    expect(screen.queryByTestId("inspector-empty")).toBeNull();
    expect(screen.queryByTestId("inspector-loading")).toBeNull();
    expect(screen.queryByTestId("inspector-error")).toBeNull();
  });

  it("renders a selection with no label without an empty detail line", () => {
    render(<Inspector selection={{ id: "node-7" }} />);
    const selected = screen.getByTestId("inspector-selection");
    expect(selected.textContent).toContain("node-7");
    expect(selected.querySelector(".kbot-inspector__selected-detail")).toBeNull();
  });

  it("claims no subject while a read is in flight", () => {
    render(<Inspector selection={{ id: "node-7" }} loading />);
    expect(screen.getByTestId("inspector-loading").textContent).toBe(
      "Inspecting selection…",
    );
    expect(screen.queryByTestId("inspector-selection")).toBeNull();
    expect(screen.queryByTestId("inspector-empty")).toBeNull();
  });

  it("does not show the loading line without a subject to load", () => {
    render(<Inspector loading />);
    expect(screen.queryByTestId("inspector-loading")).toBeNull();
    expect(screen.getByTestId("inspector-empty").textContent).toMatch(
      /Nothing selected/,
    );
  });

  it("reports a read failure as an alert with the detail, never a subject", () => {
    render(<Inspector error="workstation returned 503" />);
    const alert = screen.getByTestId("inspector-error");
    expect(alert.getAttribute("role")).toBe("alert");
    expect(alert.textContent).toContain(
      "Could not inspect the selection — workstation returned 503",
    );
    expect(screen.queryByTestId("inspector-selection")).toBeNull();
    expect(screen.queryByTestId("inspector-loading")).toBeNull();
    expect(screen.queryByTestId("inspector-empty")).toBeNull();
  });

  it("prefers the error state over a concurrent selection and loading", () => {
    render(
      <Inspector selection={{ id: "node-7" }} loading error="stale read" />,
    );
    expect(screen.getByTestId("inspector-error").textContent).toContain(
      "stale read",
    );
    expect(screen.queryByTestId("inspector-selection")).toBeNull();
    expect(screen.queryByTestId("inspector-loading")).toBeNull();
  });

  it("scopes every rule under the Signal root and keeps the approved tokens", () => {
    for (const selector of [
      ".kbot-shell__inspector-root .kbot-inspector__head",
      ".kbot-shell__inspector-root .kbot-inspector__title",
      ".kbot-shell__inspector-root .kbot-inspector__body",
      ".kbot-shell__inspector-root .kbot-inspector__empty",
      ".kbot-shell__inspector-root .kbot-inspector__loading",
      ".kbot-shell__inspector-root .kbot-inspector__error",
      ".kbot-shell__inspector-root .kbot-inspector__selected",
    ]) {
      expect(cssSource.includes(selector)).toBe(true);
    }
    // No unscoped selector leaks outside the component root.
    for (const bare of [".kbot-inspector {", ".kbot-inspector,", ".kbot-inspector."]) {
      expect(cssSource.includes(bare)).toBe(false);
    }
    // Approved Signal vocabulary only: Manrope prose, mono technical ids,
    // navy/surface/line panels, seafoam selection, coral caution.
    expect(cssSource).toContain('var(--font-ui, "Manrope"');
    expect(cssSource).toContain('var(--font-mono, "IBM Plex Mono"');
    expect(cssSource).toContain("var(--seafoam, #a8d8d1)");
    expect(cssSource).toContain("var(--sage, #b3dda8)");
    expect(cssSource).toContain("var(--coral, #cc9689)");
    expect(cssSource).toContain("var(--surface, #14222e)");
    expect(cssSource).not.toContain("#a3ff12");
    expect(cssSource).not.toContain("lime");
    expect(cssSource).not.toContain("cyan");
  });

  it("keeps 390px containment and ≥44px touch targets in the mobile layer", () => {
    expect(cssSource).toContain("@media (max-width: 640px)");
    expect(cssSource).toMatch(/min-height:\s*44px/);
    expect(cssSource).toMatch(/overflow-wrap:\s*anywhere/);
    expect(cssSource).toMatch(/min-width:\s*0/);
  });
});
