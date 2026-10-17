/**
 * ArmedRecordsList — keyboard access slice (APP-BONES-KEYBOARD-01).
 *
 * Rows were already focusable (`tabIndex={0}` + aria-label) but only the
 * pointer could toggle the inline detail. These tests pin the keyboard
 * contract: Enter/Space toggle with native-button semantics (Space
 * canceled so the page never scrolls), pointer and keyboard compose, no
 * paper command is issued by selecting a row, unrelated keys/chords and
 * auto-repeats are ignored. The client is an in-memory vi.fn() fake;
 * mutating methods are vi.fn() spies so the no-command proof is real.
 */

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ArmedRecordsList } from "./ArmedRecordsList";
import type { PaperArmedClient, PaperArmedRecord, PaperArmedView } from "./client";

type SpyClient = PaperArmedClient & Record<
  "pauseEntries" | "resumeEntries" | "disarm" | "arm",
  ReturnType<typeof vi.fn>
>;

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function viewOf(records: PaperArmedRecord[]): PaperArmedView {
  return { schema_version: "1", armed: records.length > 0, records };
}

function record(extra: Partial<PaperArmedRecord> = {}): PaperArmedRecord {
  return {
    venue: "kraken",
    pair: "SUIUSD",
    mode: "paper",
    pack_id: "trend-follow",
    entries_paused: false,
    ...extra,
  };
}

const secondRecord = (): PaperArmedRecord =>
  record({ venue: "coinbase", pair: "BTC-USD", pack_id: "mean-revert", entries_paused: true });

/** Full fake PaperClient: every mutating method is a vi.fn() spy. */
function makeClient(): SpyClient {
  return {
    listArmed: vi.fn().mockResolvedValue(viewOf([record(), secondRecord()])),
    pauseEntries: vi.fn(),
    resumeEntries: vi.fn(),
    disarm: vi.fn(),
    arm: vi.fn(),
  };
}

async function renderReadyRows(client: PaperArmedClient): Promise<HTMLElement[]> {
  render(<ArmedRecordsList client={client} />);
  const rows = await screen.findAllByTestId("paper-armed-row");
  await waitFor(() => { expect(screen.getByTestId("paper-armed-table")).toBeDefined() });
  return rows;
}

function expectNoDetail(): void {
  expect(screen.queryByTestId("paper-armed-detail")).toBeNull();
}

function expectDetailShows(row: PaperArmedRecord): void {
  const detail = screen.getByTestId("paper-armed-detail");
  for (const field of [row.venue, row.pair, row.mode, row.pack_id]) {
    expect(detail.textContent).toContain(field);
  }
}

describe("ArmedRecordsList keyboard toggle — Enter", () => {
  it("Enter opens the focused row's detail; Enter again closes it; focus stays", async () => {
    const rows = await renderReadyRows(makeClient());
    rows[0].focus();
    expectNoDetail();
    fireEvent.keyDown(rows[0], { key: "Enter", code: "Enter" });
    expectDetailShows(record());
    expect(document.activeElement).toBe(screen.getAllByTestId("paper-armed-row")[0]);
    fireEvent.keyDown(rows[0], { key: "Enter", code: "Enter" });
    await waitFor(() => { expectNoDetail() });
  });
  it("Enter on a second row switches the detail to that row's data", async () => {
    const rows = await renderReadyRows(makeClient());
    fireEvent.keyDown(rows[0], { key: "Enter", code: "Enter" });
    fireEvent.keyDown(rows[1], { key: "Enter", code: "Enter" });
    expectDetailShows(secondRecord());
  });
});

describe("ArmedRecordsList keyboard toggle — Space", () => {
  it("Space opens the focused row's detail and Space again closes it", async () => {
    const rows = await renderReadyRows(makeClient());
    expectNoDetail();
    fireEvent.keyDown(rows[0], { key: " ", code: "Space" });
    expectDetailShows(record());
    fireEvent.keyDown(rows[0], { key: " ", code: "Space" });
    await waitFor(() => { expectNoDetail() });
  });
  it("cancels Enter/Space so the page does not scroll; other keys keep defaults", async () => {
    const rows = await renderReadyRows(makeClient());
    // Handled keys are canceled; an un-canceled Space would scroll the page.
    expect(fireEvent.keyDown(rows[0], { key: " ", code: "Space" })).toBe(false);
    expectDetailShows(record());
    expect(fireEvent.keyDown(rows[0], { key: "Enter", code: "Enter" })).toBe(false);
    // Ignored keys keep their default behavior (Tab must still move focus).
    expect(fireEvent.keyDown(rows[0], { key: "Tab" })).toBe(true);
    expect(fireEvent.keyDown(rows[0], { key: "a", code: "KeyA" })).toBe(true);
    await waitFor(() => { expectNoDetail() });
  });
});

