import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
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

it("keeps the same polite atomic revision status across saves and replacement imports", () => {
  const validJsonBytes = JSON.stringify(supportedPack);
  const { rerender } = render(
    <StrategyExplanation bytes={validJsonBytes} revisionId={null} />,
  );
  const status = screen.getByTestId("strategy-explanation-revision");

  const expectStatus = (label: string): void => {
    const current = screen.getByTestId("strategy-explanation-revision");
    expect(current).toBe(status);
    expect(current.tagName).toBe("P");
    expect(current.getAttribute("role")).toBe("status");
    expect(current.getAttribute("aria-live")).toBe("polite");
    expect(current.getAttribute("aria-atomic")).toBe("true");
    expect(current.textContent).toBe(label);
  };

  const unsavedLabel =
    "No saved revision yet (showing stored draft content as unsaved)";
  expectStatus(unsavedLabel);

  rerender(<StrategyExplanation bytes={validJsonBytes} revisionId="abc-1" />);
  expectStatus("Saved revision abc-1");

  const importedBytes = JSON.stringify({ ...supportedPack, id: "replacement" });
  rerender(<StrategyExplanation bytes={importedBytes} revisionId="abc-2" />);
  expectStatus("Saved revision abc-2");

  rerender(<StrategyExplanation bytes={importedBytes} revisionId={null} />);
  expectStatus(unsavedLabel);
});
