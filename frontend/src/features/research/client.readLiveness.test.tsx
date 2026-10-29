import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createHttpClient } from "./client";
import { ResearchView } from "./ResearchView";

type TrackedOutcome = {
  state: "pending" | "fulfilled" | "rejected";
  value?: unknown;
  error?: unknown;
};

function track<T>(promise: Promise<T>): TrackedOutcome {
  const outcome: TrackedOutcome = { state: "pending" };
  void promise.then(
    (value) => {
      outcome.state = "fulfilled";
      outcome.value = value;
    },
    (error) => {
      outcome.state = "rejected";
      outcome.error = error;
    },
  );
  return outcome;
}

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

function bodyNeverResolvesResponse(): Response {
  return {
    ok: true,
    status: 200,
    json: () => new Promise<unknown>(() => {}),
  } as Response;
}

function parseFailureResponse(): Response {
  return {
    ok: true,
    status: 200,
    json: async (): Promise<unknown> => {
      throw new SyntaxError("Unexpected token < in JSON at position 0");
    },
  } as Response;
}

function slowBodyResponse(body: unknown, delayMs: number): Response {
  return {
    ok: true,
    status: 200,
    json: () =>
      new Promise<unknown>((resolve) => {
        setTimeout(() => resolve(body), delayMs);
      }),
  } as Response;
}

type FetchCall = { url: string; init: RequestInit };
type Responder = (call: FetchCall) => Response | Promise<Response>;

function stubTransport(responders: Responder[]): {
  fetchMock: ReturnType<typeof vi.fn>;
  calls: FetchCall[];
} {
  const calls: FetchCall[] = [];
  const fetchMock = vi.fn((url: string, init: RequestInit) => {
    calls.push({ url, init });
    const responder = responders[Math.min(calls.length - 1, responders.length - 1)];
    const result = responder(calls[calls.length - 1]);
    return result instanceof Promise ? result : Promise.resolve(result);
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, calls };
}

const never: Responder = () => new Promise<Response>(() => {});

async function flush(): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
}

