/**
 * Strategy explanation Signal presentation slice — KRELL-SIGNAL-20261010.
 *
 * Pins the scoped Signal presentation of the persistent strategy
 * explanation card mounted beside the open Editor in the Workstation
 * Strategies view: scoped `kbot-feature__strategy-explanation-*` class
 * names on navy/seafoam/sage tokens with Manrope inherited from the host,
 * while preserving every existing data-testid, the parsed/empty/unparsed
 * states and the reachable StrategyExplanationCsvExport child.
 *
 * The scoped-class assertions are RED on the flat pre-signal base; the
 * preserved-behavior guards prove the change is presentation only.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";
import { StrategyExplanation } from "./StrategyExplanation";

afterEach(cleanup);

const supportedPack = {
  schema_version: 1,
  id: "trend-follow",
  version: "1.0.0",
  label: "Trend follow",
  author: "krellbot tests",
  origin: "Test fixture.",
  timeframe: "1h",
  indicators: { sma20: { fn: "sma", src: "close", len: 20 } },
  entry: ["close", ">", "sma20"],
  exit: ["close", "<", "sma20"],
  risk: { max_account_pct: 25, stop: { type: "pct", pct: 5 } },
  markets: [{ venue: "kraken", pair: "SUIUSD" }],
};

const supportedBytes = JSON.stringify(supportedPack);

describe("StrategyExplanation signal slice — scoped presentation", () => {
  it("roots the card on the scoped kbot-feature class and keeps its region semantics", () => {
    render(<StrategyExplanation bytes={supportedBytes} revisionId="rev-7" />);
    const region = screen.getByTestId("strategy-explanation");
    expect(region.getAttribute("class")).toContain(
      "kbot-feature__strategy-explanation-root",
    );
    expect(region.getAttribute("role")).toBe("region");
    expect(region.getAttribute("aria-label")).toBe("Strategy explanation");
  });

  it("scopes the card chrome classes instead of unstyled bare elements", () => {
    render(<StrategyExplanation bytes={supportedBytes} revisionId="rev-7" />);
    const root = screen.getByTestId("strategy-explanation");
    expect(
      root.querySelector(".kbot-feature__strategy-explanation-head"),
    ).not.toBeNull();
    expect(
      root.querySelector(".kbot-feature__strategy-explanation-title")
        ?.textContent,
    ).toContain("What this revision trades");
    expect(
      root.querySelector(".kbot-feature__strategy-explanation-revision"),
    ).toBe(screen.getByTestId("strategy-explanation-revision"));
    expect(
      root.querySelector(".kbot-feature__strategy-explanation-metadata"),
    ).toBe(screen.getByTestId("strategy-explanation-metadata"));
    expect(
      root.querySelector(".kbot-feature__strategy-explanation-section"),
    ).not.toBeNull();
  });

  it("keeps the truthful performance disclaimer inside the styled card", () => {
    render(<StrategyExplanation bytes={supportedBytes} revisionId="rev-7" />);
    const root = screen.getByTestId("strategy-explanation");
    const notice = root.querySelector(
      ".kbot-feature__strategy-explanation-performance",
    );
    expect(notice).toBe(screen.getByTestId("strategy-explanation-performance"));
    expect(notice?.textContent).toContain("not provided");
    expect(notice?.textContent).not.toMatch(/%\s*(return|profit)|win rate/i);
  });
});

describe("StrategyExplanation signal slice — preserved states", () => {
  it("still renders the parsed explanation with every existing data-testid", () => {
    render(<StrategyExplanation bytes={supportedBytes} revisionId="rev-7" />);
    for (const testId of [
      "strategy-explanation",
      "strategy-explanation-revision",
      "strategy-explanation-metadata",
      "strategy-explanation-indicators",
      "strategy-explanation-entry",
      "strategy-explanation-exit",
      "strategy-explanation-markets",
      "strategy-explanation-allocation",
      "strategy-explanation-stop",
      "strategy-explanation-performance",
    ]) {
      expect(screen.getByTestId(testId)).toBeDefined();
    }
    expect(
      screen.getByTestId("strategy-explanation-entry").textContent,
    ).toContain('the close price is greater than the indicator "sma20"');
  });

  it("keeps the honest empty/unparsed state visible when nothing is saved", () => {
    render(<StrategyExplanation bytes="" revisionId={null} />);
    expect(
      screen.getByTestId("strategy-explanation-revision").textContent,
    ).toContain("No saved revision yet");
    const unparsed = screen.getByTestId("strategy-explanation-unparsed");
    expect(unparsed.textContent).toContain("cannot be explained");
    expect(unparsed.getAttribute("class")).toContain(
      "kbot-feature__strategy-explanation-unparsed",
    );
    expect(screen.queryByTestId("strategy-explanation-metadata")).toBeNull();
  });

  it("styles the unparsed notice through the same scoped root, not a new global class", () => {
    render(<StrategyExplanation bytes="not json at all" revisionId="rev-bad" />);
    const root = screen.getByTestId("strategy-explanation");
    expect(root.getAttribute("class")).toContain(
      "kbot-feature__strategy-explanation-root",
    );
    expect(
      root.querySelector(".kbot-feature__strategy-explanation-unparsed"),
    ).not.toBeNull();
  });

  it("keeps the unknowns notice scoped and present for unsupported constructs", () => {
    render(
      <StrategyExplanation
        bytes={JSON.stringify({
          ...supportedPack,
          entry: ["close", "!=", "sma20"],
        })}
        revisionId="rev-odd"
      />,
    );
    const unknowns = screen.getByTestId("strategy-explanation-unknowns");
    expect(unknowns.getAttribute("class")).toContain(
      "kbot-feature__strategy-explanation-unknowns",
    );
  });
});

describe("StrategyExplanation signal slice — CSV export child", () => {
  it("keeps the CSV export button reachable and enabled on parsed content", () => {
    render(<StrategyExplanation bytes={supportedBytes} revisionId="rev-7" />);
    const button = screen.getByTestId(
      "strategies-explanation-csv-export",
    ) as HTMLButtonElement;
    expect(button.textContent).toBe("Export explanation");
    expect(button.disabled).toBe(false);
    expect(
      screen
        .getByTestId("strategy-explanation")
        .querySelector(".kbot-feature__strategy-explanation-actions")
        ?.contains(button),
    ).toBe(true);
  });

  it("keeps the CSV export button disabled, not hidden, for unparsed bytes", () => {
    render(<StrategyExplanation bytes="not json at all" revisionId="rev-bad" />);
    const button = screen.getByTestId(
      "strategies-explanation-csv-export",
    ) as HTMLButtonElement;
    expect(button).toBeDefined();
    expect(button.disabled).toBe(true);
  });

  it("still downloads the explanation CSV when clicked", async () => {
    const createObjectURL = vi
      .spyOn(URL, "createObjectURL")
      .mockReturnValue("blob:test-url");
    const revokeObjectURL = vi
      .spyOn(URL, "revokeObjectURL")
      .mockImplementation(() => {});
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    try {
      render(<StrategyExplanation bytes={supportedBytes} revisionId="rev-7" />);
      fireEvent.click(screen.getByTestId("strategies-explanation-csv-export"));
      expect(createObjectURL).toHaveBeenCalledTimes(1);
      const blob = createObjectURL.mock.calls[0][0] as Blob;
      expect(await blob.text()).toContain("section,key,value");
    } finally {
      click.mockRestore();
      createObjectURL.mockRestore();
      revokeObjectURL.mockRestore();
    }
  });
});

describe("StrategyExplanation signal slice — stylesheet contract", () => {
  const stylesDir = dirname(fileURLToPath(import.meta.url));
  let css = "";
  const readCss = (): string => {
    if (css === "") {
      css = readFileSync(join(stylesDir, "StrategyExplanation.signal.css"), "utf8");
    }
    return css;
  };

  it("is root-scoped to the card and consumes the approved named tokens", () => {
    const css = readCss();
    expect(css).toMatch(/^\.kbot-feature__strategy-explanation-root\b/m);
    // This card has no affirmative "go" action of its own (the CSV export
    // is a secondary utility control), so --sage is deliberately reserved
    // for the editor's primary actions — the same discipline the accepted
    // PackLibrary card follows.
    for (const token of [
      "--navy",
      "--surface",
      "--panel",
      "--line",
      "--text",
      "--muted",
      "--seafoam",
      "--coral",
    ]) {
      expect(css).toContain(`var(${token}`);
    }
    expect(css).toContain('var(--font-ui, "Manrope"');
  });

  it("does not reintroduce the retired neon palette or remote fonts", () => {
    const css = readCss();
    for (const legacy of ["#07090d", "#5ce1ff", "#c6ff3d"]) {
      expect(css.toLowerCase()).not.toContain(legacy);
    }
    expect(css).not.toMatch(/@import|https?:\/\//);
  });

  it("keeps narrow surfaces reachable with 44px targets and contained content", () => {
    const css = readCss();
    const mediaIndex = css.indexOf("@media");
    expect(mediaIndex).toBeGreaterThan(-1);
    const narrow = css.slice(mediaIndex);
    expect(narrow).toMatch(/max-width:\s*640px/);
    expect(narrow).toMatch(/min-height:\s*44px/);
    // Long revision ids / labels must not widen the page.
    expect(css).toMatch(/overflow-wrap:\s*anywhere/);
    expect(css).toMatch(/max-width:\s*100%/);
  });
});
