import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OperationsView } from "./OperationsView";
import type {
  OperationsClient,
  OperationsViewModel,
} from "./client";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const DISABLED_TEXT =
  "Live trading is disabled in this build (KRELLBOT_ENABLE_LIVE is not 1).";
const NO_GRANTS_TEXT =
  "Live trading is not authorized: no operator grant on file.";
const PROMO_DEFERRED_TEXT = "Promotion to live is owner-deferred.";
const KILL_HELPER = "Engaging stops new entries and all live sends. It does not sell or disarm.";
const KILL_RELEASED_TEXT = "Kill switch: released";
const NO_ALERTS_TEXT = "No alerts.";

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
  const v = view();
  return {
    getOperations: vi.fn().mockResolvedValue(v),
    promote: vi.fn().mockResolvedValue({ schema_version: "1", code: "live_disabled", ok: false }),
    pauseEntries: vi.fn().mockResolvedValue({ schema_version: "1", code: "entries_paused", ok: true }),
    resumeEntries: vi.fn().mockResolvedValue({ schema_version: "1", code: "entries_resumed", ok: true }),
    engageKill: vi.fn().mockResolvedValue({ schema_version: "1", code: "kill_switch_engaged", ok: true }),
    releaseKill: vi.fn().mockResolvedValue({ schema_version: "1", code: "kill_switch_released", ok: true }),
    ackAlert: vi.fn().mockResolvedValue({ schema_version: "1", code: "acknowledged", ok: true }),
    ...over,
  };
}

describe("OperationsView empty / disabled state", () => {
  it("renders the disabled banner verbatim when live_enabled is false", async () => {
    const client = makeClient();
    render(<OperationsView client={client} />);
    const banner = await screen.findByTestId("ops-live-status");
    expect(banner.textContent).toMatch(/Live trading is disabled/);
    expect(banner.textContent).toContain(DISABLED_TEXT);
    expect(banner.textContent).toContain(PROMO_DEFERRED_TEXT);
  });

  it("renders the no-grant copy when live_enabled but authorized is empty", async () => {
    const client = makeClient({
      getOperations: vi.fn().mockResolvedValue(
        view({
          live: {
            schema_version: "1",
            live_enabled: true,
            authorized: [],
            kill_switch: { engaged: false, reason: null, engaged_at: null },
            promotion_available: false,
            promotion_code: "live_promotion_owner_deferred",
          },
        }),
      ),
    });
    render(<OperationsView client={client} />);
    const banner = await screen.findByTestId("ops-live-status");
    expect(banner.textContent).toContain(NO_GRANTS_TEXT);
    expect(banner.textContent).toContain(PROMO_DEFERRED_TEXT);
  });

  it("renders the operator grant list when authorized is non-empty", async () => {
    const client = makeClient({
      getOperations: vi.fn().mockResolvedValue(
        view({
          live: {
            schema_version: "1",
            live_enabled: true,
            authorized: [{ venue: "kraken", pair: "SUIUSD" }],
            kill_switch: { engaged: false, reason: null, engaged_at: null },
            promotion_available: false,
            promotion_code: "live_promotion_owner_deferred",
          },
        }),
      ),
    });
    render(<OperationsView client={client} />);
    const banner = await screen.findByTestId("ops-live-status");
    expect(banner.textContent).toContain("kraken SUIUSD");
  });

  it("never renders 'Go live', 'Start live', or 'Enable live'", async () => {
    const client = makeClient();
    render(<OperationsView client={client} />);
    await screen.findByTestId("ops-live-status");
    const root = screen.getByTestId("operations-view");
    expect(root.textContent ?? "").not.toMatch(/Go live|Start live|Enable live/);
  });
});

describe("OperationsView kill switch", () => {
  it("renders the released state and helper text", async () => {
    const client = makeClient();
    render(<OperationsView client={client} />);
    const kill = await screen.findByTestId("ops-kill");
    expect(kill.textContent).toContain(KILL_RELEASED_TEXT);
    expect(kill.textContent).toContain(KILL_HELPER);
    const reason = screen.getByTestId("ops-kill-reason") as HTMLInputElement;
    const engage = screen.getByTestId("ops-kill-engage") as HTMLButtonElement;
    expect(reason.value).toBe("");
    expect(engage.disabled).toBe(true);
  });

  it("engages kill when reason is provided, then refreshes", async () => {
    let refreshed = false;
    const client = makeClient({
      getOperations: vi.fn().mockImplementation(async () => {
        if (!refreshed) {
          refreshed = true;
          return view();
        }
        return view({
          live: {
            schema_version: "1",
            live_enabled: false,
            authorized: [],
            kill_switch: { engaged: true, reason: "operator-test", engaged_at: 1700000000 },
            promotion_available: false,
            promotion_code: "live_promotion_owner_deferred",
          },
        });
      }),
      engageKill: vi.fn().mockResolvedValue({
        schema_version: "1",
        code: "kill_switch_engaged",
        ok: true,
        kill_switch: { engaged: true, reason: "operator-test", engaged_at: 1700000000 },
      }),
    });
    render(<OperationsView client={client} />);
    const reason = (await screen.findByTestId("ops-kill-reason")) as HTMLInputElement;
    fireEvent.change(reason, { target: { value: "operator-test" } });
    const engage = await screen.findByTestId("ops-kill-engage");
    fireEvent.click(engage);
    await waitFor(() => {
      expect(client.engageKill).toHaveBeenCalledWith("operator-test");
    });
    await waitFor(() => {
      expect(screen.getByTestId("ops-kill").textContent).toMatch(
        /Kill switch: engaged — operator-test/,
      );
    });
    const release = await screen.findByTestId("ops-kill-release");
    expect(release).toBeDefined();
  });
});

