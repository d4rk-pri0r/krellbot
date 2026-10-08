import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { OperationsClient, OperationsViewModel } from "./client";
import {
  OPERATIONS_READ_TIMEOUT_MS,
  OPERATIONS_REFRESH_INTERVAL_MS,
  useOperationsRefresh,
} from "./useOperationsRefresh";

const INTERVAL = OPERATIONS_REFRESH_INTERVAL_MS;

function view(over: Partial<OperationsViewModel> = {}): OperationsViewModel {
  return {
    schema_version: "1",
    live: {
      schema_version: "1",
      live_enabled: false,
      authorized: [],
      kill_switch: { engaged: false, reason: null, engaged_at: null },
      promotion_available: false,
      promotion_code: "live_promotion_owner_deferred",
    },
    deployments: [],
    alerts: [],
    ...over,
  };
}

function makeClient(over: Partial<OperationsClient> = {}): OperationsClient {
  return {
    getOperations: vi.fn().mockResolvedValue(view()),
    promote: vi.fn().mockResolvedValue({ schema_version: "1", code: "live_disabled", ok: false }),
    pauseEntries: vi.fn().mockResolvedValue({ schema_version: "1", code: "entries_paused", ok: true }),
    resumeEntries: vi.fn().mockResolvedValue({ schema_version: "1", code: "entries_resumed", ok: true }),
    engageKill: vi.fn().mockResolvedValue({ schema_version: "1", code: "kill_switch_engaged", ok: true }),
    releaseKill: vi.fn().mockResolvedValue({ schema_version: "1", code: "kill_switch_released", ok: true }),
    ackAlert: vi.fn().mockResolvedValue({ schema_version: "1", code: "acknowledged", ok: true }),
    ...over,
  };
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  cleanup();
  vi.restoreAllMocks();
});

async function settle(ms = 0): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe("useOperationsRefresh initial load", () => {
  it("reads once on mount and records the last successful read", async () => {
    const client = makeClient();
    const { result } = renderHook(() => useOperationsRefresh(client, { intervalMs: INTERVAL }));
    expect(result.current.refreshing).toBe(true);
    expect(result.current.view).toBeNull();
    await settle();
    expect(result.current.view).not.toBeNull();
    expect(result.current.fetchError).toBeNull();
    expect(result.current.lastSuccessAt).not.toBeNull();
    expect(result.current.lastSuccessAgeMs).not.toBeNull();
    expect(result.current.refreshing).toBe(false);
  });

  it("reports the fetch error while the view stays null on a first-read failure", async () => {
    const client = makeClient({
      getOperations: vi.fn().mockRejectedValue(new Error("operations view failed: 503")),
    });
    const { result } = renderHook(() => useOperationsRefresh(client, { intervalMs: INTERVAL }));
    await settle();
    expect(result.current.view).toBeNull();
    expect(result.current.fetchError).toBe("operations view failed: 503");
    expect(result.current.lastSuccessAt).toBeNull();
    expect(result.current.lastSuccessAgeMs).toBeNull();
  });
});

describe("useOperationsRefresh periodic read", () => {
  it("issues a read-only getOperations on each interval tick and never a command", async () => {
    const client = makeClient();
    renderHook(() => useOperationsRefresh(client, { intervalMs: INTERVAL }));
    await settle();
    expect(client.getOperations).toHaveBeenCalledTimes(1);
    await settle(INTERVAL);
    expect(client.getOperations).toHaveBeenCalledTimes(2);
    await settle(INTERVAL);
    expect(client.getOperations).toHaveBeenCalledTimes(3);
    expect(client.promote).not.toHaveBeenCalled();
    expect(client.pauseEntries).not.toHaveBeenCalled();
    expect(client.resumeEntries).not.toHaveBeenCalled();
    expect(client.engageKill).not.toHaveBeenCalled();
    expect(client.releaseKill).not.toHaveBeenCalled();
    expect(client.ackAlert).not.toHaveBeenCalled();
  });

  it("updates the view when the server state changes on a later tick", async () => {
    let calls = 0;
    const client = makeClient({
      getOperations: vi.fn().mockImplementation(async () => {
        calls += 1;
        return view({
          deployments:
            calls === 1
              ? []
              : [
                  {
                    venue: "kraken",
                    pair: "SUIUSD",
                    pack_id: "trend-follow",
                    pack_version: "1.0.0",
                    mode: "paper",
                    entries_paused: true,
                    promotion: { available: false, code: "live_disabled" },
                  },
                ],
        });
      }),
    });
    const { result } = renderHook(() => useOperationsRefresh(client, { intervalMs: INTERVAL }));
    await settle();
    expect(result.current.view?.deployments.length).toBe(0);
    await settle(INTERVAL);
    expect(result.current.view?.deployments.length).toBe(1);
    expect(result.current.view?.deployments[0]?.entries_paused).toBe(true);
  });

  it("skips a tick whose read is still in flight, then reads again after it settles", async () => {
    let resolveFirst: (v: OperationsViewModel) => void = () => undefined;
    const client = makeClient({
      getOperations: vi.fn().mockImplementationOnce(
        () =>
          new Promise<OperationsViewModel>((resolve) => {
            resolveFirst = resolve;
          }),
      ),
    });
    renderHook(() => useOperationsRefresh(client, { intervalMs: 100 }));
    // First read is hung; ticks that fire while it is in flight are skipped.
    await settle(250);
    expect(client.getOperations).toHaveBeenCalledTimes(1);
    await act(async () => {
      resolveFirst(view());
    });
    await settle(100);
    expect(client.getOperations).toHaveBeenCalledTimes(2);
  });
});

