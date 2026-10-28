import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StarterPicker } from "./StarterPicker";

afterEach(cleanup);

/**
 * Read-deadline regression (issue 302): the production default loader
 * (`fetchStarters`) is exercised end to end through a real render of
 * the section, with only the network boundary stubbed. A stalled
 * catalogue read — response headers or JSON body — must settle by the
 * fixed 10000ms total deadline as the existing inline failure row with
 * its existing Retry control, never as a perpetual Loading state.
 */
const READ_DEADLINE_MS = 10000;

/** Same viewport stand-in as the sibling StarterPicker suites. */
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

const healthyBody = {
  schema_version: "1",
  catalogue_version: "1",
  examples: [
    {
      id: "starter-dual-ma-crossover",
      label: "Dual moving-average crossover",
      description: "Educational example.",
      pack: { id: "starter-dual-ma-crossover" },
    },
  ],
};

function immediateJson(body: unknown, ok = true, status = 200): Response {
  return { ok, status, json: async () => body } as Response;
}

function deferredJson() {
  let resolveJson!: (body: unknown) => void;
  const json = new Promise<unknown>((done) => {
    resolveJson = done;
  });
  const response = { ok: true, status: 200, json: () => json } as Response;
  return { response, resolveJson };
}

/** Fetch mock with the production `fetch` parameter shape. */
function fetchMockOf(impl: () => Promise<Response>) {
  return vi.fn(
    (_input: RequestInfo | URL, _init?: RequestInit): Promise<Response> =>
      impl(),
  );
}

/** Flush the loader microtasks without ever reaching the deadline. */
async function flush(): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
}

async function advanceToDeadline(): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(READ_DEADLINE_MS);
  });
}

function renderPicker(): ReturnType<typeof render> {
  return render(<StarterPicker onPick={() => {}} />);
}

