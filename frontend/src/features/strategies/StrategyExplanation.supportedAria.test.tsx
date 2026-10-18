import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { explainPack } from "./explainPack";
import { StrategyExplanation } from "./StrategyExplanation";

afterEach(cleanup);

const mixedPack = {
  schema_version: 1,
  id: "trend-follow",
  version: "1.0.0",
  label: "Trend follow",
  author: "krellbot tests",
  origin: "Test fixture.",
  timeframe: "1h",
  indicators: {
    sma20: { fn: "sma", src: "close", len: 20 },
    grail7: { fn: "grail", src: "close", len: 9 },
  },
  entry: ["close", ">", "sma20"],
  exit: ["close", "<", "sma20"],
  risk: { max_account_pct: 25, stop: { type: "pct", pct: 5 } },
  markets: [
    { venue: "kraken", pair: "SUIUSD" },
    { venue: "ftsx", pair: "SUIUSD" },
  ],
};

describe("StrategyExplanation supported/unsupported indicator and market rows", () => {
  it("exposes each indicator row as a listitem whose accessible name states support from the runtime pack", () => {
    const bytes = JSON.stringify(mixedPack);
    render(<StrategyExplanation bytes={bytes} revisionId="rev-7" />);
    const pack = explainPack(bytes, "rev-7");

    const rows = within(screen.getByTestId("strategy-explanation-indicators")).getAllByRole(
      "listitem",
    );
    expect(rows).toHaveLength(pack.indicators.length);
    expect(pack.indicators.some((indicator) => indicator.supported)).toBe(true);
    expect(pack.indicators.some((indicator) => !indicator.supported)).toBe(true);

    rows.forEach((row, index) => {
      const indicator = pack.indicators[index];
      expect(row.tagName).toBe("LI");
      expect(row.getAttribute("role")).toBe("listitem");
      expect(row.getAttribute("data-supported")).toBe(indicator.supported ? "1" : "0");
      expect(row.getAttribute("aria-label")).toBe(
        `${indicator.supported ? "Supported" : "Unsupported"} indicator: ${indicator.text}`,
      );
      expect(row.textContent).toBe(indicator.text);
    });
  });

  it("exposes each market row as a listitem whose accessible name states support from the runtime pack", () => {
    const bytes = JSON.stringify(mixedPack);
    render(<StrategyExplanation bytes={bytes} revisionId="rev-7" />);
    const pack = explainPack(bytes, "rev-7");

    const rows = within(screen.getByTestId("strategy-explanation-markets")).getAllByRole(
      "listitem",
    );
    expect(rows).toHaveLength(pack.markets.length);
    expect(pack.markets.some((market) => market.supported)).toBe(true);
    expect(pack.markets.some((market) => !market.supported)).toBe(true);

    rows.forEach((row, index) => {
      const market = pack.markets[index];
      expect(row.tagName).toBe("LI");
      expect(row.getAttribute("role")).toBe("listitem");
      expect(row.getAttribute("data-supported")).toBe(market.supported ? "1" : "0");
      expect(row.getAttribute("aria-label")).toBe(
        `${market.supported ? "Supported" : "Unsupported"} market: ${market.text}`,
      );
      expect(row.textContent).toBe(market.text);
    });
  });

  it("announces the exact runtime wording for supported and unsupported rows", () => {
    render(<StrategyExplanation bytes={JSON.stringify(mixedPack)} revisionId="rev-7" />);
    const indicators = within(
      screen.getByTestId("strategy-explanation-indicators"),
    ).getAllByRole("listitem");
    const markets = within(screen.getByTestId("strategy-explanation-markets")).getAllByRole(
      "listitem",
    );

    expect(indicators[0].getAttribute("aria-label")).toBe(
      `Supported indicator: ${indicators[0].textContent}`,
    );
    expect(indicators[1].getAttribute("aria-label")).toBe(
      `Unsupported indicator: ${indicators[1].textContent}`,
    );
    expect(markets[0].getAttribute("aria-label")).toBe(
      `Supported market: ${markets[0].textContent}`,
    );
    expect(markets[1].getAttribute("aria-label")).toBe(
      `Unsupported market: ${markets[1].textContent}`,
    );
  });

  it("recomputes every row label when the revision bytes change, including fallback rows", () => {
    const { rerender } = render(
      <StrategyExplanation bytes={JSON.stringify(mixedPack)} revisionId="rev-7" />,
    );
    const before = within(
      screen.getByTestId("strategy-explanation-indicators"),
    ).getAllByRole("listitem");
    expect(before[1].getAttribute("aria-label")).toContain("Unsupported indicator:");

    const replacementBytes = JSON.stringify({
      ...mixedPack,
      indicators: { ema9: { fn: "ema", src: "open", len: 9 } },
      markets: [{ venue: "coinbase", pair: "BTCUSD" }],
    });
    rerender(<StrategyExplanation bytes={replacementBytes} revisionId="rev-8" />);
    const pack = explainPack(replacementBytes, "rev-8");

    const indicatorRows = within(
      screen.getByTestId("strategy-explanation-indicators"),
    ).getAllByRole("listitem");
    expect(indicatorRows).toHaveLength(1);
    expect(indicatorRows[0].getAttribute("aria-label")).toBe(
      `Supported indicator: ${pack.indicators[0].text}`,
    );
    expect(before[1].textContent ?? "").not.toBe(indicatorRows[0].textContent);

    const marketRows = within(
      screen.getByTestId("strategy-explanation-markets"),
    ).getAllByRole("listitem");
    expect(marketRows).toHaveLength(1);
    expect(marketRows[0].getAttribute("aria-label")).toBe(
      `Supported market: ${pack.markets[0].text}`,
    );

    rerender(
      <StrategyExplanation
        bytes={JSON.stringify({ ...mixedPack, indicators: {}, markets: undefined })}
        revisionId="rev-9"
      />,
    );
    const fallbackPack = explainPack(
      JSON.stringify({ ...mixedPack, indicators: {}, markets: undefined }),
      "rev-9",
    );
    const fallbackIndicator = within(
      screen.getByTestId("strategy-explanation-indicators"),
    ).getAllByRole("listitem")[0];
    const fallbackMarket = within(
      screen.getByTestId("strategy-explanation-markets"),
    ).getAllByRole("listitem")[0];
    expect(fallbackIndicator.getAttribute("aria-label")).toBe(
      `Unsupported indicator: ${fallbackPack.indicators[0].text}`,
    );
    expect(fallbackIndicator.getAttribute("data-supported")).toBe("0");
    expect(fallbackMarket.getAttribute("aria-label")).toBe(
      `Unsupported market: ${fallbackPack.markets[0].text}`,
    );
    expect(fallbackMarket.getAttribute("data-supported")).toBe("0");
  });
});
