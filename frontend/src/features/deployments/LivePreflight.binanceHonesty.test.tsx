/**
 * M14.7: live preflight stays honest — no qualified Binance live option.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { LivePreflight } from "./LivePreflight";

afterEach(() => {
  cleanup();
});

describe("LivePreflight Binance honesty", () => {
  it("does not offer binance as a live venue and states paper-only honesty", () => {
    render(<LivePreflight />);
    const select = screen.getByTestId("live-preflight-account") as HTMLSelectElement;
    const values = Array.from(select.querySelectorAll("option")).map(
      (option) => (option as HTMLOptionElement).value,
    );
    expect(values).toEqual(["kraken"]);
    expect(values).not.toContain("binance");
    const note = screen.getByTestId("live-preflight-paper-only-venues");
    expect(note.textContent).toMatch(/paper-only/i);
    expect(note.textContent).toMatch(/does not offer qualified Binance live/i);
    expect(note.textContent).toMatch(/BTCUSDT/);
  });
});
