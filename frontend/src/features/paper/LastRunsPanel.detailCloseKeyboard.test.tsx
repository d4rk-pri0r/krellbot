import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LastRunsPanel } from "./LastRunsPanel";
import type { PaperClient, PaperHistory, PaperRun, PaperRunsClient } from "./client";

const run: PaperRun = {
  venue: "kraken", pair: "SUI/USD", pack_id: "local-close-fixture",
  first_ts_ms: 1000, last_ts_ms: 2000, ticks_total: 1,
  last_refusal_code: null, mode: "paper", status: "closed",
  summary: "kraken SUI/USD: 1 tick, 1 fill, closed",
  recent_fills: [{ coid: "local-close-fill", side: "buy", ts_ms: 1000 }],
};
const other: PaperRun = { ...run, pair: "DOTUSD", summary: "kraken DOTUSD: closed" };

// Only the data boundary is in-memory; events, effects, DOM and focus use the shipped component.
async function mount(runs: PaperRun[] = [run, other]) {
  const history: PaperHistory = { schema_version: "1", runs };
  const unexpectedCommand = async (): Promise<never> => { throw new Error("No commands allowed"); };
  const client: PaperClient & PaperRunsClient = {
    listRuns: async () => history,
    getStatus: unexpectedCommand, pauseEntries: unexpectedCommand,
    resumeEntries: unexpectedCommand, disarm: unexpectedCommand,
  };
  const view = render(<LastRunsPanel client={client} />);
  await screen.findByTestId("paper-last-runs-table");
  return view;
}

function open(selected: PaperRun = run) {
  const row = screen.getByTestId(`paper-last-runs-row-${selected.venue}-${selected.pair}`);
  row.focus();
  fireEvent.keyDown(row, { key: "Enter" });
  return row;
}

async function expectOneRemoval(action: () => void) {
  const detail = screen.getByTestId("paper-last-runs-detail");
  let removals = 0;
  const observer = new MutationObserver((records) => {
    for (const record of records) {
      removals += Array.from(record.removedNodes).filter((node) => node === detail).length;
    }
  });
  observer.observe(detail.parentElement!, { childList: true });
  try {
    action();
    await waitFor(() => expect(removals).toBe(1));
    expect(screen.queryByTestId("paper-last-runs-detail")).toBeNull();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(removals).toBe(1);
  } finally {
    observer.disconnect();
  }
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("LastRunsPanel detail close keyboard (KRELL-SIGNAL-20261010)", () => {
  it("names the current summary, advertises Escape, and preserves visible copy and section semantics", async () => {
    await mount();
    for (const selected of [run, other]) {
      open(selected);
      const detail = screen.getByTestId("paper-last-runs-detail");
      const summary = screen.getByTestId("paper-last-runs-detail-summary").textContent;
      const close = within(detail).getByRole("button", { name: `Close run detail for ${summary}` });
      expect(close).toBe(screen.getByTestId("paper-last-runs-detail-close"));
      expect(close.textContent).toBe("Close detail");
      expect(within(detail).getByText("Close detail", { selector: "button" })).toBe(close);
      expect(close.getAttribute("aria-keyshortcuts")).toBe("Escape");
      expect(detail.tagName).toBe("SECTION");
      expect(detail.getAttribute("aria-label")).toBe("Selected paper run detail");
      expect(detail.hasAttribute("aria-modal")).toBe(false);
    }
  });

  it.each(["close", "fill", "summary"])("Escape from %s removes detail once and restores the opening row", async (target) => {
    await mount();
    const row = open();
    const detail = screen.getByTestId("paper-last-runs-detail");
    const focus = target === "close" ? screen.getByTestId("paper-last-runs-detail-close")
      : target === "fill" ? within(detail).getByRole("button", { name: "Copy coid" })
      : screen.getByTestId("paper-last-runs-detail-summary");
    if (target === "summary") focus.tabIndex = -1;
    focus.focus();
    expect(document.activeElement).toBe(focus);
    fireEvent.keyDown(focus, { key: "ArrowDown" });
    expect(screen.getByTestId("paper-last-runs-detail")).toBe(detail);
    await expectOneRemoval(() => { fireEvent.keyDown(focus, { key: "Escape" }); });
    expect(document.activeElement).toBe(row);
    expect(row.getAttribute("aria-expanded")).toBe("false");
  });

  it.each(["Escape", "click"])("%s shares row and filtered-list focus restoration", async (method) => {
    await mount();
    for (const filtered of [false, true]) {
      const row = open(other);
      if (filtered) {
        fireEvent.change(screen.getByTestId("paper-last-runs-filter-query"), { target: { value: "SUI/USD" } });
        expect(row.isConnected).toBe(false);
      }
      const close = screen.getByTestId("paper-last-runs-detail-close");
      close.focus();
      await expectOneRemoval(() => {
        if (method === "Escape") fireEvent.keyDown(close, { key: "Escape" });
        else fireEvent.click(close);
      });
      expect(document.activeElement).toBe(filtered ? screen.getByTestId("paper-last-runs-list-panel") : row);
    }
  });

  it("resolves the full run key when two runs share a venue and pair", async () => {
    const duplicate = { ...run, pack_id: "second-pack", first_ts_ms: 3000, summary: "second run" };
    await mount([run, duplicate]);
    const rows = screen.getAllByTestId(`paper-last-runs-row-${run.venue}-${run.pair}`);
    fireEvent.click(rows[1]!);
    screen.getByTestId("paper-last-runs-detail-close").focus();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(document.activeElement).toBe(rows[1]);
  });

  it("removes its document listener after close and unmount, and leaves other Escape handlers alone", async () => {
    const add = vi.spyOn(document, "addEventListener");
    const remove = vi.spyOn(document, "removeEventListener");
    const view = await mount();
    expect(add.mock.calls.filter(([type]) => type === "keydown")).toHaveLength(0);
    const row = open();
    const registrations = add.mock.calls.filter(([type]) => type === "keydown");
    expect(registrations).toHaveLength(1);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(remove.mock.calls.some(([type, listener]) => type === "keydown" && listener === registrations[0]![1])).toBe(true);
    const outside = document.createElement("button");
    document.body.appendChild(outside);
    let outsideEscapes = 0;
    outside.addEventListener("keydown", (event) => { if (event.key === "Escape") outsideEscapes++; });
    try {
      outside.focus();
      expect(fireEvent.keyDown(outside, { key: "Escape", cancelable: true })).toBe(true);
      expect(outsideEscapes).toBe(1);
      expect(document.activeElement).toBe(outside);
      fireEvent.click(row);
      const last = add.mock.calls.filter(([type]) => type === "keydown").at(-1)!;
      view.unmount();
      expect(remove.mock.calls.some(([type, listener]) => type === "keydown" && listener === last[1])).toBe(true);
      fireEvent.keyDown(outside, { key: "Escape" });
      expect(outsideEscapes).toBe(2);
      expect(document.activeElement).toBe(outside);
    } finally {
      outside.remove();
    }
  });
});
