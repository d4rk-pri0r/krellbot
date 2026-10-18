import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ArmedRecordsList } from "./ArmedRecordsList";
import type { PaperArmedClient, PaperArmedRecord, PaperArmedView, PaperClient, PaperCommandResult } from "./client";

afterEach(cleanup);

const first: PaperArmedRecord = {
  venue: "kraken", pair: "SUIUSD", mode: "paper", pack_id: "trend-follow", entries_paused: false,
};
const second: PaperArmedRecord = {
  ...first, venue: "coinbase", pair: "BTC-USD", entries_paused: true,
};
const viewOf = (records: PaperArmedRecord[]): PaperArmedView => ({ schema_version: "1", armed: records.length > 0, records });

// Stub only the transport: the real component handles selection, actions, errors and refresh.
function combinedClient(records = [first, second]) {
  return {
    listArmed: vi.fn<PaperArmedClient["listArmed"]>().mockResolvedValue(viewOf(records)),
    getStatus: vi.fn<PaperClient["getStatus"]>().mockResolvedValue({ schema_version: "1", armed: true }),
    pauseEntries: vi.fn<PaperClient["pauseEntries"]>().mockResolvedValue({ ok: true }),
    resumeEntries: vi.fn<PaperClient["resumeEntries"]>().mockResolvedValue({ ok: true }),
    disarm: vi.fn<PaperClient["disarm"]>().mockResolvedValue({ ok: true }),
  } satisfies PaperArmedClient & PaperClient;
}

async function openRow(index = 0) {
  const rows = await screen.findAllByTestId("paper-armed-row");
  rows[index].focus();
  fireEvent.keyDown(rows[index], { key: "Enter" });
  return screen.getByTestId("paper-armed-detail");
}

function button(action: "pause" | "resume" | "disarm") {
  return screen.getByTestId(`paper-armed-row-${action}`) as HTMLButtonElement;
}

