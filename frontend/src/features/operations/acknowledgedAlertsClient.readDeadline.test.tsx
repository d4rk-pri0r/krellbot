import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AcknowledgedAlertsList } from "./AcknowledgedAlertsList";

// Exercises the production default client end to end: the panel gets an
// injected client object without listAcknowledged, so it falls back to
// createAcknowledgedAlertsHttpClient, and only the transport (global fetch)
// is stubbed. listAcknowledged must settle within the fixed 10000ms total
// deadline across response headers AND the JSON body.
const READ_DEADLINE_MS = 10000;

interface Deferred<T> {
  promise: Promise<T>;
  resolve(value: T): void;
  reject(error: unknown): void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

function operationsBody(alerts: unknown[]): Record<string, unknown> {
  return {
    schema_version: "1",
    live: { live_enabled: false, authorized: [], kill_switch: {}, promotion_available: false },
    deployments: [],
    alerts,
  };
}

function healthyResponse(alerts: unknown[]): Response {
  return new Response(JSON.stringify(operationsBody(alerts)), { status: 200 });
}

const ACK_KILL_SWITCH = {
  id: "a1",
  kind: "kill_switch",
  severity: "critical",
  code: null,
  venue: null,
  pair: null,
  count: 2,
  first_ts: 1700000000,
  last_ts: 1700000100,
  acknowledged: true,
};

const ACK_WARNING = {
  id: "a2",
  kind: "intent_refused",
  severity: "warning",
  code: "coid-1",
  venue: "kraken",
  pair: "SUIUSD",
  count: 1,
  first_ts: 1700000200,
  last_ts: 1700000200,
  acknowledged: true,
};

const UNACKNOWLEDGED_INFO = {
  id: "a3",
  kind: "intent_refused",
  severity: "info",
  code: "unack_fixture",
  venue: "kraken",
  pair: "SUIUSD",
  count: 1,
  first_ts: 1700000300,
  last_ts: 1700000300,
  acknowledged: false,
};

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

async function flush(): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1);
  });
}

async function advanceToDeadline(): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(READ_DEADLINE_MS);
  });
}

