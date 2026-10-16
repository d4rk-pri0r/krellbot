import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { LastRunsPanel } from "./LastRunsPanel";
import type { PaperClient, PaperRun, PaperRunsClient } from "./client";

afterEach(cleanup);

const runs: PaperRun[] = [
  { venue: "kraken", pair: "SUIUSD", pack_id: "Alpha-Pack", status: "active", summary: "Momentum rising" },
  { venue: "coinbase", pair: "BTCUSD", pack_id: "Beta-Pack", status: "closed", summary: "Target reached" },
  { venue: "kraken", pair: "DOTUSD", pack_id: "Gamma-Pack", status: "failed", summary: "Budget exhausted" },
  { venue: "coinbase", pair: "ETHUSD", pack_id: "Delta-Pack", status: "active", summary: "Momentum falling" },
].map((row, index) => ({
  ...row, first_ts_ms: index + 1, last_ts_ms: index + 2, ticks_total: 1,
  last_refusal_code: null, mode: "paper", recent_fills: [],
}));

async function mount(data = runs) {
  let reads = 0;
  const unexpected = async (): Promise<never> => { throw new Error("Unexpected command/status read"); };
  // Only the transport boundary is substituted; exercise the real panel predicate and DOM.
  const client: PaperClient & PaperRunsClient = {
    listRuns: async () => { reads += 1; return { schema_version: "1", runs: data }; },
    getStatus: unexpected, pauseEntries: unexpected, resumeEntries: unexpected, disarm: unexpected,
  };
  render(<LastRunsPanel client={client} />);
  await screen.findByTestId(data.length ? "paper-last-runs-table" : "paper-last-runs-empty");
  return () => reads;
}

const venue = () => screen.getByRole("combobox", { name: "Filter runs by venue" });
const status = () => screen.getByRole("combobox", { name: "Filter runs by status" });
const query = () => screen.getByRole("textbox", { name: "Search runs by pack, pair or summary" });
const rows = () => screen.queryAllByRole("row", { name: /^Open run detail/ });
const change = (control: HTMLElement, value: string) => fireEvent.change(control, { target: { value } });
const options = (control: HTMLElement) => within(control).getAllByRole("option").map((node) => (node as HTMLOptionElement).value);

describe("LastRunsPanel read-only filters", () => {
  it("derives unique venue/status options from underlying runs and narrows venue rows", async () => {
    await mount();
    expect(options(venue())).toEqual(["", "kraken", "coinbase"]);
    expect(options(status())).toEqual(["", "active", "closed", "failed"]);
    expect(screen.queryByTestId("paper-last-runs-filter-clear")).toBeNull();
    change(venue(), "kraken");
    expect(rows()).toHaveLength(2);
    expect(rows().every((row) => row.querySelector("td")?.textContent === "kraken")).toBe(true);
    expect(options(status())).toEqual(["", "active", "closed", "failed"]);
  });

  it.each([
    ["  aLPHa-pACK  ", "SUIUSD"], ["btCuSd", "BTCUSD"], ["bUdGeT", "DOTUSD"],
  ])("searches normalized pack OR pair OR summary for %j", async (text, pair) => {
    await mount();
    change(query(), text);
    expect(rows()).toHaveLength(1);
    expect(rows()[0]?.textContent).toContain(pair);
  });

  it("matches no unrelated field and treats whitespace as an empty search", async () => {
    await mount();
    change(query(), "kraken");
    expect(rows()).toHaveLength(0);
    change(query(), "   ");
    expect(rows()).toHaveLength(4);
    expect(screen.getByTestId("paper-last-runs-filter-clear")).toBeDefined();
  });

  it("narrows status and combines all dimensions with AND semantics", async () => {
    await mount();
    change(status(), "active");
    expect(rows()).toHaveLength(2);
    change(venue(), "kraken");
    change(query(), "momentum");
    expect(rows()).toHaveLength(1);
    expect(rows()[0]?.textContent).toContain("SUIUSD");
    change(query(), "falling");
    expect(rows()).toHaveLength(0);
  });

  it("clears all dimensions, restores rows, hides Clear and never re-fetches or mutates source", async () => {
    const before = JSON.stringify(runs);
    const reads = await mount();
    change(venue(), "kraken");
    change(status(), "failed");
    change(query(), "budget");
    expect(rows()).toHaveLength(1);
    fireEvent.click(screen.getByTestId("paper-last-runs-filter-clear"));
    expect(rows()).toHaveLength(4);
    expect((venue() as HTMLSelectElement).value).toBe("");
    expect((status() as HTMLSelectElement).value).toBe("");
    expect((query() as HTMLInputElement).value).toBe("");
    expect(screen.queryByTestId("paper-last-runs-filter-clear")).toBeNull();
    expect(reads()).toBe(1);
    expect(JSON.stringify(runs)).toBe(before);
  });

  it("distinguishes no matches from no underlying runs and keeps the total chip honest", async () => {
    await mount();
    change(query(), "absent-substring");
    expect(rows()).toHaveLength(0);
    expect(screen.getByTestId("paper-last-runs-filter-empty").textContent).toBe("No runs match the current filters.");
    expect(screen.queryByTestId("paper-last-runs-empty")).toBeNull();
    expect(screen.getByTestId("paper-last-runs-count").textContent).toBe("4 runs");
    fireEvent.click(screen.getByTestId("paper-last-runs-filter-clear"));
    expect(screen.queryByTestId("paper-last-runs-filter-empty")).toBeNull();
  });

  it("keeps singular total and only the statuses actually present", async () => {
    await mount([runs[0]!]);
    expect(options(status())).toEqual(["", "active"]);
    change(query(), "absent");
    expect(screen.getByTestId("paper-last-runs-count").textContent).toBe("1 run");
  });

  it("preserves the original zero-runs sentence, not the filtered-empty sentence", async () => {
    await mount([]);
    change(query(), "anything");
    expect(screen.getByTestId("paper-last-runs-empty").textContent).toBe("No paper runs yet");
    expect(screen.queryByTestId("paper-last-runs-filter-empty")).toBeNull();
    expect(options(venue())).toEqual([""]);
    expect(options(status())).toEqual([""]);
  });
});
