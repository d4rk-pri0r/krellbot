import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
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

describe("StrategyExplanation supported content", () => {
  it("shows the revision id and a saved label", () => {
    render(
      <StrategyExplanation bytes={JSON.stringify(supportedPack)} revisionId="rev-7" />,
    );
    expect(
      screen.getByTestId("strategy-explanation-revision").textContent,
    ).toContain("rev-7");
    expect(screen.getByTestId("strategy-explanation-revision").textContent).toContain(
      "Saved revision",
    );
  });

  it("shows an unsaved label when no revision exists", () => {
    render(<StrategyExplanation bytes={JSON.stringify(supportedPack)} revisionId={null} />);
    expect(screen.getByTestId("strategy-explanation-revision").textContent).toContain(
      "No saved revision yet",
    );
  });

  it("renders readable entry, exit, market, allocation and stop text", () => {
    render(
      <StrategyExplanation bytes={JSON.stringify(supportedPack)} revisionId="rev-7" />,
    );
    expect(screen.getByTestId("strategy-explanation-entry").textContent).toContain(
      'the close price is greater than the indicator "sma20"',
    );
    expect(screen.getByTestId("strategy-explanation-exit").textContent).toContain(
      'the close price is less than the indicator "sma20"',
    );
    expect(screen.getByTestId("strategy-explanation-markets").textContent).toContain(
      "kraken: SUIUSD",
    );
    expect(
      screen.getByTestId("strategy-explanation-allocation").textContent,
    ).toContain("at most 25% of the account");
    expect(screen.getByTestId("strategy-explanation-stop").textContent).toContain(
      "percentage stop 5% below the entry price",
    );
  });

  it("renders metadata as supplied and marks it not verified", () => {
    render(
      <StrategyExplanation bytes={JSON.stringify(supportedPack)} revisionId="rev-7" />,
    );
    const metadata = screen.getByTestId("strategy-explanation").textContent ?? "";
    expect(metadata).toContain("not verified");
    expect(metadata).toContain("Trend follow");
    expect(metadata).toContain("krellbot tests");
    expect(metadata).toContain("1.0.0");
  });

  it("shows not supplied for missing metadata", () => {
    const { origin, author, ...rest } = supportedPack;
    void origin;
    void author;
    render(<StrategyExplanation bytes={JSON.stringify(rest)} revisionId="rev-8" />);
    const metadata = screen.getByTestId("strategy-explanation-metadata").textContent ?? "";
    expect(metadata).toContain("not supplied");
  });

  it("renders grouped conditions with their and/or joiner", () => {
    const grouped = {
      ...supportedPack,
      entry: {
        all: [
          ["close", ">", "sma20"],
          { any: [["close", "crosses_above", "sma20"], ["volume", ">", 100]] },
        ],
      },
    };
    render(<StrategyExplanation bytes={JSON.stringify(grouped)} revisionId="rev-g" />);
    const entry = screen.getByTestId("strategy-explanation-entry").textContent ?? "";
    expect(entry).toContain("All of these are true:");
    expect(entry).toContain("Any of these is true:");
    expect(entry).toContain("crosses above");
    expect(entry).toContain("the volume price is greater than the fixed number 100");
  });

  it("states that costs and results are not provided", () => {
    render(
      <StrategyExplanation bytes={JSON.stringify(supportedPack)} revisionId="rev-7" />,
    );
    const text = screen.getByTestId("strategy-explanation-performance").textContent ?? "";
    expect(text).toContain("not provided");
    expect(text).not.toMatch(/%\s*(return|profit)|win rate/i);
  });
});

describe("StrategyExplanation unsupported and malformed content", () => {
  it("keeps unparseable bytes visibly unknown without crashing", () => {
    render(<StrategyExplanation bytes="not json at all" revisionId="rev-bad" />);
    expect(
      screen.getByTestId("strategy-explanation-unparsed").textContent,
    ).toContain("cannot be explained");
  });

  it("keeps unsupported constructs visibly unknown without crashing", () => {
    render(
      <StrategyExplanation
        bytes={JSON.stringify({
          ...supportedPack,
          entry: ["close", "!=", "sma20"],
          risk: { max_account_pct: 25, stop: { type: "weird" } },
        })}
        revisionId="rev-odd"
      />,
    );
    expect(screen.getByTestId("strategy-explanation-entry").textContent).toContain(
      "unsupported operator",
    );
    expect(screen.getByTestId("strategy-explanation-stop").textContent).toContain(
      "unsupported stop type",
    );
    expect(screen.getByTestId("strategy-explanation-unknowns")).toBeTruthy();
    expect(screen.queryByTestId("strategy-explanation-unparsed")).toBeNull();
  });

  it("renders user-supplied label text without HTML injection", () => {
    render(
      <StrategyExplanation
        bytes={JSON.stringify({
          ...supportedPack,
          label: "<img src=x onerror=alert(1)>Bold",
          origin: "<script>alert('origin')</script>",
        })}
        revisionId="rev-xss"
      />,
    );
    const region = screen.getByTestId("strategy-explanation");
    expect(region.querySelector("img")).toBeNull();
    expect(region.querySelector("script")).toBeNull();
    expect(region.textContent).toContain("<img src=x onerror=alert(1)>Bold");
  });

  it("renders empty bytes without crashing and reports unknowns", () => {
    render(<StrategyExplanation bytes="" revisionId={null} />);
    expect(screen.getByTestId("strategy-explanation-revision").textContent).toContain(
      "No saved revision yet",
    );
    expect(
      screen.getByTestId("strategy-explanation-unparsed").textContent,
    ).toContain("cannot be explained");
  });
});
