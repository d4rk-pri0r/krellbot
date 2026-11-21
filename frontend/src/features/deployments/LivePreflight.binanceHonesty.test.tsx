/**
 * M14.7 / M23.4: live preflight offers kraken + coinbase; Binance stays paper-only.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { LivePreflight } from "./LivePreflight";

afterEach(() => {
  cleanup();
});

describe("LivePreflight Binance honesty", () => {
  it("offers kraken and coinbase live venues and keeps Binance paper-only", () => {
    render(<LivePreflight />);
    const select = screen.getByTestId("live-preflight-account") as HTMLSelectElement;
    const values = Array.from(select.querySelectorAll("option")).map(
      (option) => (option as HTMLOptionElement).value,
    );
    expect(values).toEqual(["kraken", "coinbase"]);
    expect(values).not.toContain("binance");
    expect(values).not.toContain("gate");
    const note = screen.getByTestId("live-preflight-paper-only-venues");
    expect(note.textContent).toMatch(/paper-only/i);
    expect(note.textContent).toMatch(/do not claim qualified Binance live/i);
    expect(note.textContent).toMatch(/BTCUSDT/);
    expect(note.textContent).toMatch(/coinbase/i);
  });
});