describe("useOperationsRefresh retained stale state and recovery", () => {
  it("keeps the last view and marks an error when a later read fails, then recovers", async () => {
    let calls = 0;
    const client = makeClient({
      getOperations: vi.fn().mockImplementation(async () => {
        calls += 1;
        if (calls === 2) {
          throw new Error("operations view failed: 503");
        }
        return view({
          deployments: [
            {
              venue: "kraken",
              pair: "SUIUSD",
              pack_id: "trend-follow",
              pack_version: "1.0.0",
              mode: "paper",
              entries_paused: false,
              promotion: { available: false, code: "live_disabled" },
            },
          ],
        });
      }),
    });
    const { result } = renderHook(() => useOperationsRefresh(client, { intervalMs: INTERVAL }));
    await settle();
    const first = result.current.view;
    expect(first?.deployments[0]?.pack_id).toBe("trend-follow");

    await settle(INTERVAL);
    // The prior view is retained, never wiped, when the read fails.
    expect(result.current.view).toBe(first);
    expect(result.current.fetchError).toBe("operations view failed: 503");

    await settle(INTERVAL);
    expect(result.current.fetchError).toBeNull();
    expect(result.current.view).not.toBeNull();
    expect(result.current.view?.deployments[0]?.pack_id).toBe("trend-follow");
  });

  it("ages the last successful read upward while reads keep failing", async () => {
    let calls = 0;
    const client = makeClient({
      getOperations: vi.fn().mockImplementation(async () => {
        calls += 1;
        if (calls > 1) {
          throw new Error("operations view failed: 503");
        }
        return view();
      }),
    });
    const { result } = renderHook(() => useOperationsRefresh(client, { intervalMs: INTERVAL }));
    await settle();
    const ageAfterFirst = result.current.lastSuccessAgeMs ?? 0;
    expect(ageAfterFirst).toBeGreaterThanOrEqual(0);
    await settle(INTERVAL * 3);
    expect(result.current.fetchError).toBe("operations view failed: 503");
    expect(result.current.lastSuccessAgeMs ?? 0).toBeGreaterThan(ageAfterFirst);
  });
});

describe("useOperationsRefresh hung read timeout", () => {
  it("visibly stales a hung read within the bounded timeout and reads again afterwards", async () => {
    let calls = 0;
    const client = makeClient({
      getOperations: vi.fn().mockImplementation(() => {
        calls += 1;
        if (calls === 1) {
          return new Promise<OperationsViewModel>(() => undefined);
        }
        return Promise.resolve(view());
      }),
    });
    // The interval is longer than the timeout so the hung read is first
    // abandoned and reported on its own, before any later tick can recover.
    const { result } = renderHook(() =>
      useOperationsRefresh(client, { intervalMs: 6000, timeoutMs: OPERATIONS_READ_TIMEOUT_MS }),
    );
    await settle(OPERATIONS_READ_TIMEOUT_MS + 500);
    expect(result.current.fetchError).toMatch(/timed out after 4000ms/);
    expect(result.current.fetchError).toMatch(/no response from the local dashboard server/);
    expect(result.current.view).toBeNull();
    expect(result.current.refreshing).toBe(false);
    await settle(2000);
    expect(result.current.fetchError).toBeNull();
    expect(result.current.view).not.toBeNull();
    expect(calls).toBe(2);
  });

  it("keeps the last successful view when a later read hangs past the timeout", async () => {
    let calls = 0;
    const client = makeClient({
      getOperations: vi.fn().mockImplementation(() => {
        calls += 1;
        if (calls === 1) {
          return Promise.resolve(
            view({
              deployments: [
                {
                  venue: "kraken",
                  pair: "SUIUSD",
                  pack_id: "trend-follow",
                  pack_version: "1.0.0",
                  mode: "paper",
                  entries_paused: false,
                  promotion: { available: false, code: "live_disabled" },
                },
              ],
            }),
          );
        }
        return new Promise<OperationsViewModel>(() => undefined);
      }),
    });
    const { result } = renderHook(() =>
      useOperationsRefresh(client, { intervalMs: 6000, timeoutMs: OPERATIONS_READ_TIMEOUT_MS }),
    );
    await settle();
    const first = result.current.view;
    expect(first?.deployments[0]?.pack_id).toBe("trend-follow");
    await settle(6000 + OPERATIONS_READ_TIMEOUT_MS + 500);
    expect(result.current.fetchError).toMatch(/timed out after 4000ms/);
    expect(result.current.view).toBe(first);
  });
});

