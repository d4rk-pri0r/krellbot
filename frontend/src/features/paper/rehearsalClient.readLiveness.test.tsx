import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { createRehearsalHttpClient } from "./rehearsalClient";
import { RehearsalPanel } from "./RehearsalPanel";

const status = { schema_version: "1", label: "Synthetic read fixture", status: "idle", cursor: 0, total_bars: 20, balances: { USD: "1000" }, position: "0", resting_stop: null, recent_fills: [] };
const response = () => ({ ok: true, status: 200, json: async () => status });
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(yes => { resolve = yes; });
  return { promise, resolve };
}
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });

it.each(["headers", "body"])("releases panel controls after stalled %s and allows a manual read without commands", async (phase) => {
  vi.useFakeTimers();
  const headers = deferred<ReturnType<typeof response>>();
  const body = deferred<typeof status>();
  const fetchMock = vi.fn().mockResolvedValueOnce(response())
    .mockImplementationOnce(() => phase === "headers" ? headers.promise : Promise.resolve({ ...response(), json: () => body.promise }))
    .mockResolvedValue(response());
  vi.stubGlobal("fetch", fetchMock);
  await act(async () => { render(<RehearsalPanel client={createRehearsalHttpClient()} />); });
  const refresh = screen.getByTestId("rehearsal-command-refresh") as HTMLButtonElement;
  fireEvent.click(refresh);
  expect(refresh.disabled).toBe(true);
  await act(async () => { await vi.advanceTimersByTimeAsync(15000); });
  expect(refresh.disabled).toBe(false);
  expect(screen.getByTestId("rehearsal-panel").textContent).toContain("last confirmed state");
  expect(fetchMock.mock.calls[1][1].signal.aborted).toBe(true);
  expect(fetchMock).toHaveBeenCalledTimes(2);
  await act(async () => { fireEvent.click(refresh); });
  expect(fetchMock).toHaveBeenCalledTimes(3);
  expect(refresh.disabled).toBe(false);
  await act(async () => { headers.resolve(response()); body.resolve({ ...status, status: "running" }); });
  expect(screen.getByTestId("rehearsal-state-chip").textContent).toContain("idle");
  expect(fetchMock.mock.calls.every(([, options]) => options.method === "GET")).toBe(true);
  expect(vi.getTimerCount()).toBe(0);
});

it("allows a slow response body inside the full deadline and disposes its timer", async () => {
  vi.useFakeTimers();
  const headers = deferred<ReturnType<typeof response>>();
  const body = deferred<typeof status>();
  const fetchMock = vi.fn().mockReturnValue(headers.promise);
  vi.stubGlobal("fetch", fetchMock);
  const result = createRehearsalHttpClient().getStatus();
  await vi.advanceTimersByTimeAsync(7000);
  headers.resolve({ ...response(), json: () => body.promise });
  await vi.advanceTimersByTimeAsync(7000);
  body.resolve(status);
  expect(await result).toEqual(status);
  expect(fetchMock.mock.calls[0][1].signal.aborted).toBe(false);
  expect(vi.getTimerCount()).toBe(0);
});