describe("OperationsView deployments", () => {
  it("renders one row per deployment with mode verbatim and pause/resume buttons", async () => {
    const client = makeClient({
      getOperations: vi.fn().mockResolvedValue(
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
      ),
    });
    render(<OperationsView client={client} />);
    const row = await screen.findByTestId("ops-deployment-kraken-SUIUSD");
    expect(row.textContent).toContain("trend-follow");
    expect(row.textContent).toContain("paper");
    expect(row.textContent).toMatch(/active/i);
    expect(screen.getByTestId("ops-promote-kraken-SUIUSD")).toBeDefined();
  });

  it("shows refused line after a failed promote", async () => {
    const client = makeClient({
      promote: vi
        .fn()
        .mockResolvedValueOnce({
          schema_version: "1",
          code: "live_disabled",
          ok: false,
          message: "KRELLBOT_ENABLE_LIVE is not '1'; live send refused",
          effect: "refused",
          venue: "kraken",
          pair: "SUIUSD",
        })
        .mockResolvedValue({
          schema_version: "1",
          code: "live_disabled",
          ok: false,
        }),
      getOperations: vi.fn().mockResolvedValue(
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
      ),
    });
    render(<OperationsView client={client} />);
    const promote = await screen.findByTestId("ops-promote-kraken-SUIUSD");
    fireEvent.click(promote);
    await waitFor(() => {
      expect(client.promote).toHaveBeenCalledWith("kraken", "SUIUSD", "deployment");
    });
    const result = await screen.findByTestId("ops-promote-result-kraken-SUIUSD");
    expect(result.getAttribute("role")).toBe("status");
    expect(result.textContent).toMatch(/Refused: live_disabled/);
  });

  it("shows refused line when pause returns ok=false on a live row", async () => {
    const client = makeClient({
      pauseEntries: vi.fn().mockResolvedValue({
        schema_version: "1",
        code: "stored_mode_not_paper",
        ok: false,
        message: "stored mode is 'live'",
        effect: "refused",
      }),
      getOperations: vi.fn().mockResolvedValue(
        view({
          deployments: [
            {
              venue: "kraken",
              pair: "SUIUSD",
              pack_id: "live-pack",
              pack_version: "1.0.0",
              mode: "live",
              entries_paused: false,
              promotion: { available: false, code: "live_disabled" },
            },
          ],
        }),
      ),
    });
    render(<OperationsView client={client} />);
    const pause = await screen.findByTestId("ops-pause-kraken-SUIUSD");
    fireEvent.click(pause);
    await waitFor(() => {
      expect(client.pauseEntries).toHaveBeenCalledWith("kraken", "SUIUSD");
    });
    const result = await screen.findByTestId("ops-pause-result-kraken-SUIUSD");
    expect(result.textContent).toMatch(/stored_mode_not_paper/);
  });
});

describe("OperationsView alerts", () => {
  it("renders 'No alerts.' when the alert list is empty", async () => {
    const client = makeClient();
    render(<OperationsView client={client} />);
    const alerts = await screen.findByTestId("ops-alerts");
    expect(alerts.textContent).toContain(NO_ALERTS_TEXT);
  });

  it("renders alert rows with acknowledge buttons", async () => {
    const client = makeClient({
      getOperations: vi.fn().mockResolvedValue(
        view({
          alerts: [
            {
              id: "abc123",
              kind: "live_refused",
              severity: "warning",
              code: "live_disabled",
              venue: "kraken",
              pair: "SUIUSD",
              count: 2,
              first_ts: 1700000000,
              last_ts: 1700000600,
              acknowledged: false,
            },
          ],
        }),
      ),
    });
    render(<OperationsView client={client} />);
    const row = await screen.findByTestId("ops-alert-abc123");
    expect(row.textContent).toContain("live_refused");
    expect(row.textContent).toContain("live_disabled");
    expect(row.textContent).toContain("×2");
    const ack = screen.getByTestId("ops-alert-ack-abc123");
    fireEvent.click(ack);
    await waitFor(() => {
      expect(client.ackAlert).toHaveBeenCalledWith("abc123");
    });
  });
});