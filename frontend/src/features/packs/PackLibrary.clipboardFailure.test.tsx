import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { PackLibrary, type PackLibraryClient, type PackRow } from "./PackLibrary";

// Mocks isolate browser permission outcomes and promise ordering, not runtime acceptance.
const ids = ["Local-α/exact", "LOCAL-PAPER-bravo"];
const rows: PackRow[] = ids.map((pack_id) => ({
  pack_id, bucket: "installed", version: "1", permissions: [], rollback_ref: null,
}));
const client: PackLibraryClient = {
  listInstalled: async () => rows,
  rollback: async () => ({ ok: false }),
};
const copy = (i: number) => screen.getByRole("button", { name: `Copy pack_id ${ids[i]}` });
const item = (i: number) => screen.getByTestId(`pack-library-row-${ids[i]}`);
const feedback = (i: number) => screen.getByTestId(`pack-library-copy-feedback-${ids[i]}`);
function clipboard(writeText?: (value: string) => Promise<void>) {
  vi.stubGlobal("navigator", { clipboard: writeText ? { writeText } : undefined });
}
async function mount() {
  const view = render(<PackLibrary client={client} />);
  await screen.findByTestId("pack-library-list");
  return view;
}
function deferred() {
  let resolve!: () => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<void>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it.each(["missing", "rejected", "throws"])("reports %s clipboard failure on its row and clears it after exact-byte retry", async (mode) => {
  if (mode === "missing") clipboard();
  else clipboard(() => {
    const error = new DOMException("Denied", "NotAllowedError");
    if (mode === "throws") throw error;
    return Promise.reject(error);
  });
  await mount();
  fireEvent.click(copy(0));
  const alert = await within(item(0)).findByRole("alert");
  expect(alert.textContent).toContain("Could not copy pack_id");
  expect(alert.textContent).toContain(ids[0]);
  expect(copy(0).getAttribute("aria-describedby")).toBe(alert.id);
  expect(within(item(1)).queryByRole("alert")).toBeNull();
  expect(feedback(0).textContent).toBe("Copy");
  const write = vi.fn(async (_value: string) => {});
  clipboard(write);
  await act(async () => { fireEvent.click(copy(0)); });
  expect(write).toHaveBeenCalledWith(ids[0]);
  expect(within(item(0)).queryByRole("alert")).toBeNull();
  expect(feedback(0).textContent).toBe("Copied");
});

it.each(["success", "failure"])("ignores a late older %s after a newer row succeeds", async (outcome) => {
  const older = deferred();
  clipboard((value) => value === ids[0] ? older.promise : Promise.resolve());
  await mount();
  fireEvent.click(copy(0));
  expect(feedback(0).textContent).toBe("Copy");
  await act(async () => { fireEvent.click(copy(1)); });
  await act(async () => {
    if (outcome === "success") older.resolve();
    else older.reject(new Error("late denial"));
  });
  expect(feedback(1).textContent).toBe("Copied");
  expect(feedback(0).textContent).toBe("Copy");
  expect(screen.queryByRole("alert")).toBeNull();
});

it("clears old success before a pending retry, ignores older same-row success, and cleans timers on unmount", async () => {
  clipboard(async () => {});
  const view = await mount();
  vi.useFakeTimers();
  await act(async () => { fireEvent.click(copy(0)); });
  expect(vi.getTimerCount()).toBe(1);
  const pending = deferred();
  clipboard(() => pending.promise);
  fireEvent.click(copy(0));
  expect(feedback(0).textContent).toBe("Copy");
  expect(vi.getTimerCount()).toBe(0);
  clipboard(async () => { throw new Error("denied"); });
  await act(async () => { fireEvent.click(copy(0)); });
  await act(async () => { pending.resolve(); });
  expect(within(item(0)).getByRole("alert")).toBeDefined();
  expect(feedback(0).textContent).toBe("Copy");
  clipboard(async () => {});
  await act(async () => { fireEvent.click(copy(1)); });
  act(() => { vi.advanceTimersByTime(2000); });
  expect(feedback(1).textContent).toBe("Copy");
  await act(async () => { fireEvent.click(copy(1)); });
  view.unmount();
  expect(vi.getTimerCount()).toBe(0);
});

it("does not schedule success feedback for a write completing after unmount", async () => {
  const pending = deferred();
  clipboard(() => pending.promise);
  const view = await mount();
  vi.useFakeTimers();
  fireEvent.click(copy(0));
  view.unmount();
  await act(async () => { pending.resolve(); });
  expect(vi.getTimerCount()).toBe(0);
});