describe("ArmedRecordsList row actions", () => {
  it.each([false, true])("exposes native, labelled controls matching entries_paused=%s", async (paused) => {
    render(<ArmedRecordsList client={combinedClient([{ ...first, entries_paused: paused }])} />);
    const detail = await openRow();
    for (const [action, label] of [["pause", "Pause entries on"], ["resume", "Resume entries on"], ["disarm", "Disarm"]] as const) {
      const control = button(action);
      expect(control.tagName).toBe("BUTTON");
      expect(control.type).toBe("button");
      expect(control.tabIndex).toBe(0);
      expect(within(detail).getByRole("button", { name: `${label} ${first.venue} ${first.pair}` })).toBe(control);
    }
    expect(button("pause").disabled).toBe(paused);
    expect(button("resume").disabled).toBe(!paused);
    expect(button("disarm").disabled).toBe(false);
  });

  it.each([
    ["pause", "pauseEntries", 0],
    ["resume", "resumeEntries", 1],
    ["disarm", "disarm", 1],
  ] as const)("%s targets only the selected run and refreshes exactly once on success", async (action, method, index) => {
    const client = combinedClient();
    let resolve!: (value: PaperCommandResult) => void;
    client[method].mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
    client.listArmed.mockResolvedValueOnce(viewOf([first, second])).mockResolvedValueOnce(viewOf(index === 0 ? [second] : [first]));
    render(<ArmedRecordsList client={client} />);
    await openRow(index);
    fireEvent.click(button(action));
    expect(client[method]).toHaveBeenCalledExactlyOnceWith([first, second][index].venue, [first, second][index].pair);
    for (const kind of ["pause", "resume", "disarm"] as const) expect(button(kind).disabled).toBe(true);
    fireEvent.click(button(action));
    expect(client[method]).toHaveBeenCalledTimes(1);
    await act(async () => { resolve({ ok: true }); });
    await waitFor(() => expect(screen.queryByTestId("paper-armed-detail")).toBeNull());
    expect(client.listArmed).toHaveBeenCalledTimes(2);
    const rows = screen.getAllByTestId("paper-armed-row");
    expect(rows).toHaveLength(1);
    expect(rows[0].getAttribute("data-venue")).toBe(index === 0 ? second.venue : first.venue);
  });

  it.each([
    ["pause", "pauseEntries", 0, "Pause entries", "Entries active"],
    ["resume", "resumeEntries", 1, "Resume entries", "Entries paused"],
    ["disarm", "disarm", 1, "Disarm", "Entries paused"],
  ] as const)("keeps the selected row and chip after %s throws, and allows retry", async (action, method, index, label, chip) => {
    const client = combinedClient();
    client[method].mockRejectedValueOnce(new Error("request failed: 503"));
    render(<ArmedRecordsList client={client} />);
    await openRow(index);
    const status = screen.getByTestId(`paper-armed-status-${[first, second][index].venue}-${[first, second][index].pair}`);
    const previousClass = status.className;
    fireEvent.click(button(action));
    const error = await screen.findByTestId("paper-armed-row-action-error");
    expect(error.tagName).toBe("P");
    expect(error.getAttribute("role")).toBe("alert");
    expect(error.textContent).toBe(`${label} failed: request failed: 503`);
    expect(screen.getByTestId("paper-armed-detail").contains(error)).toBe(true);
    expect(screen.getAllByTestId("paper-armed-row")).toHaveLength(2);
    expect(status.textContent).toBe(chip);
    expect(status.className).toBe(previousClass);
    expect(button(action).disabled).toBe(false);
    expect(client.listArmed).toHaveBeenCalledTimes(1);
    let resolve!: (value: PaperCommandResult) => void;
    client[method].mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
    fireEvent.click(button(action));
    expect(screen.queryByTestId("paper-armed-row-action-error")).toBeNull();
    await act(async () => { resolve({ ok: true }); });
    expect(client[method]).toHaveBeenCalledTimes(2);
  });

  it("renders the actual refusal message without collapsing or refreshing", async () => {
    const client = combinedClient();
    client.pauseEntries.mockResolvedValueOnce({ ok: false, code: "conflict", message: "run not owned" });
    render(<ArmedRecordsList client={client} />);
    await openRow();
    fireEvent.click(button("pause"));
    expect((await screen.findByRole("alert")).textContent).toBe("Pause entries failed: run not owned");
    expect(client.listArmed).toHaveBeenCalledTimes(1);
    expect(screen.getAllByTestId("paper-armed-row")).toHaveLength(2);
  });

  it("does not show one run's error on another run's detail", async () => {
    const client = combinedClient();
    client.pauseEntries.mockRejectedValueOnce(new Error("offline"));
    render(<ArmedRecordsList client={client} />);
    await openRow();
    fireEvent.click(button("pause"));
    await screen.findByTestId("paper-armed-row-action-error");
    fireEvent.keyDown(screen.getAllByTestId("paper-armed-row")[1], { key: " " });
    expect(screen.getByTestId("paper-armed-detail").textContent).toContain(second.pair);
    expect(screen.queryByTestId("paper-armed-row-action-error")).toBeNull();
  });

  it("refreshes the confirmed pause chip before offering resume", async () => {
    const client = combinedClient([first]);
    client.listArmed.mockResolvedValueOnce(viewOf([first])).mockResolvedValueOnce(viewOf([{ ...first, entries_paused: true }]));
    render(<ArmedRecordsList client={client} />);
    await openRow();
    fireEvent.click(button("pause"));
    await waitFor(() => expect(screen.queryByTestId("paper-armed-detail")).toBeNull());
    expect(screen.getByTestId(`paper-armed-status-${first.venue}-${first.pair}`).textContent).toBe("Entries paused");
    await openRow();
    expect(button("pause").disabled).toBe(true);
    expect(button("resume").disabled).toBe(false);
    expect(client.listArmed).toHaveBeenCalledTimes(2);
  });

  it("does not leak a late failure into another selected run", async () => {
    const client = combinedClient();
    let reject!: (reason: Error) => void;
    client.pauseEntries.mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail; }));
    render(<ArmedRecordsList client={client} />);
    await openRow();
    fireEvent.click(button("pause"));
    fireEvent.keyDown(screen.getAllByTestId("paper-armed-row")[1], { key: "Enter" });
    await act(async () => { reject(new Error("late offline")); });
    expect(screen.queryByTestId("paper-armed-row-action-error")).toBeNull();
    expect(screen.getByTestId("paper-armed-detail").textContent).toContain(second.pair);
    fireEvent.keyDown(screen.getAllByTestId("paper-armed-row")[0], { key: "Enter" });
    expect(screen.getByTestId("paper-armed-row-action-error").textContent).toBe("Pause entries failed: late offline");
  });

  it("distinguishes a confirmed action from a failed list readback", async () => {
    const client = combinedClient();
    client.listArmed.mockResolvedValueOnce(viewOf([first, second])).mockRejectedValueOnce(new Error("readback failed: 503"));
    render(<ArmedRecordsList client={client} />);
    await openRow();
    fireEvent.click(button("disarm"));
    expect((await screen.findByTestId("paper-armed-refresh-error")).textContent).toBe("readback failed: 503");
    expect(screen.queryByTestId("paper-armed-row-action-error")).toBeNull();
    expect(screen.queryByTestId("paper-armed-detail")).toBeNull();
    expect(screen.getAllByTestId("paper-armed-row")).toHaveLength(2);
    expect(client.disarm).toHaveBeenCalledExactlyOnceWith(first.venue, first.pair);
    expect(client.listArmed).toHaveBeenCalledTimes(2);
  });

  it("preserves Enter/Space toggling and refresh failure reporting", async () => {
    const client = combinedClient();
    client.listArmed.mockResolvedValueOnce(viewOf([first])).mockRejectedValueOnce(new Error("list failed: 500"));
    render(<ArmedRecordsList client={client} />);
    await openRow();
    const row = screen.getByTestId("paper-armed-row");
    fireEvent.keyDown(row, { key: " " });
    expect(screen.queryByTestId("paper-armed-detail")).toBeNull();
    fireEvent.keyDown(row, { key: " " });
    expect(screen.getByTestId("paper-armed-detail")).toBeDefined();
    fireEvent.keyDown(row, { key: "Enter" });
    expect(screen.queryByTestId("paper-armed-detail")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect((await screen.findByTestId("paper-armed-refresh-error")).textContent).toBe("list failed: 500");
    expect(screen.getByTestId("paper-armed-row")).toBe(row);
    expect(client.listArmed).toHaveBeenCalledTimes(2);
  });
});
