import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OperationsView } from "./OperationsView";
import type {
  AlertRow,
  DeploymentRow,
  OperationsClient,
  OperationsViewModel,
} from "./client";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

/**
 * KRELL-SIGNAL-20261010 operations presentation layer.
 *
 * Transport note: every client here is an in-memory vi.fn() fake standing
 * in for the loopback operations API. No real venue/engine state, keys,
 * orders or deployment history is exercised or implied by these tests.
 */

const DISABLED_TEXT =
  "Live trading is disabled in this build (KRELLBOT_ENABLE_LIVE is not 1).";
const NO_GRANTS_TEXT =
  "Live trading is not authorized: no operator grant on file.";
const PROMO_DEFERRED_TEXT = "Promotion to live is owner-deferred.";
const KILL_HELPER = "Engaging stops new entries and all live sends. It does not sell or disarm.";
const KILL_RELEASED_TEXT = "Kill switch: released";
const NO_ALERTS_TEXT = "No alerts.";
const NO_ALERTS_MATCH_TEXT = "No alerts match the current filters.";
const NO_DEPLOYMENTS_TEXT = "No deployments.";
const MANUAL_REFRESH_LABEL = "Refresh now";
const STALE_PREFIX = "Operations state may be stale";
const STALE_SUFFIX =
  "showing last known state from the previous successful read — not current server state";

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

function live(engaged: boolean, reason: string | null) {
  return {
    schema_version: "1",
    live_enabled: false,
    authorized: [],
    kill_switch: { engaged, reason, engaged_at: engaged ? 1700000000 : null },
    promotion_available: false,
    promotion_code: "live_promotion_owner_deferred",
  };
}

function makeClient(over: Partial<OperationsClient> = {}): OperationsClient {
  const v = view();
  return {
    getOperations: vi.fn().mockResolvedValue(v),
    promote: vi.fn().mockResolvedValue({ schema_version: "1", code: "live_disabled", ok: false }),
    pauseEntries: vi.fn().mockResolvedValue({ schema_version: "1", code: "entries_paused", ok: true }),
    resumeEntries: vi.fn().mockResolvedValue({ schema_version: "1", code: "entries_resumed", ok: true }),
    engageKill: vi.fn().mockResolvedValue({ schema_version: "1", code: "kill_switch_engaged", ok: true }),
    releaseKill: vi.fn().mockResolvedValue({ schema_version: "1", code: "kill_switch_released", ok: true }),
    ackAlert: vi.fn().mockResolvedValue({ schema_version: "1", code: "acknowledged", ok: true }),
    listDeploymentRecords: vi.fn().mockResolvedValue([]),
    getDeploymentRecord: vi.fn().mockResolvedValue({
      deployment_id: "dep-1",
      venue: "kraken",
      pair: "SUIUSD",
      created_at_ms: 1700000000000,
      state: "refused",
      config: {},
      schedule: {},
      last_execution_summary: "",
    }),
    ...over,
  };
}

function alert(over: Partial<AlertRow> = {}): AlertRow {
  return {
    id: "a1",
    kind: "live_refused",
    severity: "warning",
    code: "live_disabled",
    venue: "kraken",
    pair: "SUIUSD",
    count: 2,
    first_ts: 1700000000,
    last_ts: 1700000600,
    acknowledged: false,
    ...over,
  };
}

function deployment(over: Partial<DeploymentRow> = {}): DeploymentRow {
  return {
    venue: "kraken",
    pair: "SUIUSD",
    pack_id: "trend-follow",
    pack_version: "1.0.0",
    mode: "paper",
    entries_paused: false,
    promotion: { available: false, code: "live_disabled" },
    ...over,
  };
}

