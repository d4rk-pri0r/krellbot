import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  SavedStrategyLibrary,
  type LibraryClient,
  type OwnedDraftSummary,
  type OwnedRevisionBytes,
} from "./SavedStrategyLibrary";

afterEach(cleanup);

const rows: OwnedDraftSummary[] = ["rev-a", "rev-b"].map((revision_id) => ({
  revision_id, strategy_id: "local-copy-test", parent_revision_id: null,
  state: "draft", runnable: false, created_at: "2026-10-16T10:00:00Z",
  id: "local-copy-test", label: revision_id, pair: "SUIUSD", timeframe: "1h",
}));
const busyLabel = "Copying as new…";

function deferred() {
  let resolve!: (value: OwnedRevisionBytes) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<OwnedRevisionBytes>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

async function mount() {
  const reads = [deferred(), deferred()];
  // Only the I/O boundary is faked, to hold real component reads in flight.
  const client: LibraryClient = {
    listOwned: async () => rows,
    getJson: vi.fn((revisionId: string) => reads[rows.findIndex(row => row.revision_id === revisionId)].promise),
  };
  const onCopyAsNew = vi.fn();
  const onReopen = vi.fn();
  render(<SavedStrategyLibrary client={client} onReopen={onReopen} onCopyAsNew={onCopyAsNew} />);
  const renderedRows = await screen.findAllByTestId("library-row");
  const copies = renderedRows.map(row => within(row).getByTestId<HTMLButtonElement>("library-copy-as-new"));
  const reopens = renderedRows.map(row => within(row).getByRole<HTMLButtonElement>("button", { name: "Reopen" }));
  return { reads, client, onCopyAsNew, onReopen, renderedRows, copies, reopens };
}

function status(row: HTMLElement): HTMLElement {
  const region = row.querySelector<HTMLElement>('[aria-live="polite"]');
  expect(region).not.toBeNull();
  return region!;
}

function idle(button: HTMLButtonElement, row: HTMLElement) {
  expect(button.textContent).toBe("Copy as new");
  expect(button.getAttribute("aria-busy")).not.toBe("true");
  expect(button.disabled).toBe(false);
  expect(status(row).textContent).toBe("");
}

function busy(button: HTMLButtonElement, row: HTMLElement) {
  expect(button.getAttribute("aria-busy")).toBe("true");
  expect(button.textContent).toBe(busyLabel);
  expect(button.disabled).toBe(true);
  expect(status(row).textContent).toBe(busyLabel);
  // A busy ancestor would defer the live announcement until after the read.
  expect(status(row).closest('[aria-busy="true"]')).toBeNull();
}

function loaded(index: number): OwnedRevisionBytes {
  return { revision_id: rows[index].revision_id, state: "draft", bytes: `{"id":"${rows[index].revision_id}"}` };
}

describe("SavedStrategyLibrary copy busy signal", () => {
  it("signals only the focused copy, prevents repeat clicks, and restores on success", async () => {
    const { reads, client, copies, reopens, renderedRows, onCopyAsNew, onReopen } = await mount();
    idle(copies[0], renderedRows[0]);
    idle(copies[1], renderedRows[1]);
    copies[0].focus();
    expect(document.activeElement).toBe(copies[0]);
    fireEvent.click(copies[0]);
    busy(copies[0], renderedRows[0]);
    expect(reopens[0].disabled).toBe(true);
    fireEvent.click(copies[0]);
    fireEvent.click(reopens[0]);
    expect(client.getJson).toHaveBeenCalledExactlyOnceWith("rev-a");
    idle(copies[1], renderedRows[1]);
    copies[1].focus();
    expect(document.activeElement).toBe(copies[1]);
    await act(async () => { reads[0].resolve(loaded(0)); });
    idle(copies[0], renderedRows[0]);
    expect(reopens[0].disabled).toBe(false);
    expect(onCopyAsNew).toHaveBeenCalledExactlyOnceWith(rows[0], loaded(0).bytes);
    expect(onReopen).not.toHaveBeenCalled();
    expect(screen.queryByTestId("library-copy-error")).toBeNull();
  });

  it("keeps other rows usable and settles overlapping row reads independently", async () => {
    const { reads, client, copies, reopens, renderedRows, onCopyAsNew, onReopen } = await mount();
    fireEvent.click(copies[0]);
    expect(copies[1].disabled).toBe(false);
    fireEvent.click(copies[1]);
    busy(copies[0], renderedRows[0]);
    busy(copies[1], renderedRows[1]);
    expect(client.getJson).toHaveBeenCalledTimes(2);
    expect(client.getJson).toHaveBeenNthCalledWith(2, "rev-b");
    await act(async () => { reads[0].resolve(loaded(0)); });
    idle(copies[0], renderedRows[0]);
    busy(copies[1], renderedRows[1]);
    expect(reopens[0].disabled).toBe(true);
    await act(async () => { reads[1].resolve(loaded(1)); });
    idle(copies[1], renderedRows[1]);
    expect(reopens.every(button => !button.disabled)).toBe(true);
    expect(onCopyAsNew).toHaveBeenCalledTimes(2);
    expect(onCopyAsNew).toHaveBeenNthCalledWith(2, rows[1], loaded(1).bytes);
    expect(onReopen).not.toHaveBeenCalled();
  });

  it("clears busy on rejection and preserves the canonical copy error text and alert", async () => {
    const { reads, copies, renderedRows, onCopyAsNew, onReopen } = await mount();
    fireEvent.click(copies[0]);
    busy(copies[0], renderedRows[0]);
    await act(async () => { reads[0].reject(new Error("library open failed: 500")); });
    idle(copies[0], renderedRows[0]);
    const error = screen.getByTestId("library-copy-error");
    expect(error.tagName).toBe("P");
    expect(error.getAttribute("role")).toBe("alert");
    expect(error.textContent).toBe("Copy as new failed: library open failed: 500");
    expect(screen.getAllByTestId("library-row")).toHaveLength(2);
    expect(onCopyAsNew).not.toHaveBeenCalled();
    expect(onReopen).not.toHaveBeenCalled();
  });

  it.each(["Enter", " "])("accepts the native button activation click for %j without a key handler", async (key) => {
    const { reads, client, copies, renderedRows } = await mount();
    const button = copies[0];
    expect(button.tagName).toBe("BUTTON");
    expect(button.type).toBe("button");
    expect(button.tabIndex).toBe(0);
    button.focus();
    fireEvent.keyDown(button, { key });
    fireEvent.keyUp(button, { key });
    expect(client.getJson).not.toHaveBeenCalled();
    // jsdom has no native keyboard default actions; emit the browser's detail=0 click.
    fireEvent.click(button, { detail: 0 });
    busy(button, renderedRows[0]);
    fireEvent.keyDown(button, { key, repeat: true });
    fireEvent.click(button, { detail: 0 });
    expect(client.getJson).toHaveBeenCalledExactlyOnceWith("rev-a");
    await act(async () => { reads[0].resolve(loaded(0)); });
    idle(button, renderedRows[0]);
  });

  it("retains the global Reopen gate without mislabeling a queued copy as busy", async () => {
    const { reads, client, copies, reopens, renderedRows, onReopen, onCopyAsNew } = await mount();
    fireEvent.click(reopens[0]);
    expect(reopens.every(button => button.disabled)).toBe(true);
    expect(copies.every(button => button.disabled)).toBe(true);
    for (let index = 0; index < copies.length; index++) {
      expect(copies[index].textContent).toBe("Copy as new");
      expect(copies[index].getAttribute("aria-busy")).not.toBe("true");
      expect(status(renderedRows[index]).textContent).toBe("");
      fireEvent.click(copies[index]);
    }
    expect(client.getJson).toHaveBeenCalledExactlyOnceWith("rev-a");
    await act(async () => { reads[0].resolve(loaded(0)); });
    expect(onReopen).toHaveBeenCalledExactlyOnceWith(rows[0], loaded(0).bytes);
    expect(onCopyAsNew).not.toHaveBeenCalled();
    idle(copies[0], renderedRows[0]);
  });
});