describe("starter picker read deadline (production fetchStarters)", () => {
  const realFetch = globalThis.fetch;

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    vi.stubGlobal(
      "IntersectionObserver",
      VisibleIntersectionObserver as unknown as typeof IntersectionObserver,
    );
  });

  afterEach(() => {
    globalThis.fetch = realFetch;
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("a stalled headers read leaves Loading for the existing error row with Retry at the deadline", async () => {
    const fetchMock = fetchMockOf(() => new Promise<Response>(() => {}));
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    renderPicker();
    await flush();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("starter-picker-loading")).toBeDefined();
    // Before the deadline the bounded read is still legitimately loading.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(READ_DEADLINE_MS - 1);
    });
    expect(screen.getByTestId("starter-picker-loading")).toBeDefined();
    expect(screen.queryByTestId("starter-picker-error")).toBeNull();
    expect(screen.queryByTestId("starter-picker-retry")).toBeNull();
    // At the deadline the section settles as the existing inline failure.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    const error = screen.getByTestId("starter-picker-error");
    expect(error.textContent).toBe(
      "Could not load starter examples: starter catalogue read timed out after 10000ms",
    );
    const retry = screen.getByTestId("starter-picker-retry");
    expect(retry.tagName).toBe("BUTTON");
    expect(screen.queryByTestId("starter-picker-loading")).toBeNull();
    // The expired attempt aborted the request it owns.
    const init = fetchMock.mock.calls[0][1];
    expect(init?.signal).toBeInstanceOf(AbortSignal);
    expect(init?.signal?.aborted).toBe(true);
    // No invented fallback rows ship with the failure.
    expect(
      screen.queryByTestId("starter-picker-item-starter-dual-ma-crossover"),
    ).toBeNull();
  });

  it("a stalled body read settles at the deadline and a late catalogue never settles the expired attempt", async () => {
    const late = deferredJson();
    const fetchMock = fetchMockOf(() => Promise.resolve(late.response));
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    renderPicker();
    await flush();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("starter-picker-loading")).toBeDefined();
    await advanceToDeadline();
    expect(screen.getByTestId("starter-picker-error")).toBeDefined();
    expect(screen.getByTestId("starter-picker-retry")).toBeDefined();
    expect(fetchMock.mock.calls[0][1]?.signal?.aborted).toBe(true);
    // The stalled body completes late with a healthy catalogue...
    await act(async () => {
      late.resolveJson(healthyBody);
    });
    await flush();
    // ...but the expired attempt must not settle the original load.
    expect(screen.getByTestId("starter-picker-error")).toBeDefined();
    expect(screen.getByTestId("starter-picker-retry")).toBeDefined();
    expect(
      screen.queryByTestId("starter-picker-item-starter-dual-ma-crossover"),
    ).toBeNull();
    expect(screen.queryByTestId("starter-picker-loading")).toBeNull();
  });

  it("a healthy catalogue inside the deadline keeps the exact success behaviour", async () => {
    const fetchMock = fetchMockOf(() => Promise.resolve(immediateJson(healthyBody)));
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    renderPicker();
    await flush();
    await flush();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/packs/starters");
    expect(init?.method).toBe("GET");
    expect(init?.credentials).toBe("include");
    expect(
      screen.getByTestId("starter-picker-item-starter-dual-ma-crossover"),
    ).toBeDefined();
    expect(screen.queryByTestId("starter-picker-error")).toBeNull();
    expect(screen.queryByTestId("starter-picker-retry")).toBeNull();
    // Success cleared the deadline timer and never aborted its request.
    expect(init?.signal?.aborted).toBe(false);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("catalogue_version 0 still renders the explicit empty state, no fallback rows", async () => {
    const fetchMock = fetchMockOf(() =>
      Promise.resolve(immediateJson({ ...healthyBody, catalogue_version: "0" })),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    renderPicker();
    await flush();
    await flush();
    expect(screen.getByTestId("starter-picker-empty")).toBeDefined();
    expect(screen.getByText("No starter examples available")).toBeDefined();
    expect(
      screen.queryByTestId("starter-picker-item-starter-dual-ma-crossover"),
    ).toBeNull();
    expect(screen.queryByTestId("starter-picker-error")).toBeNull();
  });

  it("a non-2xx response keeps its existing truthful error", async () => {
    const fetchMock = fetchMockOf(() =>
      Promise.resolve(immediateJson({}, false, 503)),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    renderPicker();
    await flush();
    await flush();
    const error = screen.getByTestId("starter-picker-error");
    expect(error.textContent).toBe(
      "Could not load starter examples: starter catalogue unavailable: 503",
    );
    expect(screen.getByTestId("starter-picker-retry")).toBeDefined();
    expect(screen.queryByTestId("starter-picker-empty")).toBeNull();
  });

  it("a malformed body keeps its existing truthful error", async () => {
    const fetchMock = fetchMockOf(() => Promise.resolve(immediateJson({ nope: 1 })));
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    renderPicker();
    await flush();
    await flush();
    const error = screen.getByTestId("starter-picker-error");
    expect(error.textContent).toBe(
      "Could not load starter examples: starter catalogue response malformed",
    );
    expect(screen.getByTestId("starter-picker-retry")).toBeDefined();
  });

  it("retry after a timeout performs a fresh bounded read that can render real examples", async () => {
    const fetchMock = fetchMockOf(() => new Promise<Response>(() => {}));
    fetchMock
      .mockImplementationOnce(
        (_input: RequestInfo | URL, _init?: RequestInit) =>
          new Promise<Response>(() => {}),
      )
      .mockImplementationOnce(
        (_input: RequestInfo | URL, _init?: RequestInit) =>
          Promise.resolve(immediateJson(healthyBody)),
      );
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    renderPicker();
    await flush();
    await advanceToDeadline();
    expect(screen.getByTestId("starter-picker-error")).toBeDefined();
    await act(async () => {
      fireEvent.click(screen.getByTestId("starter-picker-retry"));
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    await flush();
    await flush();
    expect(
      screen.getByTestId("starter-picker-item-starter-dual-ma-crossover"),
    ).toBeDefined();
    expect(screen.queryByTestId("starter-picker-error")).toBeNull();
    expect(screen.queryByTestId("starter-picker-loading")).toBeNull();
    // The completed retry owns a fresh, cleared deadline — not a lingering one.
    expect(fetchMock.mock.calls[1][1]?.signal?.aborted).toBe(false);
    await advanceToDeadline();
    expect(
      screen.getByTestId("starter-picker-item-starter-dual-ma-crossover"),
    ).toBeDefined();
    expect(screen.queryByTestId("starter-picker-error")).toBeNull();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("unmounting the section leaves no pending deadline timers", async () => {
    const fetchMock = fetchMockOf(() => new Promise<Response>(() => {}));
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const view = renderPicker();
    await flush();
    // Exactly the in-flight read's own deadline timer is pending.
    expect(vi.getTimerCount()).toBe(1);
    await act(async () => {
      view.unmount();
    });
    await advanceToDeadline();
    // The deadline fired once and was cleared on exit: no leak, no rows.
    expect(vi.getTimerCount()).toBe(0);
    expect(document.querySelector(".kbot-starter-picker")).toBeNull();
  });
});
