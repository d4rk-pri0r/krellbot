import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OperationsView } from "./OperationsView";
import type { AlertRow, OperationsClient, OperationsViewModel } from "./client";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function setup() {
  const alerts: AlertRow[] = ["first", "second"].map((id) => ({
    id, kind: "intent_refused", severity: "warning", code: "LOCAL_ACK_TEST",
    venue: "local-paper-fixture", pair: "PAPERUSD", count: 1,
    first_ts: 1700000000, last_ts: 1700000000, acknowledged: false,
  }));
  const snapshot = (): OperationsViewModel => ({
    schema_version: "1",
    live: {
      schema_version: "1", live_enabled: false, authorized: [],
      kill_switch: { engaged: false, reason: null, engaged_at: null },
      promotion_available: false, promotion_code: "live_promotion_owner_deferred",
    },
    deployments: [], alerts: alerts.map((alert) => ({ ...alert })),
  });
  // Mock only injected I/O; run the mounted view, children and refresh hook.
  const client = {
    getOperations: vi.fn(async () => snapshot()),
    ackAlert: vi.fn(async (id: string) => {
      alerts.find((alert) => alert.id === id)!.acknowledged = true;
      return { ok: true, code: "acknowledged" };
    }),
    promote: vi.fn(), pauseEntries: vi.fn(), resumeEntries: vi.fn(),
    engageKill: vi.fn(), releaseKill: vi.fn(),
    listAcknowledged: vi.fn(async () => []),
  } satisfies OperationsClient & { listAcknowledged: () => Promise<AlertRow[]> };
  render(<OperationsView client={client} />);
  return { client, alerts };
}

describe("alert acknowledgement failure honesty", () => {
  it.each([
    new Error("Failed to fetch"),
    new Error("alerts.ack failed: 403"),
    new Error("alerts.ack failed: 500"),
    "storage unavailable",
  ])("shows the actual thrown error, retains the button and allows successful retry: %s", async (error) => {
    const { client, alerts } = setup();
    const button = await screen.findByTestId("ops-alert-ack-first");
    client.ackAlert.mockRejectedValueOnce(error);
    const reads = client.getOperations.mock.calls.length;
    fireEvent.click(button);
    const row = screen.getByTestId("ops-alert-first");
    const failure = await within(row).findByTestId("ops-alert-ack-error");
    expect(failure.getAttribute("role")).toBe("alert");
    expect(failure.textContent).toContain(error instanceof Error ? error.message : error);
    expect(within(row).getByRole("button", { name: "Acknowledge" })).toBe(button);
    expect(row.textContent).not.toContain("acknowledged");
    expect(alerts[0].acknowledged).toBe(false);
    expect(within(screen.getByTestId("ops-alert-second")).queryByRole("alert")).toBeNull();
    await waitFor(() => expect(client.getOperations.mock.calls.length).toBeGreaterThan(reads));
    fireEvent.click(button);
    await waitFor(() => expect(within(row).queryByRole("button")).toBeNull());
    expect(row.textContent).toContain("acknowledged");
    expect(within(row).queryByTestId("ops-alert-ack-error")).toBeNull();
    expect(client.ackAlert.mock.calls).toEqual([["first"], ["first"]]);
    expect(screen.getByTestId("ops-alert-ack-second")).toBeTruthy();
  });

  it("clears only the successful row's error after its pending retry completes", async () => {
    const { client, alerts } = setup();
    const first = await screen.findByTestId("ops-alert-ack-first");
    const second = screen.getByTestId("ops-alert-ack-second");
    client.ackAlert.mockRejectedValueOnce(new Error("first failure"));
    fireEvent.click(first);
    await within(screen.getByTestId("ops-alert-first")).findByRole("alert");
    client.ackAlert.mockRejectedValueOnce(new Error("second failure"));
    fireEvent.click(second);
    await within(screen.getByTestId("ops-alert-second")).findByRole("alert");

    let complete!: () => void;
    client.ackAlert.mockImplementationOnce(() => new Promise((resolve) => {
      complete = () => {
        alerts[0].acknowledged = true;
        resolve({ ok: true, code: "acknowledged" });
      };
    }));
    fireEvent.click(first);
    expect(screen.getAllByTestId("ops-alert-ack-error")).toHaveLength(2);
    expect(screen.getByTestId("ops-alert-ack-first")).toBe(first);
    complete();
    await waitFor(() => expect(screen.queryByTestId("ops-alert-ack-first")).toBeNull());
    expect(screen.getAllByTestId("ops-alert-ack-error")).toHaveLength(1);
    expect(within(screen.getByTestId("ops-alert-second")).getByRole("alert").textContent).toContain("second failure");
    expect(screen.getByTestId("ops-alert-ack-second")).toBe(second);
  });

  it("preserves refresh failure reporting alongside the ack error and recovers on retry", async () => {
    const { client } = setup();
    const button = await screen.findByTestId("ops-alert-ack-first");
    client.ackAlert.mockRejectedValueOnce(new Error("ack transport disconnected"));
    client.getOperations.mockRejectedValueOnce(new Error("operations read unavailable"));
    fireEvent.click(button);
    expect((await screen.findByTestId("ops-alert-ack-error")).textContent).toContain("ack transport disconnected");
    expect((await screen.findByTestId("ops-stale-warning")).textContent).toContain("operations read unavailable");
    expect(screen.getByTestId("ops-alert-ack-first")).toBe(button);
    fireEvent.click(button);
    await waitFor(() => expect(screen.queryByTestId("ops-alert-ack-first")).toBeNull());
    expect(screen.queryByTestId("ops-alert-ack-error")).toBeNull();
    expect(screen.queryByTestId("ops-stale-warning")).toBeNull();
  });
});
