import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LastRunsPanel } from "./LastRunsPanel";
import type { PaperClient, PaperRun, PaperRunsClient } from "./client";

const runs: PaperRun[] = ["SUIUSD", "DOTUSD"].map((pair) => ({
  venue: "kraken", pair, pack_id: "local-copy-fixture", first_ts_ms: 1,
  last_ts_ms: 2, ticks_total: 1, last_refusal_code: "store_full",
  mode: "paper", status: "closed", summary: `${pair}: 1 tick, refusal store_full — exact α\n`,
  recent_fills: [{ coid: `coid-${pair}-α`, side: "buy", ts_ms: 1000 }],
}));

async function mount() {
  const client: PaperClient & PaperRunsClient = {
    async listRuns() { return { schema_version: "1", runs }; },
    async getStatus() { throw new Error("Unexpected status read"); },
    async pauseEntries() { throw new Error("Unexpected trading command"); },
    async resumeEntries() { throw new Error("Unexpected trading command"); },
    async disarm() { throw new Error("Unexpected trading command"); },
  };
  render(<LastRunsPanel client={client} />);
  await screen.findByTestId("paper-last-runs-table");
  vi.useFakeTimers();
}

// jsdom has no system clipboard; only this browser boundary is substituted.
function stubClipboard(write: (text: string) => Promise<void> = async () => {}) {
  const calls: string[] = [];
  vi.stubGlobal("navigator", Object.create(navigator, {
    clipboard: { value: { writeText: (text: string) => { calls.push(text); return write(text); } } },
  }));
  return calls;
}
const copy = (pair = "SUIUSD") => screen.getByTestId(`paper-last-runs-copy-kraken-${pair}`);
async function click(button = copy()) {
  await act(async () => { fireEvent.click(button); });
  await act(async () => { vi.advanceTimersToNextFrame(); });
}
async function advance(ms: number) {
  await act(async () => { vi.advanceTimersByTime(ms); });
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("LastRunsPanel copy actions", () => {
  it("copies exact summary, preserves row context and expires only after 2000ms", async () => {
    const calls = stubClipboard();
    await mount();
    const button = copy();
    button.focus();
    for (const key of ["Enter", " "]) {
      expect(fireEvent.keyDown(button, { key })).toBe(true);
      expect(screen.queryByTestId("paper-last-runs-detail")).toBeNull();
    }
    // Native keyboard activation is qualified in Chromium, not simulated by jsdom.
    await click();
    expect(calls).toEqual([runs[0]!.summary]);
    expect(button.textContent).toBe("Copied");
    expect(document.activeElement).toBe(button);
    expect(screen.queryByTestId("paper-last-runs-detail")).toBeNull();
    await advance(1999);
    expect(button.textContent).toBe("Copied");
    await advance(1);
    expect(button.textContent).toBe("Copy");
  });

  it("reports rejected writes for 2000ms, then allows a successful retry", async () => {
    let denied = true;
    const calls = stubClipboard(async () => { if (denied) throw new Error("denied"); });
    await mount();
    await click();
    expect(copy().textContent).toBe("Copy failed");
    await advance(1999);
    expect(copy().textContent).toBe("Copy failed");
    await advance(1);
    expect(copy().textContent).toBe("Copy");
    denied = false;
    await click();
    expect(copy().textContent).toBe("Copied");
    expect(calls).toEqual([runs[0]!.summary, runs[0]!.summary]);
  });

  it("keeps feedback and timer restarts independent across rows", async () => {
    stubClipboard();
    await mount();
    await click();
    await advance(1000);
    await click(copy("DOTUSD"));
    expect(copy().textContent).toBe("Copied");
    expect(copy("DOTUSD").textContent).toBe("Copied");
    await advance(1000);
    expect(copy().textContent).toBe("Copy");
    expect(copy("DOTUSD").textContent).toBe("Copied");
    await click(copy("DOTUSD"));
    await advance(1000);
    expect(copy("DOTUSD").textContent).toBe("Copied");
    await advance(1000);
    expect(copy("DOTUSD").textContent).toBe("Copy");
  });

  it("ignores older asynchronous writes after a newer click on the same row", async () => {
    let finish!: () => void;
    let first = true;
    stubClipboard(() => {
      if (first) { first = false; return new Promise<void>((resolve) => { finish = resolve; }); }
      return Promise.reject(new Error("newer write denied"));
    });
    await mount();
    await click();
    await click();
    expect(copy().textContent).toBe("Copy failed");
    await act(async () => { finish(); });
    await act(async () => { vi.advanceTimersToNextFrame(); });
    expect(copy().textContent).toBe("Copy failed");
  });

  it.each([true, false, "throw"])("cleans up the unavailable-API fallback (%s) and restores focus", async (result) => {
    vi.stubGlobal("navigator", Object.create(navigator, { clipboard: { value: undefined } }));
    // execCommand is absent in jsdom; assert the real fallback's selected textarea.
    const exec = vi.fn(() => {
      const field = document.activeElement as HTMLTextAreaElement;
      expect(field.tagName).toBe("TEXTAREA");
      expect(field.value).toBe(runs[0]!.summary);
      expect(field.selectionEnd).toBe(field.value.length);
      if (result === "throw") throw new Error("copy unavailable");
      return result;
    });
    Object.defineProperty(document, "execCommand", { configurable: true, value: exec });
    try {
      await mount();
      copy().focus();
      await click();
      expect(exec).toHaveBeenCalledWith("copy");
      expect(document.querySelector("textarea")).toBeNull();
      expect(document.activeElement).toBe(copy());
      expect(copy().textContent).toBe(result === true ? "Copied" : "Copy failed");
    } finally {
      Reflect.deleteProperty(document, "execCommand");
    }
  });

  it("copies only the fill coid without changing the fill table semantics", async () => {
    const calls = stubClipboard();
    await mount();
    fireEvent.click(screen.getByTestId("paper-last-runs-row-kraken-SUIUSD"));
    const button = screen.getByRole("button", { name: "Copy coid" });
    expect(button.closest("tr")?.querySelectorAll("td")).toHaveLength(4);
    await click(button);
    expect(calls).toEqual([runs[0]!.recent_fills[0]!.coid]);
    expect(button.textContent).toBe("Copied");
    expect(copy().textContent).toBe("Copy");
    await advance(2000);
    expect(button.textContent).toBe("Copy coid");
  });

  it("cancels pending feedback work on unmount", async () => {
    stubClipboard();
    await mount();
    await click();
    expect(vi.getTimerCount()).toBeGreaterThan(0);
    cleanup();
    expect(vi.getTimerCount()).toBe(0);
  });
});