describe("acknowledgedAlertsClient bounded read deadline via AcknowledgedAlertsList", () => {
  it("rejects a stalled headers read at the fixed deadline with the role=alert failure, aborts its request and clears its timer", async () => {
    const stalled = deferred<Response>();
    const fetchMock = vi.fn().mockImplementation(() => stalled.promise);
    vi.stubGlobal("fetch", fetchMock);
    render(<AcknowledgedAlertsList client={{}} />);
    const panel = screen.getByTestId("ops-acknowledged-alerts");
    expect(panel.textContent).toContain("Loading…");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(READ_DEADLINE_MS - 1);
    });
    expect(panel.textContent).toContain("Loading…");
    await advanceToDeadline();
    const failure = screen.getByRole("alert");
    expect(failure.textContent).toContain("Failed to load acknowledged alerts.");
    expect(failure.textContent ?? "").toMatch(/timed out after 10000ms/);
    expect(panel.textContent ?? "").not.toContain("Loading…");
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/operations");
    expect(init.credentials).toBe("include");
    expect((init.headers as Record<string, string>)["X-Krellbot-CSRF"]).toBeDefined();
    expect(init.signal).toBeInstanceOf(AbortSignal);
    expect((init.signal as AbortSignal).aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("rejects a stalled JSON body read at the same fixed total deadline", async () => {
    const stalledBody = {
      ok: true,
      status: 200,
      json: () => deferred<Record<string, unknown>>().promise,
    } as unknown as Response;
    const fetchMock = vi.fn().mockResolvedValue(stalledBody);
    vi.stubGlobal("fetch", fetchMock);
    render(<AcknowledgedAlertsList client={{}} />);
    expect(screen.getByTestId("ops-acknowledged-alerts").textContent).toContain("Loading…");
    await advanceToDeadline();
    const failure = screen.getByRole("alert");
    expect(failure.textContent).toContain("Failed to load acknowledged alerts.");
    expect(failure.textContent ?? "").toMatch(/timed out after 10000ms/);
    expect(screen.getByTestId("ops-acknowledged-alerts").textContent ?? "").not.toContain("Loading…");
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect((init.signal as AbortSignal).aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("never lets late rows from an expired attempt settle the original load", async () => {
    const stalled = deferred<Response>();
    const fetchMock = vi.fn().mockImplementation(() => stalled.promise);
    vi.stubGlobal("fetch", fetchMock);
    render(<AcknowledgedAlertsList client={{}} />);
    await advanceToDeadline();
    expect(screen.getByRole("alert").textContent).toContain("Failed to load acknowledged alerts.");
    await act(async () => {
      stalled.resolve(healthyResponse([ACK_KILL_SWITCH, ACK_WARNING]));
      await vi.advanceTimersByTimeAsync(50);
    });
    const panel = screen.getByTestId("ops-acknowledged-alerts");
    expect(panel.textContent).toContain("Failed to load acknowledged alerts.");
    expect(panel.textContent ?? "").not.toContain("Loading…");
    expect(screen.queryByTestId("ops-acknowledged-alert-a1")).toBeNull();
    expect(screen.queryByTestId("ops-acknowledged-alert-a2")).toBeNull();
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("keeps Refresh usable after a timeout and renders real rows from a fresh bounded read", async () => {
    const stalled = deferred<Response>();
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(() => stalled.promise)
      .mockImplementationOnce(async () => healthyResponse([ACK_KILL_SWITCH, ACK_WARNING]));
    vi.stubGlobal("fetch", fetchMock);
    render(<AcknowledgedAlertsList client={{}} />);
    await advanceToDeadline();
    expect(screen.getByRole("alert").textContent).toContain("Failed to load acknowledged alerts.");
    fireEvent.click(screen.getByTestId("ops-acknowledged-refresh"));
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const [, freshInit] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(freshInit.signal).toBeInstanceOf(AbortSignal);
    expect((freshInit.signal as AbortSignal).aborted).toBe(false);
    await flush();
    await flush();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByTestId("ops-acknowledged-alert-a1")).toBeTruthy();
    expect(screen.getByTestId("ops-acknowledged-alert-a2")).toBeTruthy();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("renders healthy acknowledged rows before the deadline with filters, detail toggle and acknowledged-only behaviour", async () => {
    const fetchMock = vi.fn().mockImplementation(
      async () => healthyResponse([ACK_KILL_SWITCH, ACK_WARNING, UNACKNOWLEDGED_INFO]),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<AcknowledgedAlertsList client={{}} />);
    await flush();
    await flush();
    expect(screen.getByTestId("ops-acknowledged-alert-a1")).toBeTruthy();
    expect(screen.getByTestId("ops-acknowledged-alert-a2")).toBeTruthy();
    expect(screen.queryByTestId("ops-acknowledged-alert-a3")).toBeNull();
    const panel = screen.getByTestId("ops-acknowledged-alerts");
    expect(panel.textContent ?? "").not.toContain("a3");
    fireEvent.change(screen.getByTestId("ops-acknowledged-filter-severity"), {
      target: { value: "warning" },
    });
    expect(screen.queryByTestId("ops-acknowledged-alert-a1")).toBeNull();
    expect(screen.getByTestId("ops-acknowledged-alert-a2")).toBeTruthy();
    fireEvent.click(screen.getByTestId("ops-acknowledged-alert-a2"));
    expect(screen.getByTestId("ops-ack-detail-a2").textContent ?? "").toContain("intent_refused");
    expect(vi.getTimerCount()).toBe(0);
  });

  it("keeps the truthful non-2xx failure unchanged", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(
        async () => new Response(JSON.stringify(operationsBody([])), { status: 403 }),
      ),
    );
    render(<AcknowledgedAlertsList client={{}} />);
    await flush();
    await flush();
    const failure = screen.getByRole("alert");
    expect(failure.textContent).toContain("Failed to load acknowledged alerts.");
    expect(failure.textContent ?? "").toMatch(/403/);
    expect(failure.textContent ?? "").not.toMatch(/timed out/);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("unmount before the deadline leaves no live deadline timer and no stray failure surface", async () => {
    const stalled = deferred<Response>();
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => stalled.promise));
    const view = render(<AcknowledgedAlertsList client={{}} />);
    expect(vi.getTimerCount()).toBe(1);
    view.unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(READ_DEADLINE_MS + 100);
    });
    expect(document.body.textContent ?? "").not.toContain("Failed to load acknowledged alerts.");
    expect(vi.getTimerCount()).toBe(0);
  });
});
