import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { LastRunsPanel } from "./LastRunsPanel";
import type { PaperClient, PaperHistory, PaperRunsClient } from "./client";

afterEach(cleanup);

const history: PaperHistory = {
  schema_version: "1",
  runs: ["SUIUSD", "DOTUSD"].map((pair) => ({
    venue: "kraken", pair, pack_id: "disclosure-fixture",
    first_ts_ms: 1000, last_ts_ms: 2000, ticks_total: 1,
    last_refusal_code: null, mode: "paper", status: "closed",
    summary: "1 tick, 0 fills, no refusal, closed", recent_fills: [],
  })),
};

// Only the transport is substituted; selection, events and DOM are production code.
function clientFor(): PaperClient & PaperRunsClient {
  return {
    listRuns: async () => history,
    getStatus: async () => { throw new Error("Unexpected status read"); },
    pauseEntries: async () => { throw new Error("Unexpected mutation"); },
    resumeEntries: async () => { throw new Error("Unexpected mutation"); },
    disarm: async () => { throw new Error("Unexpected mutation"); },
  };
}

function controlledId(row: HTMLElement): string {
  const id = row.getAttribute("aria-controls");
  expect(id).toBeTruthy();
  return id!;
}

function expectExpanded(row: HTMLElement, id: string): HTMLElement {
  expect(row.getAttribute("aria-expanded")).toBe("true");
  expect(row.getAttribute("aria-controls")).toBe(id);
  const detail = screen.getByRole("region", { name: "Selected paper run detail" });
  expect(document.getElementById(id)).toBe(detail);
  expect(detail).toBe(screen.getByTestId("paper-last-runs-detail"));
  return detail;
}

describe("LastRunsPanel disclosure ARIA", () => {
  it.each(["Enter", " "])("announces %j expansion on the focused row and re-collapse after close", async (key) => {
    render(<LastRunsPanel client={clientFor()} />);
    const row = await screen.findByRole("row", { name: "Open run detail for kraken SUIUSD" });
    const id = controlledId(row);
    expect(row.getAttribute("aria-expanded")).toBe("false");
    expect(document.getElementById(id)).toBeNull();
    row.focus();
    expect(fireEvent.keyDown(row, { key })).toBe(false);
    const detail = expectExpanded(row, id);
    expect(document.activeElement).toBe(row);
    expect(within(detail).getByTestId("paper-last-runs-fills-empty").textContent).toBe("no fills in this run");
    fireEvent.keyDown(row, { key });
    expect(expectExpanded(row, id)).toBe(detail);
    fireEvent.click(screen.getByTestId("paper-last-runs-detail-close"));
    expect(row.getAttribute("aria-expanded")).toBe("false");
    expect(row.getAttribute("aria-controls")).toBe(id);
    expect(document.getElementById(id)).toBeNull();
    expect(screen.queryByTestId("paper-last-runs-detail")).toBeNull();
    fireEvent.keyDown(row, { key: "Enter" });
    expectExpanded(row, id);
  });

  it("tracks selection across rows without changing row/table semantics or click idempotence", async () => {
    render(<LastRunsPanel client={clientFor()} />);
    const first = await screen.findByRole("row", { name: "Open run detail for kraken SUIUSD" });
    const second = screen.getByRole("row", { name: "Open run detail for kraken DOTUSD" });
    expect(first.tagName).toBe("TR");
    expect(first.tabIndex).toBe(0);
    expect(second.getAttribute("aria-expanded")).toBe("false");
    const id = controlledId(first);
    fireEvent.keyDown(first, { key: "ArrowDown" });
    expect(first.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByTestId("paper-last-runs-detail")).toBeNull();
    fireEvent.click(first);
    const detail = expectExpanded(first, id);
    fireEvent.click(first);
    expect(expectExpanded(first, id)).toBe(detail);
    fireEvent.click(second);
    expectExpanded(second, id);
    expect(first.getAttribute("aria-expanded")).toBe("false");
    expect(second.classList.contains("kbot-paper-runs__row--selected")).toBe(true);
    expect(first.classList.contains("kbot-paper-runs__row--selected")).toBe(false);
  });

  it("uses distinct control targets for independently mounted panels", async () => {
    render(<><LastRunsPanel client={clientFor()} /><LastRunsPanel client={clientFor()} /></>);
    const rows = await screen.findAllByRole("row", { name: "Open run detail for kraken SUIUSD" });
    expect(controlledId(rows[0]!)).not.toBe(controlledId(rows[1]!));
  });
});
