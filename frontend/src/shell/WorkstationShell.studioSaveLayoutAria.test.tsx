import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { Pack, StrategyClient } from "../features/strategies/client";
import { WorkstationShell } from "./WorkstationShell";

function deferred() {
  let resolve!: () => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<void>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

beforeAll(() => {
  if (typeof globalThis.ResizeObserver !== "function") {
    globalThis.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
  }
});

afterEach(() => {
  cleanup();
  window.history.replaceState({}, "", "/");
});

async function openSavedStudio(saveEditor: StrategyClient["saveEditor"]) {
  window.history.replaceState({}, "", "/");
  const pack: Pack = {
    id: "layout-aria",
    timeframe: "1h",
    indicators: { sma20: { fn: "sma", src: "close", len: 20 } },
    entry: ["close", ">", "sma20"],
    exit: ["close", "<", "sma20"],
  };
  const revision = {
    revision_id: "rev-layout-aria",
    state: "draft" as const,
    pack,
    errors: [],
  };
  const strategy: StrategyClient = {
    create: async () => revision,
    edit: async () => { throw new Error("Layout save must not edit execution"); },
    validate: async () => { throw new Error("Layout save must not validate execution"); },
    arm: async () => { throw new Error("Layout save must not arm execution"); },
    saveEditor,
  };
  render(<WorkstationShell strategyClient={strategy} />);
  fireEvent.click(screen.getByRole("button", { name: "Studio" }));
  expect(screen.queryByTestId("studio-save-layout")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Strategies" }));
  fireEvent.change(screen.getByLabelText(/raw json/i), {
    target: { value: JSON.stringify(pack) },
  });
  fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
  await screen.findByTestId("editor-revision-id");
  fireEvent.click(screen.getByRole("button", { name: "Studio" }));
  return screen.getByTestId("studio-save-layout") as HTMLButtonElement;
}

function layoutStatus() {
  const status = screen.getByTestId("studio-save-layout-status");
  expect(status.tagName).toBe("P");
  expect(status.getAttribute("role")).toBe("status");
  expect(status.getAttribute("aria-live")).toBe("polite");
  expect(status.hidden).toBe(false);
  expect(status.getAttribute("aria-hidden")).not.toBe("true");
  expect(status.style.position).toBe("absolute");
  expect(status.style.clipPath).toBe("inset(50%)");
  return status;
}

describe("Studio Save layout assistive feedback", () => {
  it("announces a pending save, prevents duplicate activation, then announces the saved revision", async () => {
    const pending = deferred();
    const saveEditor = vi.fn<NonNullable<StrategyClient["saveEditor"]>>()
      .mockReturnValue(pending.promise);
    const button = await openSavedStudio(saveEditor);
    expect(button.getAttribute("aria-busy")).toBe("false");
    expect(button.getAttribute("aria-keyshortcuts")).toBe("Enter");
    expect(button.disabled).toBe(false);
    expect(layoutStatus().textContent).toBe("");
    button.focus();
    expect(document.activeElement).toBe(button);
    fireEvent.click(button);
    expect(button.getAttribute("aria-busy")).toBe("true");
    expect(button.disabled).toBe(true);
    expect(layoutStatus().textContent).toBe("Saving layout");
    fireEvent.click(button);
    expect(saveEditor).toHaveBeenCalledTimes(1);
    expect(saveEditor).toHaveBeenCalledWith("rev-layout-aria", {
      layout: {
        pack: expect.any(Object),
        entry: expect.any(Object),
        exit: expect.any(Object),
        sma20: expect.any(Object),
      },
      edges: [],
    });
    await act(async () => { pending.resolve(); });
    expect(button.getAttribute("aria-busy")).toBe("false");
    expect(button.disabled).toBe(false);
    expect(layoutStatus().textContent).toBe("Layout saved for revision rev-layout-aria");
    expect(screen.queryByTestId("studio-layout-error")).toBeNull();
  });

  it("clears stale success on retry, alerts on rejection without announcing success, and permits recovery", async () => {
    const first = deferred();
    const second = deferred();
    const third = deferred();
    const saveEditor = vi.fn<NonNullable<StrategyClient["saveEditor"]>>()
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise)
      .mockReturnValueOnce(third.promise);
    const button = await openSavedStudio(saveEditor);
    fireEvent.click(button);
    await act(async () => { first.resolve(); });
    expect(layoutStatus().textContent).toBe("Layout saved for revision rev-layout-aria");
    fireEvent.click(button);
    expect(layoutStatus().textContent).toBe("Saving layout");
    await act(async () => { second.reject(new Error("layout 500")); });
    expect(button.getAttribute("aria-busy")).toBe("false");
    expect(button.disabled).toBe(false);
    expect(layoutStatus().textContent).toBe("");
    const error = screen.getByTestId("studio-layout-error");
    expect(error.getAttribute("role")).toBe("alert");
    expect(error.className).toBe("kbot-shell__error");
    expect(error.textContent).toBe("layout 500");
    fireEvent.click(button);
    expect(screen.queryByTestId("studio-layout-error")).toBeNull();
    expect(layoutStatus().textContent).toBe("Saving layout");
    await act(async () => { third.resolve(); });
    expect(button.disabled).toBe(false);
    expect(layoutStatus().textContent).toBe("Layout saved for revision rev-layout-aria");
    expect(saveEditor).toHaveBeenCalledTimes(3);
  });

  it("does not report a pending or successful save when the optional saveEditor is absent", async () => {
    const button = await openSavedStudio(undefined);
    fireEvent.click(button);
    expect(button.getAttribute("aria-busy")).toBe("false");
    expect(button.disabled).toBe(false);
    expect(layoutStatus().textContent).toBe("");
  });
});