describe("useOperationsRefresh read sequencing", () => {
  it("discards an older read that resolves after a newer manual refresh started", async () => {
    const firstView = view({
      deployments: [
        {
          venue: "kraken",
          pair: "SUIUSD",
          pack_id: "old-pack",
          pack_version: "1.0.0",
          mode: "paper",
          entries_paused: false,
          promotion: { available: false, code: "live_disabled" },
        },
      ],
    });
    const newerView = view({
      deployments: [
        {
          venue: "kraken",
          pair: "SUIUSD",
          pack_id: "new-pack",
          pack_version: "1.0.0",
          mode: "paper",
          entries_paused: true,
          promotion: { available: false, code: "live_disabled" },
        },
      ],
    });
    let resolveOlder: (v: OperationsViewModel) => void = () => undefined;
    const client = makeClient({
      getOperations: vi
        .fn()
        .mockImplementationOnce(
          () =>
            new Promise<OperationsViewModel>((resolve) => {
              resolveOlder = resolve;
            }),
        )
        .mockResolvedValueOnce(newerView),
    });
    const { result } = renderHook(() => useOperationsRefresh(client, { intervalMs: INTERVAL }));
    // The mount read is still hung; an action-driven refresh supersedes it.
    await act(async () => {
      await result.current.refresh();
    });
    await act(async () => {
      resolveOlder(firstView);
    });
    // The older resolution must not overwrite the newer read's view.
    expect(result.current.view?.deployments[0]?.pack_id).toBe("new-pack");
    expect(result.current.fetchError).toBeNull();
  });

  it("treats an explicit manual refresh as a full replacement of the view", async () => {
    const freshView = view({
      alerts: [
        {
          id: "z9",
          kind: "live_refused",
          severity: "warning",
          code: "live_disabled",
          venue: "kraken",
          pair: "SUIUSD",
          count: 1,
          first_ts: 1700000000,
          last_ts: 1700000600,
          acknowledged: false,
        },
      ],
    });
    const client = makeClient({
      getOperations: vi.fn().mockResolvedValueOnce(view()).mockResolvedValueOnce(freshView),
    });
    const { result } = renderHook(() => useOperationsRefresh(client, { intervalMs: INTERVAL }));
    await settle();
    expect(result.current.view?.alerts.length).toBe(0);
    await act(async () => {
      await result.current.refresh();
    });
    expect(result.current.view?.alerts[0]?.id).toBe("z9");
    expect(client.getOperations).toHaveBeenCalledTimes(2);
  });
});

describe("useOperationsRefresh unmount cleanup", () => {
  it("stops the interval and applies no state after unmount", async () => {
    let resolveRead: (v: OperationsViewModel) => void = () => undefined;
    const client = makeClient({
      getOperations: vi.fn().mockImplementation(
        () =>
          new Promise<OperationsViewModel>((resolve) => {
            resolveRead = resolve;
          }),
      ),
    });
    const { unmount } = renderHook(() =>
      useOperationsRefresh(client, { intervalMs: 100 }),
    );
    await settle(50);
    unmount();
    await act(async () => {
      resolveRead(view());
    });
    // Ticks after unmount must not issue further reads.
    await settle(500);
    expect(client.getOperations).toHaveBeenCalledTimes(1);
    expect(() => {
      resolveRead(view());
    }).not.toThrow();
  });

  it("clears timers on unmount so a surviving read cannot resurrect state", async () => {
    let resolveRead: (v: OperationsViewModel) => void = () => undefined;
    const client = makeClient({
      getOperations: vi.fn().mockImplementation(
        () =>
          new Promise<OperationsViewModel>((resolve) => {
            resolveRead = resolve;
          }),
      ),
    });
    const { result, unmount } = renderHook(() =>
      useOperationsRefresh(client, { intervalMs: 100 }),
    );
    await settle(50);
    unmount();
    await act(async () => {
      resolveRead(view());
    });
    expect(result.current.view).toBeNull();
  });
});

describe("useOperationsRefresh client identity", () => {
  it("re-reads when a new client is provided without duplicating timers", async () => {
    const first = makeClient();
    const second = makeClient();
    const { rerender, result } = renderHook(
      ({ client }: { client: OperationsClient }) =>
        useOperationsRefresh(client, { intervalMs: INTERVAL }),
      { initialProps: { client: first } },
    );
    await settle();
    expect(first.getOperations).toHaveBeenCalledTimes(1);
    rerender({ client: second });
    await settle();
    expect(second.getOperations).toHaveBeenCalledTimes(1);
    expect(first.getOperations).toHaveBeenCalledTimes(1);
    expect(result.current.view).not.toBeNull();
  });
});
