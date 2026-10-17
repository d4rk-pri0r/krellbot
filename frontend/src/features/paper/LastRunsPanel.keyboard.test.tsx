import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LastRunsPanel } from "./LastRunsPanel";
import type { PaperClient, PaperHistory, PaperRunsClient } from "./client";

afterEach(cleanup);

const history: PaperHistory = {
  schema_version: "1",
  runs: [{
    venue: "kraken", pair: "SUIUSD", pack_id: "local-keyboard-fixture",
    first_ts_ms: 1000, last_ts_ms: 2000, ticks_total: 1,
    last_refusal_code: null, mode: "paper", status: "closed",
    summary: "1 tick, 1 fill, no refusal, closed",
    recent_fills: [{ coid: "local-keyboard-fill", side: "buy", ts_ms: 1000 }],
  }],
};

// Isolate event handling here; runtime acceptance uses the real HTTP client.
function clientFor(data = history): PaperClient & PaperRunsClient {
  return {
    listRuns: vi.fn().mockResolvedValue(data),
    getStatus: vi.fn(), pauseEntries: vi.fn(), resumeEntries: vi.fn(), disarm: vi.fn(),
  };
}

describe("LastRunsPanel keyboard activation", () => {
  it.each(["Enter", " "])("opens summary/fills with %j and cancels default", async (key) => {
    const client = clientFor();
    render(<LastRunsPanel client={client} />);
    const row = await screen.findByRole("row", { name: "Open run detail for kraken SUIUSD" });
    row.focus();
    expect(document.activeElement).toBe(row);
    expect(fireEvent.keyDown(row, { key })).toBe(false);
    const detail = screen.getByTestId("paper-last-runs-detail");
    expect(within(detail).getByText(history.runs[0]!.summary)).toBeDefined();
    expect(within(detail).getByText("local-keyboard-fill")).toBeDefined();
    expect(within(detail).getByRole("table")).toBeDefined();
    expect(client.listRuns).toHaveBeenCalledTimes(1);
    expect(client.pauseEntries).not.toHaveBeenCalled();
    expect(client.resumeEntries).not.toHaveBeenCalled();
    expect(client.disarm).not.toHaveBeenCalled();
  });

  it("ignores unrelated keys without cancelling them and preserves click/close", async () => {
    render(<LastRunsPanel client={clientFor()} />);
    const row = await screen.findByRole("row", { name: "Open run detail for kraken SUIUSD" });
    for (const key of ["Escape", "ArrowDown", "a", "Tab"]) {
      expect(fireEvent.keyDown(row, { key })).toBe(true);
      expect(screen.queryByTestId("paper-last-runs-detail")).toBeNull();
    }
    fireEvent.click(row);
    const close = screen.getByRole("button", { name: "Close detail" });
    close.focus();
    expect(document.activeElement).toBe(close);
    fireEvent.click(close);
    expect(screen.queryByTestId("paper-last-runs-detail")).toBeNull();
  });

  it("opens an empty-fills detail with the keyboard", async () => {
    const run = { ...history.runs[0]!, recent_fills: [], summary: "1 tick, 0 fills, no refusal, closed" };
    render(<LastRunsPanel client={clientFor({ schema_version: "1", runs: [run] })} />);
    fireEvent.keyDown(await screen.findByRole("row", { name: "Open run detail for kraken SUIUSD" }), { key: "Enter" });
    expect(screen.getByTestId("paper-last-runs-fills-empty").textContent).toBe("no fills in this run");
  });

  it("renders no activatable row for empty or failed history", async () => {
    const client = clientFor({ schema_version: "1", runs: [] });
    const view = render(<LastRunsPanel client={client} />);
    await screen.findByTestId("paper-last-runs-empty");
    expect(screen.queryByRole("row")).toBeNull();
    view.unmount();
    const failed = clientFor();
    vi.mocked(failed.listRuns).mockRejectedValue(new Error("paper history refused: csrf required"));
    render(<LastRunsPanel client={failed} />);
    expect((await screen.findByRole("alert")).textContent).toContain("csrf required");
    expect(screen.queryByRole("row")).toBeNull();
    expect(screen.queryByTestId("paper-last-runs-detail")).toBeNull();
  });
});