describe("OperationsView Signal layout: status banner", () => {
  it("groups the live banner and the kill switch into one status banner with verbatim copy", async () => {
    const client = makeClient();
    render(<OperationsView client={client} />);
    const banner = await screen.findByTestId("ops-status-banner");
    expect(banner).toBeDefined();

    const liveStatus = within(banner).getByTestId("ops-live-status");
    expect(liveStatus.textContent).toContain(DISABLED_TEXT);
    expect(liveStatus.textContent).toContain(PROMO_DEFERRED_TEXT);

    const kill = within(banner).getByTestId("ops-kill");
    expect(kill.textContent).toContain(KILL_RELEASED_TEXT);
    expect(kill.textContent).toContain(KILL_HELPER);
  });

  it("keeps the no-grant banner and promotion-deferred copy inside the status banner", async () => {
    const client = makeClient({
      getOperations: vi.fn().mockResolvedValue(
        view({ live: { ...live(false, null), live_enabled: true, authorized: [] } }),
      ),
    });
    render(<OperationsView client={client} />);
    const banner = await screen.findByTestId("ops-status-banner");
    const liveStatus = within(banner).getByTestId("ops-live-status");
    expect(liveStatus.textContent).toContain(NO_GRANTS_TEXT);
    expect(liveStatus.textContent).toContain(PROMO_DEFERRED_TEXT);
  });

  it("renders the kill-switch state line as its own status line, released or engaged", async () => {
    const released = makeClient();
    const { unmount } = render(<OperationsView client={released} />);
    const releasedState = await screen.findByTestId("ops-kill-state");
    expect(releasedState.textContent).toBe(KILL_RELEASED_TEXT);
    expect(within(screen.getByTestId("ops-kill")).queryByTestId("ops-kill-release")).toBeNull();
    unmount();

    const engaged = makeClient({
      getOperations: vi.fn().mockResolvedValue(view({ live: live(true, "operator-halt") })),
    });
    render(<OperationsView client={engaged} />);
    const engagedState = await screen.findByTestId("ops-kill-state");
    expect(engagedState.textContent).toBe("Kill switch: engaged — operator-halt");
    expect(screen.getByTestId("ops-kill-release")).toBeDefined();
    const killPanel = screen.getByTestId("ops-kill");
    expect(killPanel.textContent).toContain(KILL_HELPER);
  });

  it("keeps the kill switch reason control and disabled engage behaviour", async () => {
    const client = makeClient();
    render(<OperationsView client={client} />);
    const reason = (await screen.findByTestId("ops-kill-reason")) as HTMLInputElement;
    const engage = screen.getByTestId("ops-kill-engage") as HTMLButtonElement;
    expect(reason.value).toBe("");
    expect(engage.disabled).toBe(true);
    fireEvent.change(reason, { target: { value: "operator-test" } });
    expect(engage.disabled).toBe(false);
    fireEvent.click(engage);
    await waitFor(() => {
      expect(client.engageKill).toHaveBeenCalledWith("operator-test");
    });
  });
});

describe("OperationsView Signal layout: mode header", () => {
  it("shows the current operation mode label from the helper in a deployments mode header", async () => {
    const client = makeClient({
      getOperations: vi.fn().mockResolvedValue(
        view({ deployments: [deployment({ mode: "paper" })] }),
      ),
    });
    render(<OperationsView client={client} />);
    const modeHeader = await screen.findByTestId("ops-mode-header");
    const chips = within(modeHeader).getAllByText("Paper");
    expect(chips.length).toBeGreaterThanOrEqual(1);
    expect(modeHeader.textContent).toContain("Paper");
  });

  it("keeps the unknown-mode helper output verbatim in the mode header", async () => {
    const client = makeClient({
      getOperations: vi.fn().mockResolvedValue(
        view({ deployments: [deployment({ mode: "ghost" })] }),
      ),
    });
    render(<OperationsView client={client} />);
    const modeHeader = await screen.findByTestId("ops-mode-header");
    expect(modeHeader.textContent).toContain("(unknown mode: ghost)");
  });

  it("lists each distinct running mode once, in first-appearance order", async () => {
    const client = makeClient({
      getOperations: vi.fn().mockResolvedValue(
        view({
          deployments: [
            deployment({ venue: "kraken", pair: "SUIUSD", mode: "paper" }),
            deployment({ venue: "coinbase", pair: "SUIUSD", mode: "live" }),
            deployment({ venue: "kraken", pair: "XBT/USD", mode: "paper" }),
          ],
        }),
      ),
    });
    render(<OperationsView client={client} />);
    const modeHeader = await screen.findByTestId("ops-mode-header");
    const chips = Array.from(
      modeHeader.querySelectorAll(".kbot-ops__mode-chip"),
    ).map((el) => el.textContent);
    expect(chips).toEqual(["Paper", "Live"]);
  });
});

