/**
 * Read-liveness regression (issue 293): the existing-session CSRF
 * recovery GET `/api/v1/session/csrf` is bounded across response
 * headers AND the JSON body by a fixed 10000ms total deadline.
 *
 * Contract under test:
 * - A stalled read (headers or body) resolves `false` at the deadline,
 *   never throws, aborts its owned read, and leaves no pending timer.
 * - A late response from a transport that ignores the AbortSignal can
 *   never install a CSRF token after the deadline has fired.
 * - A healthy supported response that completes before the deadline
 *   still installs the in-memory token; URL, GET method and
 *   `credentials: "include"` are unchanged, with no hidden retry and
 *   no bootstrap POST/replay.
 * - Forbidden/network/malformed responses resolve `false`, and an
 *   already-held token keeps its current failure treatment (no global
 *   token clearing).
 * - Concurrent calls own independent controllers and timers.
 * - An ordinary WorkstationShell reload with no bootstrap token and a
 *   stalled read settles startup within the deadline and offers the
 *   honest "Recover the local session" surface instead of hanging.
 */
import { act, cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { JSX } from "react";
import type { PaperClient } from "./features/paper/client";
import type { ResearchClient } from "./features/research/client";
import type { StrategyClient } from "./features/strategies/client";
import { clearCsrf, getCsrf, recoverCsrf } from "./session";
import { WorkstationShell } from "./shell/WorkstationShell";

const DEADLINE_MS = 10000;

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

beforeAll(() => {
  if (typeof globalThis.ResizeObserver !== "function") {
    globalThis.ResizeObserver =
      ResizeObserverStub as unknown as typeof ResizeObserver;
  }
});

type RecordedFetchCall = {
  url: unknown;
  init: RequestInit | undefined;
};

type FetchStub = {
  calls: RecordedFetchCall[];
};

/** Stubs global fetch; the recorder observes every call verbatim. */
function stubFetch(
  implement: (url: string, init: RequestInit) => Promise<Response> | Response,
): FetchStub {
  const calls: RecordedFetchCall[] = [];
  const mock = vi.fn((url: unknown, init?: RequestInit): Promise<Response> | Response => {
    const record = { url, init };
    calls.push(record);
    return implement(url as string, (init ?? {}) as RequestInit);
  });
  vi.stubGlobal("fetch", mock);
  return { calls };
}

/** A transport response whose headers never arrive. */
function stalledHeaders(): Promise<Response> {
  return new Promise<Response>(() => {});
}

/** A supported 200 whose JSON body never arrives. */
function stalledBodyResponse(): Response {
  return {
    ok: true,
    status: 200,
    json: () => new Promise<never>(() => {}),
  } as unknown as Response;
}

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

function rejectingJsonResponse(): Response {
  return {
    ok: true,
    status: 200,
    json: async (): Promise<unknown> => {
      throw new SyntaxError("Unexpected token < in JSON");
    },
  } as Response;
}

/**
 * Observes settlement of a never-rejecting promise without awaiting it,
 * so a test can assert that a read is still pending at a point in
 * fake-clock time.
 */
function observe(promise: Promise<boolean>): { settled: () => boolean; value: () => boolean | undefined } {
  const state = { done: false, value: undefined as boolean | undefined };
  void promise.then((ok) => {
    state.done = true;
    state.value = ok;
  });
  return {
    settled: () => state.done,
    value: () => state.value,
  };
}

async function advance(ms: number): Promise<void> {
  await vi.advanceTimersByTimeAsync(ms);
}

function signalOf(stub: FetchStub, index = 0): AbortSignal {
  const signal = stub.calls[index]?.init?.signal;
  if (!(signal instanceof AbortSignal)) {
    throw new Error("expected recoverCsrf to pass an AbortSignal it owns");
  }
  return signal;
}

beforeEach(() => {
  vi.useFakeTimers();
  clearCsrf();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("recoverCsrf — bounded existing-session read (fixed 10000ms deadline)", () => {
  it("resolves false at the deadline when response headers never arrive, aborts its owned read and leaves no timer", async () => {
    const stub = stubFetch(() => stalledHeaders());
    const observed = observe(recoverCsrf());

    await advance(DEADLINE_MS - 1);
    expect(observed.settled()).toBe(false);

    await advance(1);
    expect(observed.settled()).toBe(true);
    expect(observed.value()).toBe(false);
    expect(getCsrf()).toBe("");
    expect(signalOf(stub).aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
    // One bounded GET only: no hidden retry, no bootstrap POST/replay.
    expect(stub.calls).toHaveLength(1);
    expect(stub.calls[0].url).toBe("/api/v1/session/csrf");
    expect(stub.calls[0].init?.method).toBe("GET");
    expect(stub.calls[0].init?.credentials).toBe("include");
  });

  it("resolves false at the deadline when the JSON body never arrives", async () => {
    const stub = stubFetch(() => Promise.resolve(stalledBodyResponse()));
    const observed = observe(recoverCsrf());

    await advance(DEADLINE_MS - 1);
    expect(observed.settled()).toBe(false);

    await advance(1);
    expect(observed.value()).toBe(false);
    expect(getCsrf()).toBe("");
    expect(signalOf(stub).aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("never installs a token from late headers after the deadline, even when the transport ignores AbortSignal", async () => {
    const late = { resolve: null as ((response: Response) => void) | null };
    const stub = stubFetch(
      () =>
        new Promise<Response>((resolve) => {
          late.resolve = resolve;
        }),
    );
    const observed = observe(recoverCsrf());

    await advance(DEADLINE_MS);
    expect(observed.value()).toBe(false);

    // The stalled transport finally answers far past the deadline and
    // ignores the abort: the token must still never be committed.
    await advance(60000);
    late.resolve?.(jsonResponse({ csrf_token: "csrf-late-headers" }));
    await advance(1);
    expect(getCsrf()).toBe("");
    expect(stub.calls).toHaveLength(1);
  });

  it("never installs a token when the body lands after the deadline (headers arrived in time)", async () => {
    const late = { body: null as ((body: unknown) => void) | null };
    const response = {
      ok: true,
      status: 200,
      json: () =>
        new Promise<unknown>((resolve) => {
          late.body = resolve;
        }),
    } as unknown as Response;
    const stub = stubFetch(() => Promise.resolve(response));
    const observed = observe(recoverCsrf());

    await advance(DEADLINE_MS);
    expect(observed.value()).toBe(false);

    await advance(1);
    late.body?.({ csrf_token: "csrf-late-body" });
    await advance(1);
    expect(getCsrf()).toBe("");
    expect(signalOf(stub).aborted).toBe(true);
  });

  it("installs the token for a healthy response before the deadline, including a slow body", async () => {
    const slow = { release: null as ((body: unknown) => void) | null };
    const response = {
      ok: true,
      status: 200,
      json: () =>
        new Promise<unknown>((resolve) => {
          slow.release = resolve;
        }),
    } as unknown as Response;
    const stub = stubFetch(() => Promise.resolve(response));
    const observed = observe(recoverCsrf());

    await advance(4000);
    // Body still in flight but inside the deadline: keep waiting.
    expect(observed.settled()).toBe(false);

    slow.release?.({ schema_version: "1", csrf_token: "csrf-slow-body" });
    await advance(1);
    expect(observed.value()).toBe(true);
    expect(getCsrf()).toBe("csrf-slow-body");
    expect(vi.getTimerCount()).toBe(0);
    expect(stub.calls).toHaveLength(1);
    expect(stub.calls[0].url).toBe("/api/v1/session/csrf");
    expect(stub.calls[0].init?.method).toBe("GET");
    expect(stub.calls[0].init?.credentials).toBe("include");
  });

  it("control: installs the token for an immediately healthy response", async () => {
    const stub = stubFetch(() =>
      Promise.resolve(jsonResponse({ csrf_token: "csrf-healthy" })),
    );
    await expect(recoverCsrf()).resolves.toBe(true);
    expect(getCsrf()).toBe("csrf-healthy");
    expect(vi.getTimerCount()).toBe(0);
    expect(stub.calls).toHaveLength(1);
  });

  it("control: 403, network rejection, malformed JSON and a missing token each resolve false without a token", async () => {
    stubFetch(() => Promise.resolve(jsonResponse({}, 403)));
    await expect(recoverCsrf()).resolves.toBe(false);
    expect(vi.getTimerCount()).toBe(0);
    vi.unstubAllGlobals();

    stubFetch(() => Promise.reject(new TypeError("Failed to parse URL")));
    await expect(recoverCsrf()).resolves.toBe(false);
    expect(vi.getTimerCount()).toBe(0);
    vi.unstubAllGlobals();

    stubFetch(() => Promise.resolve(rejectingJsonResponse()));
    await expect(recoverCsrf()).resolves.toBe(false);
    expect(vi.getTimerCount()).toBe(0);
    vi.unstubAllGlobals();

    stubFetch(() => Promise.resolve(jsonResponse({ schema_version: "1" })));
    await expect(recoverCsrf()).resolves.toBe(false);
    expect(getCsrf()).toBe("");
    expect(vi.getTimerCount()).toBe(0);
  });

  it("keeps an already-held token untouched when the read misses the deadline (no global token clearing)", async () => {
    stubFetch(() => Promise.resolve(jsonResponse({ csrf_token: "csrf-held" })));
    await expect(recoverCsrf()).resolves.toBe(true);
    vi.unstubAllGlobals();

    stubFetch(() => stalledHeaders());
    const observed = observe(recoverCsrf());
    await advance(DEADLINE_MS);
    expect(observed.value()).toBe(false);
    expect(getCsrf()).toBe("csrf-held");
  });

  it("bounds concurrent calls independently: separate signals, separate timers, both settled by the deadline", async () => {
    const stub = stubFetch(() => stalledHeaders());
    const first = observe(recoverCsrf());
    const second = observe(recoverCsrf());

    await advance(DEADLINE_MS - 1);
    expect(first.settled()).toBe(false);
    expect(second.settled()).toBe(false);

    await advance(1);
    expect(first.value()).toBe(false);
    expect(second.value()).toBe(false);
    expect(stub.calls).toHaveLength(2);
    expect(signalOf(stub, 0)).not.toBe(signalOf(stub, 1));
    expect(signalOf(stub, 0).aborted).toBe(true);
    expect(signalOf(stub, 1).aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });
});

function makePaperClient(): PaperClient {
  return {
    getStatus: vi.fn(async () => ({ schema_version: "1", armed: false })),
    pauseEntries: vi.fn().mockResolvedValue({
      schema_version: "1",
      code: "entries_paused",
      ok: true,
    }),
    resumeEntries: vi.fn().mockResolvedValue({
      schema_version: "1",
      code: "entries_resumed",
      ok: true,
    }),
    disarm: vi.fn().mockResolvedValue({
      schema_version: "1",
      code: "disarmed",
      ok: true,
    }),
  };
}

function makeResearchClient(): ResearchClient {
  return {
    submitRun: vi.fn().mockResolvedValue({ id: "job-1", state: "queued" }),
    cancelJob: vi.fn().mockResolvedValue(undefined),
    getResult: vi.fn().mockResolvedValue(null),
    getJob: vi.fn().mockResolvedValue({ id: "job-1", state: "succeeded" }),
    getResultDownload: vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      blob: vi.fn().mockResolvedValue(new Blob(['{"ok":true}'])),
    } as unknown as Response),
  };
}

function makeStrategyClient(): StrategyClient {
  return {
    create: vi.fn().mockResolvedValue({
      revision_id: "rev-1",
      state: "draft",
      pack: {},
      errors: [],
    }),
    edit: vi.fn().mockResolvedValue({
      revision_id: "rev-2",
      state: "draft",
      pack: {},
      errors: [],
    }),
    validate: vi.fn().mockResolvedValue({
      revision_id: "rev-1",
      state: "validated",
      pack: {},
      errors: [],
    }),
    arm: vi.fn().mockResolvedValue(undefined),
  };
}

function shellBootstrapDone(): string | null {
  return document
    .querySelector('[data-testid="kbot-shell"]')
    ?.getAttribute("data-bootstrap-done") ?? null;
}

/**
 * Renders the ordinary no-bootstrap reload: no meta tag, so the shell
 * can only recover the CSRF for the existing session cookie.
 */
function renderReloadedShell(stub: FetchStub): void {
  render(
    <WorkstationShell
      paperClient={makePaperClient()}
      researchClient={makeResearchClient()}
      strategyClient={makeStrategyClient()}
    />,
  );
  void stub;
}

describe("WorkstationShell — ordinary reload startup bounded by the recovery deadline", () => {
  afterEach(() => {
    cleanup();
    document.head.innerHTML = "";
    vi.clearAllMocks();
  });

  it("settles startup within the deadline and offers the honest recovery surface when the CSRF read stalls", async () => {
    const stub = stubFetch((url) => {
      // Only the session CSRF read matters here; any other shell read
      // (e.g. jobs polling) also stalls and is ignored.
      void url;
      return stalledHeaders();
    });
    renderReloadedShell(stub);

    // Startup is honestly pending while the read is in flight...
    expect(shellBootstrapDone()).toBe("0");
    expect(screen.getByTestId("app-home-session")).toBeDefined();
    expect(screen.queryByTestId("app-home-session-failure")).toBeNull();

    await act(async () => {
      await advance(DEADLINE_MS - 1);
    });
    expect(shellBootstrapDone()).toBe("0");

    await act(async () => {
      await advance(1);
    });
    // ...then settles honestly failed with the recovery action, never
    // wedged in "starting" forever.
    expect(shellBootstrapDone()).toBe("1");
    expect(screen.queryByTestId("app-home-session")).toBeNull();
    expect(screen.getByTestId("app-home-session-failure")).toBeDefined();
    expect(
      within(screen.getByTestId("app-home-session-failure")).getByRole(
        "button",
        { name: /recover the local session/i },
      ),
    ).toBeDefined();

    // Even far past the deadline the surface stays honest: no silent
    // late success, no automatic retry, no bootstrap replay.
    await act(async () => {
      await advance(60000);
    });
    expect(screen.getByTestId("app-home-session-failure")).toBeDefined();
    const csrfCalls = stub.calls.filter(
      (call) => call.url === "/api/v1/session/csrf",
    );
    expect(csrfCalls).toHaveLength(1);
    expect(csrfCalls[0].init?.method).toBe("GET");
    expect(csrfCalls[0].init?.credentials).toBe("include");
    expect(
      stub.calls.some((call) => call.url === "/api/v1/session/bootstrap"),
    ).toBe(false);
  });

  it("control: completes startup normally when the session recovers before the deadline", async () => {
    const stub = stubFetch((url) => {
      if (url === "/api/v1/session/csrf") {
        return Promise.resolve(jsonResponse({ csrf_token: "csrf-reload-ok" }));
      }
      return stalledHeaders();
    });
    renderReloadedShell(stub);

    await act(async () => {
      await advance(0);
    });
    expect(shellBootstrapDone()).toBe("1");
    expect(screen.queryByTestId("app-home-session")).toBeNull();
    expect(screen.queryByTestId("app-home-session-failure")).toBeNull();
    expect(
      stub.calls.some((call) => call.url === "/api/v1/session/bootstrap"),
    ).toBe(false);
  });
});
