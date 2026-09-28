import { afterEach, describe, expect, it, vi } from "vitest";
import { createHttpClient } from "./client";

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

describe("createHttpClient submitRun", () => {
  it("posts /api/v1/jobs with dataset, fee, and dates at the top level", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        schema_version: "1",
        id: "job-abc",
        kind: "research.backtest",
        state: "queued",
        created_at: "2026-01-01T00:00:00Z",
        started_at: null,
        finished_at: null,
        progress: null,
        result_ref: null,
        error: null,
        correlation_id: "corr-1",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const summary = await createHttpClient().submitRun({
      datasetPath: "fixtures/synthetic.csv",
      feeBps: 40,
      fromMs: 0,
      toMs: 1000,
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/jobs");
    expect(init.method).toBe("POST");
    const body = JSON.parse(String(init.body));
    expect(body.kind).toBe("research.backtest");
    expect(body.dataset_csv).toBe("fixtures/synthetic.csv");
    expect(body.fee_bps).toBe(40);
    expect(body.from_ms).toBe(0);
    expect(body.to_ms).toBe(1000);
    expect(body.request).toBeUndefined();
    expect(summary.id).toBe("job-abc");
  });

  it("does not write to localStorage when submitting", async () => {
    const setItemSpy = vi.spyOn(Storage.prototype, "setItem");
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ id: "job-abc", state: "queued" }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await createHttpClient().submitRun({
      datasetPath: "fixtures/synthetic.csv",
      feeBps: 40,
      fromMs: 0,
      toMs: 1000,
    });
    expect(setItemSpy).not.toHaveBeenCalled();
    setItemSpy.mockRestore();
  });
});

describe("createHttpClient cancelJob", () => {
  it("posts /api/v1/jobs/{id}/cancel with that job id", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ id: "job-abc", state: "cancelling" }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await createHttpClient().cancelJob("job-abc");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/jobs/job-abc/cancel");
    expect(init.method).toBe("POST");
  });

  it("does not write to localStorage when cancelling", async () => {
    const setItemSpy = vi.spyOn(Storage.prototype, "setItem");
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ id: "job-abc", state: "cancelling" }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await createHttpClient().cancelJob("job-abc");
    expect(setItemSpy).not.toHaveBeenCalled();
    setItemSpy.mockRestore();
  });
});

describe("createHttpClient getResult", () => {
  it("gets /api/v1/jobs/{id}/result and returns the parsed body", async () => {
    const stored = {
      legacy_receipt: { fee_bps: 40 },
      trace: [{ bar_ts: 0 }],
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(stored));
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpClient().getResult("job-abc");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/jobs/job-abc/result");
    expect(init.method).toBe("GET");
    expect(result).toEqual(stored);
  });

  it("returns null when the server responds 404 result_unavailable", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ code: "result_unavailable" }, 404),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpClient().getResult("job-abc");
    expect(result).toBeNull();
  });

  it("returns null when the server responds 404 not_found for an unknown job", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ code: "not_found" }, 404),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpClient().getResult("missing");
    expect(result).toBeNull();
  });
});