describe("OperationsView Signal layout: deployments", () => {
  it("renders each deployment as a scannable card with mode label, entries state and controls", async () => {
    const client = makeClient({
      getOperations: vi.fn().mockResolvedValue(
        view({ deployments: [deployment()] }),
      ),
    });
    render(<OperationsView client={client} />);
    const scroll = await screen.findByTestId("ops-deployments-scroll");
    const list = within(scroll).getByTestId("ops-deployments");
    const card = within(list).getByTestId("ops-deployment-kraken-SUIUSD");
    expect(card.textContent).toContain("trend-follow");
    expect(card.textContent).toContain("Paper");
    expect(card.textContent).toMatch(/active/i);
    expect(within(card).getByTestId("ops-pause-kraken-SUIUSD")).toBeDefined();
    expect(within(card).getByTestId("ops-resume-kraken-SUIUSD")).toBeDefined();
    expect(within(card).getByTestId("ops-promote-kraken-SUIUSD")).toBeDefined();
  });

  it("keeps the row-scoped refused result inside the card", async () => {
    const client = makeClient({
      getOperations: vi.fn().mockResolvedValue(view({ deployments: [deployment()] })),
      promote: vi.fn().mockResolvedValue({
        schema_version: "1",
        code: "live_disabled",
        ok: false,
        message: "KRELLBOT_ENABLE_LIVE is not '1'; live send refused",
        effect: "refused",
      }),
    });
    render(<OperationsView client={client} />);
    fireEvent.click(await screen.findByTestId("ops-promote-kraken-SUIUSD"));
    await waitFor(() => {
      expect(client.promote).toHaveBeenCalledWith("kraken", "SUIUSD", "deployment");
    });
    const result = await screen.findByTestId("ops-promote-result-kraken-SUIUSD");
    expect(result.getAttribute("role")).toBe("status");
    expect(result.textContent).toBe(
      "Refused: Live disabled — KRELLBOT_ENABLE_LIVE is not '1'; live send refused",
    );
    const card = screen.getByTestId("ops-deployment-kraken-SUIUSD");
    expect(card.contains(result)).toBe(true);
  });

  it("renders the no-records empty text when there are no deployments", async () => {
    const client = makeClient();
    render(<OperationsView client={client} />);
    const list = await screen.findByTestId("ops-deployments");
    expect(list.textContent).toContain(NO_DEPLOYMENTS_TEXT);
    expect(screen.queryByTestId("ops-deployment-kraken-SUIUSD")).toBeNull();
  });

  it("keeps both pause and resume usable from the card and refreshes after each", async () => {
    const getOperations = vi.fn().mockResolvedValue(view({ deployments: [deployment()] }));
    const client = makeClient({ getOperations });
    render(<OperationsView client={client} />);
    await screen.findByTestId("ops-deployment-kraken-SUIUSD");
    fireEvent.click(screen.getByTestId("ops-pause-kraken-SUIUSD"));
    await waitFor(() => {
      expect(client.pauseEntries).toHaveBeenCalledWith("kraken", "SUIUSD");
    });
    fireEvent.click(screen.getByTestId("ops-resume-kraken-SUIUSD"));
    await waitFor(() => {
      expect(client.resumeEntries).toHaveBeenCalledWith("kraken", "SUIUSD");
    });
  });
});

