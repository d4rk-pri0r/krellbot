import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AcknowledgedAlertsList } from "./AcknowledgedAlertsList";
import type { AlertRow } from "./client";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const row: AlertRow = {
  id: "local-paper-history", kind: "warning", severity: "warning", code: null,
  venue: null, pair: null, count: 1, first_ts: 1700000000,
  last_ts: 1700000000, acknowledged: true,
};

async function settle() {
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 70)); });
}

// Mock only transport: exercise the real fallback client, adapter and effect.
it("reads fallback once per mount or explicit refresh, not per state update", async () => {
  const fetch = vi.fn().mockImplementation(async () => new Response(JSON.stringify({
    alerts: [row, { ...row, id: "unacknowledged", acknowledged: false }],
  }), { status: 200 }));
  vi.stubGlobal("fetch", fetch);
  const client = {};
  const view = render(<AcknowledgedAlertsList client={client} />);
  await settle();
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(screen.queryByTestId("ops-acknowledged-alert-unacknowledged")).toBeNull();
  fireEvent.click(screen.getByTestId(`ops-acknowledged-alert-${row.id}`));
  expect(screen.getByTestId(`ops-ack-detail-${row.id}`)).toBeTruthy();
  view.rerender(<AcknowledgedAlertsList client={client} />);
  await settle();
  expect(fetch).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByTestId("ops-acknowledged-refresh"));
  await settle();
  expect(fetch).toHaveBeenCalledTimes(2);
  view.rerender(<AcknowledgedAlertsList client={{}} />);
  await settle();
  expect(fetch).toHaveBeenCalledTimes(3);
});

it.each(["resolve", "reject"] as const)("ignores stale %s after client replacement", async (outcome) => {
  let resolve!: (rows: AlertRow[]) => void;
  let reject!: (error: Error) => void;
  const pending = new Promise<AlertRow[]>((yes, no) => { resolve = yes; reject = no; });
  const view = render(<AcknowledgedAlertsList client={{ listAcknowledged: () => pending }} />);
  const listAcknowledged = vi.fn().mockResolvedValue([]);
  view.rerender(<AcknowledgedAlertsList client={{ listAcknowledged }} />);
  await settle();
  await act(async () => {
    if (outcome === "resolve") resolve([row]);
    else reject(new Error("stale failure"));
  });
  expect(screen.getByText("No acknowledged alerts.")).toBeTruthy();
  expect(screen.queryByRole("alert")).toBeNull();
  expect(listAcknowledged).toHaveBeenCalledTimes(1);
});

it("keeps the latest explicit refresh result", async () => {
  let resolve!: (rows: AlertRow[]) => void;
  const pending = new Promise<AlertRow[]>((yes) => { resolve = yes; });
  const listAcknowledged = vi.fn().mockReturnValueOnce(pending).mockResolvedValue([]);
  render(<AcknowledgedAlertsList client={{ listAcknowledged }} />);
  fireEvent.click(screen.getByTestId("ops-acknowledged-refresh"));
  await settle();
  await act(async () => { resolve([row]); });
  expect(screen.getByText("No acknowledged alerts.")).toBeTruthy();
});

it("ignores a rejected request after unmount", async () => {
  let reject!: (error: Error) => void;
  const pending = new Promise<AlertRow[]>((_yes, no) => { reject = no; });
  const view = render(<AcknowledgedAlertsList client={{ listAcknowledged: () => pending }} />);
  view.unmount();
  await act(async () => { reject(new Error("abandoned request")); });
  expect(screen.queryByRole("alert")).toBeNull();
});
