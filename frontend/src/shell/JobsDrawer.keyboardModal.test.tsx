import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { JobsDrawer, type JobRow } from "./JobsDrawer";

afterEach(cleanup);

function open(client: { list(): Promise<JobRow[]> }) {
  const view = render(<><button>Underlying</button><JobsDrawer client={client} /></>);
  const trigger = screen.getByRole("button", { name: "Jobs" });
  trigger.focus();
  fireEvent.click(trigger);
  return { ...view, trigger, close: screen.getByRole("button", { name: "Close jobs drawer" }) };
}

function tabFrom(element: HTMLElement, shiftKey = false) {
  element.focus();
  return fireEvent.keyDown(element, { key: "Tab", shiftKey });
}

describe("JobsDrawer keyboard modal lifecycle", () => {
  it("transfers focus while loading, wraps enabled controls, and restores on Escape", () => {
    const { trigger, close } = open({ list: () => new Promise(() => {}) });
    expect(document.activeElement).toBe(close);
    expect(screen.getByTestId("jobs-loading")).not.toBeNull();
    const refresh = screen.getByTestId("jobs-refresh");
    expect(tabFrom(close, true)).toBe(false);
    expect(document.activeElement).toBe(refresh);
    expect(tabFrom(refresh)).toBe(false);
    expect(document.activeElement).toBe(close);
    fireEvent.keyDown(close, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("contains empty state focus and restores on Close", async () => {
    const { trigger, close } = open({ list: async () => [] });
    await screen.findByTestId("jobs-empty");
    expect((screen.getByTestId("jobs-drawer-csv-export") as HTMLButtonElement).disabled).toBe(true);
    const underlying = screen.getByRole("button", { name: "Underlying" });
    underlying.focus();
    expect(document.activeElement).toBe(close);
    expect(tabFrom(close, true)).toBe(false);
    expect(document.activeElement).toBe(screen.getByTestId("jobs-refresh"));
    fireEvent.click(close);
    expect(document.activeElement).toBe(trigger);
    underlying.focus();
    expect(document.activeElement).toBe(underlying);
  });

  it("recomputes populated/error/loading targets when Retry disappears", async () => {
    let resolve: (rows: JobRow[]) => void = () => {};
    let calls = 0;
    const { close } = open({ list: () => {
      calls += 1;
      if (calls === 1) return Promise.resolve([{ id: "fixture", kind: "research.backtest", state: "failed" }]);
      if (calls === 2) return Promise.reject(new Error("jobs failed: 403"));
      return new Promise<JobRow[]>((done) => { resolve = done; });
    } });
    const row = await screen.findByTestId("job-row");
    expect(tabFrom(close, true)).toBe(false);
    expect(document.activeElement).toBe(row);
    expect(tabFrom(row)).toBe(false);
    expect(document.activeElement).toBe(close);
    const refresh = screen.getByTestId("jobs-refresh");
    fireEvent.click(refresh);
    const retry = await screen.findByRole("button", { name: "Retry" });
    expect(tabFrom(close, true)).toBe(false);
    expect(document.activeElement).toBe(retry);
    retry.focus();
    fireEvent.click(retry);
    expect(screen.getByTestId("jobs-loading")).not.toBeNull();
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Tab" });
    expect(document.activeElement).toBe(close);
    await act(async () => resolve([]));
    expect(screen.getByTestId("jobs-empty")).not.toBeNull();
    expect(tabFrom(close, true)).toBe(false);
    expect(document.activeElement).toBe(refresh);
  });

  it("cancels stale requests on Escape, reopens, and removes listeners on unmount", async () => {
    let resolve: (rows: JobRow[]) => void = () => {};
    let calls = 0;
    const view = open({ list: () => {
      calls += 1;
      return calls === 1 ? new Promise<JobRow[]>((done) => { resolve = done; }) : Promise.resolve([]);
    } });
    fireEvent.keyDown(view.close, { key: "Escape" });
    await act(async () => resolve([{ id: "stale", kind: "research.backtest", state: "succeeded" }]));
    fireEvent.click(view.trigger);
    await screen.findByTestId("jobs-empty");
    expect(screen.queryByTestId("job-row")).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Close jobs drawer" }));
    view.unmount();
    const button = document.createElement("button");
    document.body.append(button);
    try {
      button.focus();
      expect(document.activeElement).toBe(button);
      expect(fireEvent.keyDown(button, { key: "Tab" })).toBe(true);
      expect(fireEvent.keyDown(button, { key: "Escape" })).toBe(true);
    } finally {
      button.remove();
    }
  });

  it("blocks shell shortcuts while open and falls back to the dialog with no enabled targets", () => {
    const { close } = open({ list: () => new Promise(() => {}) });
    let shortcuts = 0;
    const onKey = () => { shortcuts += 1; };
    window.addEventListener("keydown", onKey);
    try {
      fireEvent.keyDown(close, { key: "k", ctrlKey: true });
      expect(shortcuts).toBe(0);
      const dialog = screen.getByRole("dialog");
      for (const button of dialog.querySelectorAll("button")) button.disabled = true;
      fireEvent.keyDown(document.body, { key: "Tab" });
      expect(document.activeElement).toBe(dialog);
      expect(fireEvent.keyDown(dialog, { key: "Tab", shiftKey: true })).toBe(false);
      expect(document.activeElement).toBe(dialog);
      fireEvent.keyDown(dialog, { key: "Escape" });
      expect(screen.queryByRole("dialog")).toBeNull();
      fireEvent.keyDown(document.body, { key: "k", ctrlKey: true });
      expect(shortcuts).toBe(1);
    } finally {
      window.removeEventListener("keydown", onKey);
    }
  });
});