describe("OperationsView Signal layout: deployment history", () => {
  it("wraps the dense history table in an internal scroll region instead of widening the page", async () => {
    const client = makeClient();
    render(<OperationsView client={client} />);
    const scroll = await screen.findByTestId("ops-history-scroll");
    const table = await within(scroll).findByTestId("ops-history-table");
    expect(table).toBeDefined();
    expect(scroll.contains(table)).toBe(true);
    const section = screen.getByTestId("ops-deployment-history");
    expect(section.contains(scroll)).toBe(true);
  });

  it("keeps the history refused/deferred outcomes and empty state from the real client", async () => {
    const client = makeClient({
      listDeploymentRecords: vi.fn().mockResolvedValue([
        {
          deployment_id: "dep-refused",
          venue: "kraken",
          pair: "SUIUSD",
          created_at_ms: 1700000000000,
          state: "refused",
          config: { mode: "paper" },
          schedule: {},
          last_execution_summary: "",
        },
        {
          deployment_id: "dep-deferred",
          venue: "kraken",
          pair: "SUIUSD",
          created_at_ms: 1700000100000,
          state: "deferred",
          config: {},
          schedule: {},
          last_execution_summary: "",
        },
      ]),
    });
    render(<OperationsView client={client} />);
    const scroll = await screen.findByTestId("ops-history-scroll");
    await waitFor(() => {
      expect(within(scroll).getByTestId("ops-history-row-dep-refused").textContent).toContain(
        "refused",
      );
    });
    expect(within(scroll).getByTestId("ops-history-row-dep-deferred").textContent).toContain(
      "deferred",
    );
    // Rows are present, so the empty state must not be.
    expect(within(scroll).queryByTestId("ops-history-empty")).toBeNull();
  });
});

describe("OperationsView Signal layout: alerts groups", () => {
  it("groups alerts by severity with critical first, keeping kind/severity/code labels", async () => {
    const alerts = [
      alert({ id: "w1", kind: "live_refused", severity: "warning", code: "live_disabled" }),
      alert({ id: "c1", kind: "venue_unreachable", severity: "critical", code: "needs_reconcile", count: 1 }),
      alert({ id: "i1", kind: "circuit_open_probe", severity: "info", code: null, venue: null, pair: null }),
    ];
    const client = makeClient({
      getOperations: vi.fn().mockResolvedValue(view({ alerts })),
    });
    render(<OperationsView client={client} />);
    const groups = await screen.findByTestId("ops-alert-groups");
    const heads = groups.querySelectorAll("[data-testid^='ops-severity-group-']");
    expect(Array.from(heads).map((el) => el.getAttribute("data-testid"))).toEqual([
      "ops-severity-group-critical",
      "ops-severity-group-warning",
      "ops-severity-group-info",
    ]);
    expect(heads[0]?.textContent).toContain("Critical");
    expect(heads[1]?.textContent).toContain("Warning");
    expect(heads[2]?.textContent).toContain("Info");

    const criticalRow = screen.getByTestId("ops-alert-c1");
    expect(criticalRow.textContent).toContain("Venue unreachable");
    expect(criticalRow.textContent).toContain("Critical");
    expect(criticalRow.textContent).toContain("Needs reconcile");
    expect(criticalRow.textContent).not.toContain("needs_reconcile");
    expect(criticalRow.textContent).toContain("×1");

    const warningRow = screen.getByTestId("ops-alert-w1");
    expect(warningRow.textContent).toContain("Live refused");
    expect(warningRow.textContent).toContain("Live disabled");
    expect(warningRow.textContent).not.toContain("live_disabled");
    expect(warningRow.textContent).toContain("×2");

    const infoRow = screen.getByTestId("ops-alert-i1");
    expect(infoRow.textContent).toContain("Circuit open probe");
    expect(infoRow.textContent).toContain("—");
  });

  it("keeps each severity group's rows inside their group container", async () => {
    const alerts = [
      alert({ id: "c1", severity: "critical", kind: "venue_unreachable" }),
      alert({ id: "c2", severity: "critical", kind: "store_fault", code: "store_error" }),
      alert({ id: "w1", severity: "warning" }),
    ];
    const client = makeClient({
      getOperations: vi.fn().mockResolvedValue(view({ alerts })),
    });
    render(<OperationsView client={client} />);
    await screen.findByTestId("ops-alert-groups");
    const criticalGroup = screen.getByTestId("ops-severity-group-critical").closest("li");
    expect(criticalGroup).not.toBeNull();
    expect(criticalGroup!.contains(screen.getByTestId("ops-alert-c1"))).toBe(true);
    expect(criticalGroup!.contains(screen.getByTestId("ops-alert-c2"))).toBe(true);
    expect(criticalGroup!.contains(screen.getByTestId("ops-alert-w1"))).toBe(false);
    const warningGroup = screen.getByTestId("ops-severity-group-warning").closest("li");
    expect(warningGroup!.contains(screen.getByTestId("ops-alert-w1"))).toBe(true);
  });

  it("shows 'No alerts.' with no severity groups when the server has no alerts", async () => {
    const client = makeClient();
    render(<OperationsView client={client} />);
    const alertsList = await screen.findByTestId("ops-alerts");
    expect(alertsList.textContent).toContain(NO_ALERTS_TEXT);
    expect(
      alertsList.querySelectorAll("[data-testid^='ops-severity-group-']").length,
    ).toBe(0);
    expect(screen.queryByTestId("ops-alerts-empty")).toBeNull();
  });

  it("shows the filter no-matches text without the no-alerts text when filters narrow to nothing", async () => {
    const client = makeClient({
      getOperations: vi.fn().mockResolvedValue(
        view({ alerts: [alert({ id: "w1" })] }),
      ),
    });
    render(<OperationsView client={client} />);
    await screen.findByTestId("ops-alert-w1");
    fireEvent.change(screen.getByTestId("ops-alerts-filter-query"), {
      target: { value: "no-such-code" },
    });
    expect(screen.queryByTestId("ops-alert-w1")).toBeNull();
    const empty = screen.getByTestId("ops-alerts-empty");
    expect(empty.textContent).toBe(NO_ALERTS_MATCH_TEXT);
    const alertsList = screen.getByTestId("ops-alerts");
    expect(alertsList.textContent).not.toContain(NO_ALERTS_TEXT);
    fireEvent.click(screen.getByTestId("ops-alerts-filter-clear"));
    await screen.findByTestId("ops-alert-w1");
    expect(screen.queryByTestId("ops-alerts-empty")).toBeNull();
  });

  it("keeps the acknowledge action inside the grouped alert card", async () => {
    const client = makeClient({
      getOperations: vi.fn().mockResolvedValue(view({ alerts: [alert({ id: "w1" })] })),
    });
    render(<OperationsView client={client} />);
    await screen.findByTestId("ops-alert-w1");
    fireEvent.click(screen.getByTestId("ops-alert-ack-w1"));
    await waitFor(() => {
      expect(client.ackAlert).toHaveBeenCalledWith("w1");
    });
  });
});