describe("ArmedRecordsList keyboard/pointer parity", () => {
  it("pointer click still toggles the same row open and closed", async () => {
    const rows = await renderReadyRows(makeClient());
    expectNoDetail();
    fireEvent.click(rows[0]);
    expectDetailShows(record());
    fireEvent.click(rows[0]);
    await waitFor(() => { expectNoDetail() });
  });
  it("keyboard-open + pointer-close and pointer-open + keyboard-close compose", async () => {
    const rows = await renderReadyRows(makeClient());
    fireEvent.keyDown(rows[1], { key: "Enter", code: "Enter" });
    expectDetailShows(secondRecord());
    fireEvent.click(rows[1]);
    await waitFor(() => { expectNoDetail() });
    fireEvent.click(rows[0]);
    expectDetailShows(record());
    fireEvent.keyDown(rows[0], { key: " ", code: "Space" });
    await waitFor(() => { expectNoDetail() });
  });
  it("the detail still drops when a refresh removes the keyboard-selected row", async () => {
    const listArmed = vi
      .fn<PaperArmedClient["listArmed"]>()
      .mockResolvedValueOnce(viewOf([record()]))
      .mockResolvedValueOnce(viewOf([]));
    const rows = await renderReadyRows({ listArmed } as PaperArmedClient);
    fireEvent.keyDown(rows[0], { key: "Enter", code: "Enter" });
    expectDetailShows(record());
    fireEvent.click(screen.getByRole("button", { name: /refresh/i }));
    await waitFor(() => { expect(screen.getByTestId("paper-armed-empty")).toBeDefined() });
    expectNoDetail();
  });
});

describe("ArmedRecordsList keyboard toggle — no paper command", () => {
  it("toggling by keyboard or pointer sends no pause/resume/disarm/arm", async () => {
    const client = makeClient();
    const rows = await renderReadyRows(client);
    fireEvent.keyDown(rows[0], { key: "Enter", code: "Enter" });
    fireEvent.keyDown(rows[0], { key: "Enter", code: "Enter" });
    fireEvent.click(rows[1]);
    fireEvent.keyDown(rows[1], { key: " ", code: "Space" });
    await waitFor(() => { expectNoDetail() });
    expect(client.listArmed).toHaveBeenCalledTimes(1);
    expect(client.pauseEntries).not.toHaveBeenCalled();
    expect(client.resumeEntries).not.toHaveBeenCalled();
    expect(client.disarm).not.toHaveBeenCalled();
    expect(client.arm).not.toHaveBeenCalled();
  });
});

describe("ArmedRecordsList keyboard toggle — unrelated and repeated keys", () => {
  it("ignores unrelated keys and shortcut chords; shift still activates like a button", async () => {
    const rows = await renderReadyRows(makeClient());
    for (const key of ["Tab", "ArrowDown", "ArrowRight", "Escape", "p", "a"]) {
      fireEvent.keyDown(rows[0], { key });
    }
    fireEvent.keyDown(rows[0], { key: "Enter", code: "Enter", ctrlKey: true });
    fireEvent.keyDown(rows[0], { key: " ", code: "Space", metaKey: true });
    fireEvent.keyDown(rows[0], { key: "Enter", code: "Enter", altKey: true });
    expectNoDetail();
    // Shift is not a shortcut chord: a native button activates on it too.
    fireEvent.keyDown(rows[0], { key: "Enter", code: "Enter", shiftKey: true });
    expectDetailShows(record());
  });
  it("a held-down key (auto-repeat) does not re-toggle the open detail", async () => {
    const rows = await renderReadyRows(makeClient());
    fireEvent.keyDown(rows[0], { key: "Enter", code: "Enter" });
    expectDetailShows(record());
    fireEvent.keyDown(rows[0], { key: "Enter", code: "Enter", repeat: true });
    fireEvent.keyDown(rows[0], { key: " ", code: "Space", repeat: true });
    expectDetailShows(record());
  });
});