async function advance(ms: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

const storedBody = {
  legacy_receipt: { fee_bps: 40, equity: 321, trades: [] },
  trace: [{ bar_ts: 1, input: { close: 2 }, conditions: [] }],
};

beforeEach(() => {
  vi.useFakeTimers({
    toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"],
  });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  cleanup();
});

describe("createHttpClient read liveness (issue292)", () => {
  it("getJob settles with an honest read-timeout error when response headers never arrive", async () => {
    const { fetchMock, calls } = stubTransport([never]);
    const outcome = track(createHttpClient().getJob("job-stall"));
    await advance(9999);
    expect(outcome.state).toBe("pending");
    await advance(1);
    expect(outcome.state).toBe("rejected");
    expect((outcome.error as Error).message).toMatch(/timed out/i);
    expect((calls[0].init.signal as AbortSignal).aborted).toBe(true);
    await advance(5000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("getResult settles with an honest read-timeout error when response headers never arrive", async () => {
    const { fetchMock, calls } = stubTransport([never]);
    const outcome = track(createHttpClient().getResult("job-stall"));
    await advance(9999);
    expect(outcome.state).toBe("pending");
    await advance(1);
    expect(outcome.state).toBe("rejected");
    expect((outcome.error as Error).message).toMatch(/timed out/i);
    expect(calls[0].url).toBe("/api/v1/jobs/job-stall/result");
    expect((calls[0].init.signal as AbortSignal).aborted).toBe(true);
    await advance(5000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("getJob settles with an honest read-timeout error when the JSON body never resolves", async () => {
    const { calls } = stubTransport([() => bodyNeverResolvesResponse()]);
    const outcome = track(createHttpClient().getJob("job-body"));
    await advance(10000);
    expect(outcome.state).toBe("rejected");
    expect((outcome.error as Error).message).toMatch(/timed out/i);
    expect((calls[0].init.signal as AbortSignal).aborted).toBe(true);
  });

  it("getResult settles with an honest read-timeout error when the JSON body never resolves", async () => {
    const { calls } = stubTransport([() => bodyNeverResolvesResponse()]);
    const outcome = track(createHttpClient().getResult("job-body"));
    await advance(10000);
    expect(outcome.state).toBe("rejected");
    expect((outcome.error as Error).message).toMatch(/timed out/i);
    expect((calls[0].init.signal as AbortSignal).aborted).toBe(true);
  });

  it("an ordinary Run through the real view recovers after the first status read hangs", async () => {
    const { fetchMock, calls } = stubTransport([
      () => jsonResponse({ id: "job-stall", state: "queued" }),
      never,
      () => jsonResponse({ id: "job-stall", state: "succeeded" }),
      () => jsonResponse(storedBody),
    ]);
    render(<ResearchView client={createHttpClient()} />);
    fireEvent.change(screen.getByLabelText(/dataset path/i), {
      target: { value: "fixtures/synthetic.csv" },
    });
    fireEvent.change(screen.getByLabelText(/fee basis points/i), {
      target: { value: "40" },
    });
    fireEvent.change(screen.getByLabelText(/^from$/i), {
      target: { value: "0" },
    });
    fireEvent.change(screen.getByLabelText(/^to$/i), {
      target: { value: "1000" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    await flush();
    expect(screen.getByTestId("research-job-id").textContent).toContain("job-stall");
    await advance(10000);
    await advance(1000);
    expect(screen.queryByTestId("research-result")).not.toBeNull();
    expect(screen.getByTestId("research-result").textContent).toContain("321");
    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(calls[0].init.signal).toBeUndefined();
    expect((calls[1].init.signal as AbortSignal).aborted).toBe(true);
    expect(calls[2].url).toBe("/api/v1/jobs/job-stall");
    expect(calls[3].url).toBe("/api/v1/jobs/job-stall/result");
  });

  it("healthy reads keep returning parsed values with the same URL, method, credentials and CSRF header", async () => {
    const { calls } = stubTransport([
      () => jsonResponse({ id: "job-ok", state: "running" }),
      () => jsonResponse(storedBody),
    ]);
    const client = createHttpClient();
    const snap = await client.getJob("job-ok");
    const stored = await client.getResult("job-ok");
    expect(snap).toEqual({ id: "job-ok", state: "running", error: undefined });
    expect(stored).toEqual(storedBody);
    expect(calls[0].url).toBe("/api/v1/jobs/job-ok");
    expect(calls[0].init.method).toBe("GET");
    expect(calls[0].init.credentials).toBe("include");
    expect(
      (calls[0].init.headers as Record<string, string>)["X-Krellbot-CSRF"],
    ).toBeDefined();
    expect(calls[1].url).toBe("/api/v1/jobs/job-ok/result");
    expect(calls[1].init.method).toBe("GET");
    expect(calls[1].init.credentials).toBe("include");
  });

  it("404 responses still map to null for getJob and getResult with encoded URLs", async () => {
    const { calls } = stubTransport([
      () => jsonResponse({ code: "not_found" }, 404),
      () => jsonResponse({ code: "result_unavailable" }, 404),
    ]);
    const client = createHttpClient();
    await expect(client.getJob("missing /id")).resolves.toBeNull();
    await expect(client.getResult("missing /id")).resolves.toBeNull();
    expect(calls[0].url).toBe("/api/v1/jobs/missing%20%2Fid");
    expect(calls[1].url).toBe("/api/v1/jobs/missing%20%2Fid/result");
  });

  it.each([403, 500])(
    "non-2xx status %s still rejects with the honest request-failed error",
    async (status) => {
      stubTransport([() => jsonResponse({ code: "nope" }, status)]);
      const client = createHttpClient();
      await expect(client.getJob("job-err")).rejects.toThrow(
        `request failed: ${status}`,
      );
      await expect(client.getResult("job-err")).rejects.toThrow(
        `request failed: ${status}`,
      );
    },
  );

  it("a JSON parse failure still propagates the parser error, not a timeout", async () => {
    stubTransport([() => parseFailureResponse()]);
    const outcome = track(createHttpClient().getJob("job-parse"));
    await advance(10000);
    expect(outcome.state).toBe("rejected");
    expect((outcome.error as Error).message).toMatch(/Unexpected token/);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("a body that completes under the deadline still resolves with its value", async () => {
    stubTransport([() => slowBodyResponse(storedBody, 4000)]);
    const client = createHttpClient();
    const outcome = track(client.getResult("job-slow"));
    await advance(3999);
    expect(outcome.state).toBe("pending");
    await advance(1);
    expect(outcome.state).toBe("fulfilled");
    expect(outcome.value).toEqual(storedBody);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("clears the deadline timer on every exit path", async () => {
    const client = createHttpClient();
    stubTransport([() => jsonResponse({ id: "job-ok", state: "running" })]);
    const healthy = track(client.getJob("job-ok"));
    await flush();
    expect(healthy.state).toBe("fulfilled");
    expect(vi.getTimerCount()).toBe(0);

    stubTransport([never]);
    const timedOut = track(client.getJob("job-stall"));
    await advance(10000);
    expect(timedOut.state).toBe("rejected");
    expect(vi.getTimerCount()).toBe(0);
  });

  it("simultaneous reads have independent controllers and timers", async () => {
    const { calls } = stubTransport([
      () => jsonResponse(storedBody),
      never,
    ]);
    const client = createHttpClient();
    const healthy = track(client.getResult("job-a"));
    const stalled = track(client.getResult("job-b"));
    await flush();
    expect(healthy.state).toBe("fulfilled");
    expect(stalled.state).toBe("pending");
    expect(vi.getTimerCount()).toBe(1);
    await advance(10000);
    expect(stalled.state).toBe("rejected");
    expect((stalled.error as Error).message).toMatch(/timed out/i);
    const signalA = calls[0].init.signal as AbortSignal;
    const signalB = calls[1].init.signal as AbortSignal;
    expect(signalA).not.toBe(signalB);
    expect(signalA.aborted).toBe(false);
    expect(signalB.aborted).toBe(true);
  });

  it("a transport that ignores the abort signal cannot settle the expired call with a late response", async () => {
    const lateResponse = new Promise<Response>((resolve) => {
      setTimeout(() => resolve(jsonResponse({ id: "job-late", state: "running" })), 20000);
    });
    const { fetchMock, calls } = stubTransport([() => lateResponse]);
    const outcome = track(createHttpClient().getJob("job-late"));
    await advance(10000);
    expect(outcome.state).toBe("rejected");
    expect((outcome.error as Error).message).toMatch(/timed out/i);
    expect((calls[0].init.signal as AbortSignal).aborted).toBe(true);
    await advance(10000);
    expect(outcome.state).toBe("rejected");
    expect((outcome.error as Error).message).toMatch(/timed out/i);
    expect(outcome.value).toBeUndefined();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("POST submit and result download stay unbounded and the client never replays a read", async () => {
    const { fetchMock } = stubTransport([never, never]);
    const client = createHttpClient();
    const submitOutcome = track(
      client.submitRun({
        datasetPath: "fixtures/synthetic.csv",
        feeBps: 40,
        fromMs: 0,
        toMs: 1000,
      }),
    );
    const downloadOutcome = track(client.getResultDownload("job-x"));
    await advance(30000);
    expect(submitOutcome.state).toBe("pending");
    expect(downloadOutcome.state).toBe("pending");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const stalled = track(client.getJob("job-x"));
    await advance(10000);
    expect(stalled.state).toBe("rejected");
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
});