describe("OperationsView Signal layout: refresh and csv retention", () => {
  it("keeps the manual Refresh button label and the exact stale copy after a failed read", async () => {
    let calls = 0;
    const client = makeClient({
      getOperations: vi.fn().mockImplementation(async () => {
        calls += 1;
        if (calls === 2) {
          throw new Error("operations view failed: 503");
        }
        return view({ deployments: [deployment()] });
      }),
    });
    render(<OperationsView client={client} />);
    const refresh = await screen.findByTestId("ops-refresh");
    expect(refresh.textContent).toBe(MANUAL_REFRESH_LABEL);
    // Drive the failing read explicitly: no auto-retry is asserted anywhere.
    fireEvent.click(refresh);
    await waitFor(() => {
      expect(client.getOperations).toHaveBeenCalledTimes(2);
    });
    const stale = await screen.findByTestId("ops-stale-warning");
    expect(stale.getAttribute("role")).toBe("alert");
    expect(stale.textContent).toBe(
      `${STALE_PREFIX} — refresh failed: operations view failed: 503; ${STALE_SUFFIX}.`,
    );
    // The retained view stays present alongside the stale warning.
    expect(screen.getByTestId("ops-deployment-kraken-SUIUSD").textContent).toContain(
      "trend-follow",
    );
  });

  it("still triggers the alerts CSV export from the grouped alerts panel", async () => {
    const client = makeClient({
      getOperations: vi.fn().mockResolvedValue(view({ alerts: [alert()] })),
    });
    render(<OperationsView client={client} />);
    await screen.findByTestId("ops-alert-a1");

    const createObjectURL = vi.fn<(input: Blob | MediaSource) => string>(() => "blob:ops");
    const revokeObjectURL = vi.fn();
    const originalCreate = URL.createObjectURL;
    const originalRevoke = URL.revokeObjectURL;
    URL.createObjectURL = createObjectURL as unknown as typeof URL.createObjectURL;
    URL.revokeObjectURL = revokeObjectURL as unknown as typeof URL.revokeObjectURL;
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    try {
      fireEvent.click(screen.getByTestId("ops-alerts-csv-export"));
      await waitFor(() => {
        expect(createObjectURL).toHaveBeenCalledTimes(1);
      });
      const blob = createObjectURL.mock.calls[0]?.[0] as Blob;
      const text = await blob.text();
      expect(text.split("\n")[0]).toBe(
        "id,kind,severity,code,venue,pair,count,first_ts,last_ts,acknowledged",
      );
    } finally {
      clickSpy.mockRestore();
      URL.createObjectURL = originalCreate;
      URL.revokeObjectURL = originalRevoke;
    }
  });

  it("still triggers the deployments CSV export from the deployments panel", async () => {
    const client = makeClient({
      getOperations: vi.fn().mockResolvedValue(
        view({ deployments: [deployment({ entries_paused: true })] }),
      ),
    });
    render(<OperationsView client={client} />);
    await screen.findByTestId("ops-deployment-kraken-SUIUSD");

    const createObjectURL = vi.fn<(input: Blob | MediaSource) => string>(() => "blob:ops");
    const revokeObjectURL = vi.fn();
    const originalCreate = URL.createObjectURL;
    const originalRevoke = URL.revokeObjectURL;
    URL.createObjectURL = createObjectURL as unknown as typeof URL.createObjectURL;
    URL.revokeObjectURL = revokeObjectURL as unknown as typeof URL.revokeObjectURL;
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    try {
      fireEvent.click(screen.getByTestId("ops-deployments-csv-export"));
      await waitFor(() => {
        expect(createObjectURL).toHaveBeenCalledTimes(1);
      });
      const blob = createObjectURL.mock.calls[0]?.[0] as Blob;
      expect(await blob.text()).toBe(
        "pack_id,venue,pair,mode,entries\r\n" +
          "trend-follow,kraken,SUIUSD,paper,paused",
      );
    } finally {
      clickSpy.mockRestore();
      URL.createObjectURL = originalCreate;
      URL.revokeObjectURL = originalRevoke;
    }
  });

  it("keeps the acknowledged alerts panel mounted with its refresh control", async () => {
    const listAcknowledged = vi.fn().mockResolvedValue([
      alert({ id: "ack1", acknowledged: true }),
    ]);
    const client = makeClient({ listAcknowledged } as unknown as Partial<OperationsClient>);
    render(<OperationsView client={client} />);
    const panel = await screen.findByTestId("ops-acknowledged-alerts");
    await waitFor(() => {
      expect(within(panel).getByTestId("ops-acknowledged-alert-ack1")).toBeDefined();
    });
    fireEvent.click(within(panel).getByTestId("ops-acknowledged-refresh"));
    await waitFor(() => {
      expect(listAcknowledged).toHaveBeenCalledTimes(2);
    });
  });
});

