import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OperationsView } from "./OperationsView";
import { summarizeAlertCode } from "./alertCodeLabel";
import { summarizeAlertKind } from "./alertKindLabel";
import { summarizeAlertSeverity } from "./alertSeverityLabel";
import type { AlertRow, OperationsClient, OperationsViewModel } from "./client";

// A finite alert last_ts whose millisecond value sits outside the ECMAScript
// Date range (±8.64e15 ms) must render the shared unavailable presentation
// (em dash) instead of letting new Date(last_ts * 1000).toISOString() throw
// RangeError and abort the whole Operations view.

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function makeAlert(overrides: Partial<AlertRow> & { id: string }): AlertRow {
  return {
    kind: "intent_refused",
    severity: "warning",
    code: "LAST_TS_RANGE_TEST",
    venue: "local-paper-fixture",
    pair: "PAPERUSD",
    count: 1,
    first_ts: 1700000000,
    last_ts: 1700000000,
    acknowledged: false,
    ...overrides,
  };
}

function setup(alerts: AlertRow[]) {
  const snapshot = (): OperationsViewModel => ({
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
    alerts: alerts.map((alert) => ({ ...alert })),
  });
  // Mock only injected I/O; run the mounted view, children and refresh hook.
  const client = {
    getOperations: vi.fn(async () => snapshot()),
    ackAlert: vi.fn(async (id: string) => {
      const alert = alerts.find((row) => row.id === id);
      if (alert) {
        alert.acknowledged = true;
      }
      return { ok: true, code: "acknowledged" };
    }),
    promote: vi.fn(),
    pauseEntries: vi.fn(),
    resumeEntries: vi.fn(),
    engageKill: vi.fn(),
    releaseKill: vi.fn(),
    listAcknowledged: vi.fn(async () => []),
  } satisfies OperationsClient & { listAcknowledged: () => Promise<AlertRow[]> };
  render(<OperationsView client={client} />);
  return { client, alerts };
}

describe("operations view alert last_ts Date-range safety", () => {
  it("renders the unavailable em dash for an out-of-range positive last_ts without aborting the view", async () => {
    setup([makeAlert({ id: "range-a1", last_ts: 9.1e12 })]);
    const row = await screen.findByTestId("ops-alert-range-a1");
    expect(within(row).getByText("last —")).toBeTruthy();
    expect(screen.getByTestId("ops-deployments-panel")).toBeTruthy();
    expect(screen.getByTestId("ops-alerts-panel")).toBeTruthy();
  });

  it("renders the unavailable em dash for an out-of-range negative last_ts", async () => {
    setup([makeAlert({ id: "range-a2", last_ts: -9.1e12 })]);
    const row = await screen.findByTestId("ops-alert-range-a2");
    expect(within(row).getByText("last —")).toBeTruthy();
  });

  it("keeps exact byte-equal UTC strings for healthy in-range last_ts values", async () => {
    setup([
      makeAlert({ id: "healthy-pos", last_ts: 1700000000 }),
      makeAlert({ id: "healthy-epoch", last_ts: 0 }),
      makeAlert({ id: "healthy-neg", last_ts: -1 }),
    ]);
    expect(
      within(await screen.findByTestId("ops-alert-healthy-pos")).getByText("last 2023-11-14 22:13:20"),
    ).toBeTruthy();
    expect(
      within(screen.getByTestId("ops-alert-healthy-epoch")).getByText("last 1970-01-01 00:00:00"),
    ).toBeTruthy();
    expect(
      within(screen.getByTestId("ops-alert-healthy-neg")).getByText("last 1969-12-31 23:59:59"),
    ).toBeTruthy();
  });

  it("renders the exact Date-boundary last_ts values and the em dash one step beyond", async () => {
    setup([
      makeAlert({ id: "boundary-max", last_ts: 8.64e12 }),
      makeAlert({ id: "boundary-min", last_ts: -8.64e12 }),
      makeAlert({ id: "boundary-over", last_ts: 8.64e12 + 1 }),
      makeAlert({ id: "boundary-under", last_ts: -8.64e12 - 1 }),
    ]);
    expect(
      within(await screen.findByTestId("ops-alert-boundary-max")).getByText("last +275760-09-13 00:00"),
    ).toBeTruthy();
    expect(
      within(screen.getByTestId("ops-alert-boundary-min")).getByText("last -271821-04-20 00:00"),
    ).toBeTruthy();
    expect(within(screen.getByTestId("ops-alert-boundary-over")).getByText("last —")).toBeTruthy();
    expect(within(screen.getByTestId("ops-alert-boundary-under")).getByText("last —")).toBeTruthy();
  });

  it("keeps neighbouring rows and acknowledge controls usable when one last_ts is out of range", async () => {
    const { client } = setup([
      makeAlert({ id: "mix-healthy-a", severity: "critical", count: 3, last_ts: 1700000000 }),
      makeAlert({ id: "mix-broken", severity: "critical", count: 2, last_ts: 9.1e12 }),
      makeAlert({ id: "mix-healthy-b", severity: "warning", count: 5, last_ts: 1700000001 }),
    ]);

    const healthyA = await screen.findByTestId("ops-alert-mix-healthy-a");
    const broken = screen.getByTestId("ops-alert-mix-broken");
    const healthyB = screen.getByTestId("ops-alert-mix-healthy-b");

    expect(within(healthyA).getByText("last 2023-11-14 22:13:20")).toBeTruthy();
    expect(within(broken).getByText("last —")).toBeTruthy();
    expect(within(healthyB).getByText("last 2023-11-14 22:13:21")).toBeTruthy();

    for (const row of [healthyA, broken, healthyB]) {
      expect(row.textContent).toContain(summarizeAlertKind("intent_refused").label);
      expect(row.textContent).toContain(summarizeAlertSeverity(
        row === healthyB ? "warning" : "critical",
      ).label);
      expect(row.textContent).toContain(summarizeAlertCode("LAST_TS_RANGE_TEST").label);
      expect(row.textContent).toContain("local-paper-fixture PAPERUSD");
    }
    expect(healthyA.textContent).toContain("×3");
    expect(broken.textContent).toContain("×2");
    expect(healthyB.textContent).toContain("×5");

    const ackBroken = within(broken).getByRole("button", { name: "Acknowledge" }) as HTMLButtonElement;
    expect(ackBroken.disabled).toBe(false);
    const ackB = within(healthyB).getByRole("button", { name: "Acknowledge" });
    fireEvent.click(within(healthyA).getByRole("button", { name: "Acknowledge" }));

    await waitFor(() => {
      expect(client.ackAlert).toHaveBeenCalledWith("mix-healthy-a");
      expect(within(screen.getByTestId("ops-alert-mix-healthy-a")).queryByRole("button")).toBeNull();
    });
    expect(
      within(screen.getByTestId("ops-alert-mix-healthy-a")).getByText("acknowledged"),
    ).toBeTruthy();

    const brokenAfter = screen.getByTestId("ops-alert-mix-broken");
    expect(within(brokenAfter).getByText("last —")).toBeTruthy();
    expect(within(brokenAfter).getByRole("button", { name: "Acknowledge" })).toBe(ackBroken);
    const bAfter = screen.getByTestId("ops-alert-mix-healthy-b");
    expect(within(bAfter).getByText("last 2023-11-14 22:13:21")).toBeTruthy();
    expect(within(bAfter).getByRole("button", { name: "Acknowledge" })).toBe(ackB);
    expect(screen.getByTestId("ops-deployments-panel")).toBeTruthy();
  });
});
