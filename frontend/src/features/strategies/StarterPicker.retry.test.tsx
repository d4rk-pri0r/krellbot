import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StarterPicker } from "./StarterPicker";
import type { StarterCatalogue } from "./StarterPicker.client";

afterEach(cleanup);

/**
 * Same stand-in as the other StarterPicker suites: the section counts
 * as visible the moment it is observed, so the production lifecycle
 * (one-shot intersection, cancel flag, state machine) runs unmocked.
 * The callback fires on `observe()` only — exactly the production
 * contract — so an effect run that never observes (a retry attempt)
 * cannot double-fire it.
 */
class VisibleIntersectionObserver {
  private callback: IntersectionObserverCallback;
  constructor(callback: IntersectionObserverCallback) {
    this.callback = callback;
  }
  observe(target: Element): void {
    queueMicrotask(() => {
      this.callback(
        [{ isIntersecting: true, target } as IntersectionObserverEntry],
        this as unknown as IntersectionObserver,
      );
    });
  }
  disconnect(): void {}
  unobserve(): void {}
  takeRecords(): IntersectionObserverEntry[] {
    return [];
  }
}

beforeEach(() => {
  vi.stubGlobal(
    "IntersectionObserver",
    VisibleIntersectionObserver as unknown as typeof IntersectionObserver,
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

const retryName = "Retry starter examples";

const loaded: StarterCatalogue = {
  schema_version: "1",
  catalogue_version: "1",
  examples: [
    {
      id: "starter-dual-ma-crossover",
      label: "Dual moving-average crossover",
      description: "Educational example.",
      pack: { id: "starter-dual-ma-crossover" },
    },
    {
      id: "starter-range-breakout",
      label: "Range breakout",
      description: "Educational example.",
      pack: { id: "starter-range-breakout" },
    },
  ],
};

function deferred() {
  let resolve!: (catalogue: StarterCatalogue) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<StarterCatalogue>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

async function failOnce(message = "starter catalogue unavailable: 503") {
  const load = vi.fn(() => Promise.reject(new Error(message)));
  render(<StarterPicker onPick={() => {}} loadStarters={load} />);
  const error = await screen.findByTestId("starter-picker-error");
  expect(error.textContent).toBe(`Could not load starter examples: ${message}`);
  expect(load).toHaveBeenCalledTimes(1);
  return { load, error };
}

describe("starter picker retry affordance", () => {
  it("renders a retry button next to the error paragraph, keyboard operable", async () => {
    await failOnce();
    const retry = screen.getByTestId("starter-picker-retry");
    expect(retry.tagName).toBe("BUTTON");
    expect(retry.textContent).toBe(retryName);
    expect(retry.getAttribute("type")).toBe("button");
    // The retry affordance sits in the same row as the error paragraph.
    const row = retry.closest(".kbot-starter-picker__error-row");
    expect(row).not.toBeNull();
    expect(row!.contains(screen.getByTestId("starter-picker-error"))).toBe(true);
    // Keyboard operable: focusable, plain button semantics.
    retry.focus();
    expect(document.activeElement).toBe(retry);
    fireEvent.keyDown(retry, { key: "Enter" });
    expect((retry as HTMLButtonElement).disabled).toBe(false);
  });

  it("a failed retry re-shows the same typed message and keeps the retry affordance", async () => {
    const { load } = await failOnce("transient boom");
    const retry = screen.getByTestId("starter-picker-retry");
    fireEvent.click(retry);
    await waitFor(() => {
      expect(load).toHaveBeenCalledTimes(2);
    });
    const error = await screen.findByTestId("starter-picker-error");
    expect(error.textContent).toBe("Could not load starter examples: transient boom");
    // Still recoverable without leaving the editor.
    expect(screen.getByTestId("starter-picker-retry").tagName).toBe("BUTTON");
  });

  it("retry re-runs the same loadStarters path exactly once per click and the rows replace the error", async () => {
    const second = deferred();
    const load = vi.fn()
      .mockImplementationOnce(() => Promise.reject(new Error("offline")))
      .mockImplementationOnce(() => second.promise);
    render(<StarterPicker onPick={() => {}} loadStarters={load} />);
    await screen.findByTestId("starter-picker-error");
    // While the retry is in flight the section shows the loading branch.
    await act(async () => {
      fireEvent.click(screen.getByTestId("starter-picker-retry"));
    });
    expect(load).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("starter-picker-loading")).toBeDefined();
    await act(async () => {
      second.resolve(loaded);
    });
    expect(screen.queryByTestId("starter-picker-error")).toBeNull();
    expect(screen.queryByTestId("starter-picker-retry")).toBeNull();
    expect(
      screen.getByTestId("starter-picker-item-starter-dual-ma-crossover"),
    ).toBeDefined();
    expect(screen.getByTestId("starter-picker-item-starter-range-breakout")).toBeDefined();
    // No fetch on success retries automatically.
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("a retry against catalogue_version 0 yields the empty state, never invented rows", async () => {
    const load = vi.fn()
      .mockImplementationOnce(() => Promise.reject(new Error("offline")))
      .mockImplementationOnce(() =>
        Promise.resolve({ ...loaded, catalogue_version: "0" }),
      );
    render(<StarterPicker onPick={() => {}} loadStarters={load} />);
    await screen.findByTestId("starter-picker-error");
    await act(async () => {
      fireEvent.click(screen.getByTestId("starter-picker-retry"));
    });
    expect(await screen.findByTestId("starter-picker-empty")).toBeDefined();
    expect(screen.queryByTestId("starter-picker-error")).toBeNull();
    expect(screen.queryByTestId("starter-picker-retry")).toBeNull();
    expect(
      screen.queryByTestId("starter-picker-item-starter-dual-ma-crossover"),
    ).toBeNull();
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("retry stays hidden until the first real failure", async () => {
    const load = vi.fn(() => Promise.resolve(loaded));
    render(<StarterPicker onPick={() => {}} loadStarters={load} />);
    expect(screen.queryByTestId("starter-picker-retry")).toBeNull();
    expect(
      await screen.findByTestId("starter-picker-item-starter-dual-ma-crossover"),
    ).toBeDefined();
    expect(screen.queryByTestId("starter-picker-retry")).toBeNull();
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("no auto-refetch after success: rows stay mounted without further loads", async () => {
    const load = vi.fn()
      .mockImplementationOnce(() => Promise.reject(new Error("offline")))
      .mockImplementationOnce(() => Promise.resolve(loaded));
    render(<StarterPicker onPick={() => {}} loadStarters={load} />);
    await screen.findByTestId("starter-picker-error");
    await act(async () => {
      fireEvent.click(screen.getByTestId("starter-picker-retry"));
    });
    await screen.findByTestId("starter-picker-item-starter-dual-ma-crossover");
    expect(screen.queryByTestId("starter-picker-retry")).toBeNull();
    // No further effect re-runs: the catalogue is fetched exactly twice.
    expect(load).toHaveBeenCalledTimes(2);
  });
});