describe("OperationsView Signal layout: preserved navigation", () => {
  it("keeps the alerts filter controls reachable and working from the grouped panel", async () => {
    const alerts = [
      alert({ id: "w1", severity: "warning", code: "live_disabled", venue: "kraken" }),
      alert({ id: "c1", severity: "critical", kind: "venue_unreachable", code: "needs_reconcile", venue: "coinbase" }),
    ];
    const client = makeClient({
      getOperations: vi.fn().mockResolvedValue(view({ alerts })),
    });
    render(<OperationsView client={client} />);
    await screen.findByTestId("ops-alert-w1");
    const severity = screen.getByTestId("ops-alerts-filter-severity") as HTMLSelectElement;
    expect(severity.value).toBe("all");
    fireEvent.change(severity, { target: { value: "warning" } });
    expect(screen.queryByTestId("ops-alert-c1")).toBeNull();
    expect(screen.getByTestId("ops-alert-w1")).toBeDefined();
    // The severity group headers follow the filtered set.
    const groups = screen.getByTestId("ops-alert-groups");
    expect(
      groups.querySelectorAll("[data-testid^='ops-severity-group-']").length,
    ).toBe(1);
    fireEvent.change(severity, { target: { value: "all" } });
    expect(screen.getByTestId("ops-alert-c1")).toBeDefined();
    expect(screen.getByTestId("ops-alert-w1")).toBeDefined();
  });
});
