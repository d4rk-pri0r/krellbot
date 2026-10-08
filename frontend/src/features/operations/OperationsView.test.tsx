import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { OperationsView } from "./OperationsView";
import type {
  OperationsClient,
  OperationsViewModel,
} from "./client";
import {
  OPERATIONS_READ_TIMEOUT_MS,
  OPERATIONS_REFRESH_INTERVAL_MS,
} from "./useOperationsRefresh";

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

describe("OperationsView refresh failure after prior success", () => {
  const deployment = {
    venue: "kraken",
    pair: "SUIUSD",
    pack_id: "trend-follow",
    pack_version: "1.0.0",
    mode: "paper",
    entries_paused: false,
    promotion: { available: false, code: "live_disabled" },
  };

  it("labels the retained view stale when a refresh after a successful pause fails, then clears it on recovery", async () => {
    let calls = 0;
    const client = makeClient({
      getOperations: vi.fn().mockImplementation(async () => {
        calls += 1;
        if (calls === 2) {
          throw new Error("operations view failed: 503");
        }
        return view({ deployments: [deployment] });
      }),
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
    });
    render(<OperationsView client={client} />);
    const pause = await screen.findByTestId("ops-pause-kraken-SUIUSD");
    fireEvent.click(pause);
    await waitFor(() => {
      expect(client.pauseEntries).toHaveBeenCalledWith("kraken", "SUIUSD");
    });

    const stale = await screen.findByTestId("ops-stale-warning");
    expect(stale.getAttribute("role")).toBe("alert");
    expect(stale.textContent).toMatch(/stale/i);
    expect(stale.textContent).toContain("operations view failed: 503");
    expect(stale.textContent).toMatch(/last known state/i);
    expect(stale.textContent).toMatch(/not current server state/i);

    // The last observed view is retained, not replaced with invented data.
    const row = screen.getByTestId("ops-deployment-kraken-SUIUSD");
    expect(row.textContent).toContain("trend-follow");
    expect(row.textContent).toMatch(/active/i);

    // A later successful refresh clears the warning and keeps the view present.
    fireEvent.click(screen.getByTestId("ops-resume-kraken-SUIUSD"));
    await waitFor(() => {
      expect(client.resumeEntries).toHaveBeenCalledWith("kraken", "SUIUSD");
    });
    await waitFor(() => {
      expect(screen.queryByTestId("ops-stale-warning")).toBeNull();
    });
    expect(screen.getByTestId("ops-deployment-kraken-SUIUSD").textContent).toContain(
      "trend-follow",
    );
  });
});

describe("OperationsView pause/resume command failure", () => {
  const deployment = {
    venue: "kraken",
    pair: "SUIUSD",
    pack_id: "trend-follow",
    pack_version: "1.0.0",
    mode: "paper",
    entries_paused: false,
    promotion: { available: false, code: "live_disabled" },
  };

  function deploymentView(): OperationsViewModel {
    return view({ deployments: [deployment] });
  }

  it("a rejected pause shows a row-scoped unknown-outcome alert, keeps the last known view, and does not refresh or invent a result", async () => {
    const getOperations = vi.fn().mockResolvedValue(deploymentView());
    const client = makeClient({
      getOperations,
      pauseEntries: vi.fn().mockRejectedValue(new Error("paper.pause_entries failed: 503")),
    });
    render(<OperationsView client={client} />);
    const pause = await screen.findByTestId("ops-pause-kraken-SUIUSD");
    fireEvent.click(pause);

    const alert = await screen.findByTestId("ops-pause-error-kraken-SUIUSD");
    expect(alert.getAttribute("role")).toBe("alert");
    expect(alert.textContent).toMatch(/pause/i);
    expect(alert.textContent).toMatch(/unknown/i);
    expect(alert.textContent).toContain("paper.pause_entries failed: 503");

    // No fabricated server-confirmed refusal for the rejected command.
    expect(alert.textContent).not.toMatch(/Refused/);
    expect(screen.queryByTestId("ops-pause-result-kraken-SUIUSD")).toBeNull();

    // The last known row is retained, not rewritten from a stale local guess.
    const row = screen.getByTestId("ops-deployment-kraken-SUIUSD");
    expect(row.textContent).toContain("trend-follow");
    expect(row.textContent).toMatch(/active/i);

    // A transport failure must not trigger a refresh of current server state.
    await new Promise((resolve) => setTimeout(resolve, 25));
    expect(getOperations).toHaveBeenCalledTimes(1);
  });

  it("a rejected resume shows a row-scoped unknown-outcome alert without refreshing", async () => {
    const getOperations = vi.fn().mockResolvedValue(deploymentView());
    const client = makeClient({
      getOperations,
      resumeEntries: vi.fn().mockRejectedValue(new Error("paper.resume_entries failed: network")),
    });
    render(<OperationsView client={client} />);
    const resume = await screen.findByTestId("ops-resume-kraken-SUIUSD");
    fireEvent.click(resume);

    const alert = await screen.findByTestId("ops-resume-error-kraken-SUIUSD");
    expect(alert.getAttribute("role")).toBe("alert");
    expect(alert.textContent).toMatch(/resume/i);
    expect(alert.textContent).toMatch(/unknown/i);
    expect(alert.textContent).toContain("paper.resume_entries failed: network");
    expect(screen.queryByTestId("ops-resume-result-kraken-SUIUSD")).toBeNull();

    await new Promise((resolve) => setTimeout(resolve, 25));
    expect(getOperations).toHaveBeenCalledTimes(1);
  });

  it("a new explicit pause request clears the superseded result, so a later unknown transport outcome never appears alongside an old Refused status", async () => {
    const client = makeClient({
      getOperations: vi.fn().mockResolvedValue(deploymentView()),
      pauseEntries: vi
        .fn()
        .mockResolvedValueOnce({
          schema_version: "1",
          code: "stored_mode_not_paper",
          ok: false,
          message: "stored mode is 'live'",
          effect: "refused",
        })
        .mockRejectedValueOnce(new Error("paper.pause_entries failed: 503")),
    });
    render(<OperationsView client={client} />);
    const pause = await screen.findByTestId("ops-pause-kraken-SUIUSD");
    fireEvent.click(pause);
    const refusal = await screen.findByTestId("ops-pause-result-kraken-SUIUSD");
    expect(refusal.getAttribute("role")).toBe("status");
    expect(refusal.textContent).toMatch(/Refused: stored_mode_not_paper/);
    expect(screen.queryByTestId("ops-pause-error-kraken-SUIUSD")).toBeNull();

    // A new explicit attempt supersedes the earlier outcome: the old Refused
    // status must be gone before the request is sent, so the transport failure
    // is reported on its own instead of next to the stale refusal.
    fireEvent.click(pause);
    const alert = await screen.findByTestId("ops-pause-error-kraken-SUIUSD");
    expect(alert.getAttribute("role")).toBe("alert");
    expect(alert.textContent).toMatch(/unknown/i);
    expect(alert.textContent).not.toMatch(/stored_mode_not_paper/);
    expect(screen.queryByTestId("ops-pause-result-kraken-SUIUSD")).toBeNull();
  });

  it("a new explicit resume request clears its superseded result before sending", async () => {
    const client = makeClient({
      getOperations: vi.fn().mockResolvedValue(deploymentView()),
      resumeEntries: vi
        .fn()
        .mockResolvedValueOnce({
          schema_version: "1",
          code: "no_active_entries",
          ok: false,
          message: "nothing to resume",
          effect: "refused",
        })
        .mockRejectedValueOnce(new Error("paper.resume_entries failed: network")),
    });
    render(<OperationsView client={client} />);
    const resume = await screen.findByTestId("ops-resume-kraken-SUIUSD");
    fireEvent.click(resume);
    const refusal = await screen.findByTestId("ops-resume-result-kraken-SUIUSD");
    expect(refusal.textContent).toMatch(/Refused: no_active_entries/);

    fireEvent.click(resume);
    const alert = await screen.findByTestId("ops-resume-error-kraken-SUIUSD");
    expect(alert.getAttribute("role")).toBe("alert");
    expect(alert.textContent).toMatch(/unknown/i);
    expect(screen.queryByTestId("ops-resume-result-kraken-SUIUSD")).toBeNull();
  });

  it("keeps a server-confirmed refusal from the current attempt visible, with no transport error beside it", async () => {
    const client = makeClient({
      getOperations: vi.fn().mockResolvedValue(deploymentView()),
      pauseEntries: vi.fn().mockResolvedValue({
        schema_version: "1",
        code: "stored_mode_not_paper",
        ok: false,
        message: "stored mode is 'live'",
        effect: "refused",
      }),
    });
    render(<OperationsView client={client} />);
    const pause = await screen.findByTestId("ops-pause-kraken-SUIUSD");
    fireEvent.click(pause);
    const refusal = await screen.findByTestId("ops-pause-result-kraken-SUIUSD");
    expect(refusal.getAttribute("role")).toBe("status");
    expect(refusal.textContent).toMatch(/Refused: stored_mode_not_paper/);
    // A refusal is a server-confirmed answer, never presented as a transport error.
    expect(screen.queryByTestId("ops-pause-error-kraken-SUIUSD")).toBeNull();
    expect(client.pauseEntries).toHaveBeenCalledTimes(1);
  });

  it("sends at most one request while a pause or resume action is pending", async () => {
    const client = makeClient({
      getOperations: vi.fn().mockResolvedValue(deploymentView()),
      pauseEntries: vi.fn().mockImplementation(() => new Promise(() => undefined)),
      resumeEntries: vi.fn().mockImplementation(() => new Promise(() => undefined)),
    });
    render(<OperationsView client={client} />);
    const pause = await screen.findByTestId("ops-pause-kraken-SUIUSD");
    fireEvent.click(pause);
    fireEvent.click(pause);
    fireEvent.click(pause);
    expect(client.pauseEntries).toHaveBeenCalledTimes(1);

    const resume = screen.getByTestId("ops-resume-kraken-SUIUSD");
    fireEvent.click(resume);
    fireEvent.click(resume);
    expect(client.resumeEntries).toHaveBeenCalledTimes(1);

    await new Promise((resolve) => setTimeout(resolve, 25));
    expect(client.pauseEntries).toHaveBeenCalledTimes(1);
    expect(client.resumeEntries).toHaveBeenCalledTimes(1);
  });

  it("after a rejected pause only an explicit retry sends another request, and it clears the error", async () => {
    const client = makeClient({
      getOperations: vi.fn().mockResolvedValue(deploymentView()),
      pauseEntries: vi
        .fn()
        .mockRejectedValueOnce(new Error("paper.pause_entries failed: 503"))
        .mockResolvedValueOnce({
          schema_version: "1",
          code: "entries_paused",
          ok: true,
          message: "entries paused",
        }),
    });
    render(<OperationsView client={client} />);
    const pause = await screen.findByTestId("ops-pause-kraken-SUIUSD");
    fireEvent.click(pause);
    expect(await screen.findByTestId("ops-pause-error-kraken-SUIUSD")).toBeDefined();

    // No automatic retry, and the control stays usable for an explicit one.
    await new Promise((resolve) => setTimeout(resolve, 25));
    expect(client.pauseEntries).toHaveBeenCalledTimes(1);
    expect((pause as HTMLButtonElement).disabled).toBe(false);

    fireEvent.click(pause);
    await waitFor(() => {
      expect(client.pauseEntries).toHaveBeenCalledTimes(2);
    });
    await waitFor(() => {
      expect(screen.queryByTestId("ops-pause-error-kraken-SUIUSD")).toBeNull();
    });
    expect((client.pauseEntries as ReturnType<typeof vi.fn>).mock.calls).toEqual([
      ["kraken", "SUIUSD"],
      ["kraken", "SUIUSD"],
    ]);
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
<<<<<<< HEAD
});

describe("OperationsView periodic freshness", () => {
  const deploymentView = (paused: boolean): OperationsViewModel =>
    view({
      deployments: [
        {
          venue: "kraken",
          pair: "SUIUSD",
          pack_id: "trend-follow",
          pack_version: "1.0.0",
          mode: "paper",
          entries_paused: paused,
          promotion: { available: false, code: "live_disabled" },
        },
      ],
    });

  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  async function settle(ms = 0): Promise<void> {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ms);
    });
  }

  // With fake timers, RTL's findBy* polling never advances, so each test
  // flushes the mount read itself and then uses synchronous queries.
  async function rendered(): Promise<void> {
    await settle();
  }

  it("updates the deployments table from a later periodic read without any action", async () => {
    let calls = 0;
    const client = makeClient({
      getOperations: vi.fn().mockImplementation(async () => {
        calls += 1;
        return deploymentView(calls > 1);
      }),
    });
    render(<OperationsView client={client} />);
    await rendered();
    const row = screen.getByTestId("ops-deployment-kraken-SUIUSD");
    expect(row.textContent).toMatch(/active/i);

    await settle(OPERATIONS_REFRESH_INTERVAL_MS);
    expect(screen.getByTestId("ops-deployment-kraken-SUIUSD").textContent).toMatch(/paused/i);
    expect(client.pauseEntries).not.toHaveBeenCalled();
    expect(client.engageKill).not.toHaveBeenCalled();
    expect(client.ackAlert).not.toHaveBeenCalled();
  });

  it("shows the last successful read age with the truthful qualifier, never a heartbeat claim", async () => {
    const client = makeClient();
    render(<OperationsView client={client} />);
    await rendered();
    const age = screen.getByTestId("ops-last-read-age");
    expect(age.textContent).toContain("Last successful read from this dashboard server:");
    expect(age.textContent).toMatch(/ago/);
    expect(age.textContent).toContain(
      "local server read age only — not exchange-candle freshness and not proof the bot is trading",
    );
    expect(age.textContent ?? "").not.toMatch(/heartbeat|exchange (is )?(connected|healthy)/i);
  });

  it("ages the read upward while reads fail, retaining the last known rows", async () => {
    let calls = 0;
    const client = makeClient({
      getOperations: vi.fn().mockImplementation(async () => {
        calls += 1;
        if (calls > 1) {
          throw new Error("operations view failed: 503");
        }
        return deploymentView(false);
      }),
    });
    render(<OperationsView client={client} />);
    await rendered();
    expect(screen.getByTestId("ops-deployment-kraken-SUIUSD")).toBeDefined();
    const firstAge = screen.getByTestId("ops-last-read-age").textContent ?? "";

    await settle(OPERATIONS_REFRESH_INTERVAL_MS * 3);
    const stale = screen.getByTestId("ops-stale-warning");
    expect(stale.textContent).toContain("operations view failed: 503");
    // The retained row is still the last known state, not wiped or invented.
    expect(screen.getByTestId("ops-deployment-kraken-SUIUSD").textContent).toContain(
      "trend-follow",
    );
    const laterAge = screen.getByTestId("ops-last-read-age").textContent ?? "";
    expect(laterAge).not.toBe(firstAge);
    const parse = (text: string): number | null => {
      const m = text.match(/(\d+)s ago/);
      return m ? Number(m[1]) : null;
    };
    const first = parse(firstAge);
    const later = parse(laterAge);
    if (first !== null && later !== null) {
      expect(later).toBeGreaterThanOrEqual(first);
    }
  });

  it("recovers via the manual Refresh button without reloading and clears the stale warning", async () => {
    let calls = 0;
    const client = makeClient({
      getOperations: vi.fn().mockImplementation(async () => {
        calls += 1;
        if (calls === 2) {
          throw new Error("operations view failed: 503");
        }
        return deploymentView(calls > 2);
      }),
    });
    render(<OperationsView client={client} />);
    await rendered();
    await settle(OPERATIONS_REFRESH_INTERVAL_MS);
    expect(screen.getByTestId("ops-stale-warning")).toBeDefined();

    fireEvent.click(screen.getByTestId("ops-refresh"));
    await settle();
    expect(screen.queryByTestId("ops-stale-warning")).toBeNull();
    expect(screen.getByTestId("ops-deployment-kraken-SUIUSD").textContent).toMatch(/paused/i);
  });

  it("keeps protective controls usable while the view is stale", async () => {
    let calls = 0;
    const client = makeClient({
      getOperations: vi.fn().mockImplementation(async () => {
        calls += 1;
        if (calls > 1) {
          throw new Error("operations view failed: 503");
        }
        return deploymentView(false);
      }),
      pauseEntries: vi.fn().mockResolvedValue({
        schema_version: "1",
        code: "entries_paused",
        ok: true,
      }),
    });
    render(<OperationsView client={client} />);
    await rendered();
    await settle(OPERATIONS_REFRESH_INTERVAL_MS);
    expect(screen.getByTestId("ops-stale-warning")).toBeDefined();

    const pause = screen.getByTestId("ops-pause-kraken-SUIUSD");
    expect((pause as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(pause);
    await settle();
    expect(client.pauseEntries).toHaveBeenCalledWith("kraken", "SUIUSD");
    // The kill switch input stays editable too.
    const reason = screen.getByTestId("ops-kill-reason") as HTMLInputElement;
    expect(reason.disabled).toBe(false);
  });

  it("a hung read visibly stales and then recovers on a later read", async () => {
    let calls = 0;
    const client = makeClient({
      getOperations: vi.fn().mockImplementation(() => {
        calls += 1;
        if (calls === 1) {
          return Promise.resolve(deploymentView(false));
        }
        if (calls === 2) {
          return new Promise<OperationsViewModel>(() => undefined);
        }
        return Promise.resolve(deploymentView(true));
      }),
    });
    render(<OperationsView client={client} />);
    await rendered();
    expect(screen.getByTestId("ops-deployment-kraken-SUIUSD")).toBeDefined();

    await settle(OPERATIONS_REFRESH_INTERVAL_MS + OPERATIONS_READ_TIMEOUT_MS + 500);
    const stale = screen.getByTestId("ops-stale-warning");
    expect(stale.textContent).toMatch(/timed out after 4000ms/);
    // The last known rows are retained while the read hangs.
    expect(screen.getByTestId("ops-deployment-kraken-SUIUSD").textContent).toContain(
      "trend-follow",
    );

    await settle(OPERATIONS_REFRESH_INTERVAL_MS);
    expect(screen.queryByTestId("ops-stale-warning")).toBeNull();
    expect(screen.getByTestId("ops-deployment-kraken-SUIUSD").textContent).toMatch(/paused/i);
  });

  it("stops reading after unmount", async () => {
    const client = makeClient();
    const { unmount } = render(<OperationsView client={client} />);
    await rendered();
    unmount();
    const callsAfterUnmount = (client.getOperations as ReturnType<typeof vi.fn>).mock.calls.length;
    await settle(OPERATIONS_REFRESH_INTERVAL_MS * 3);
    expect((client.getOperations as ReturnType<typeof vi.fn>).mock.calls.length).toBe(
      callsAfterUnmount,
    );
  });
});
=======

  it("keeps every alert visible while the filter is untouched", async () => {
    const client = makeClient({
      getOperations: vi.fn().mockResolvedValue(
        view({
          alerts: [
            {
              id: "w1",
              kind: "live_refused",
              severity: "warning",
              code: "live_disabled",
              venue: "kraken",
              pair: "SUIUSD",
              count: 1,
              first_ts: 1700000000,
              last_ts: 1700000600,
              acknowledged: false,
            },
            {
              id: "c1",
              kind: "pack_stale",
              severity: "critical",
              code: "pack_stale",
              venue: "coinbase",
              pair: "SUIUSD",
              count: 1,
              first_ts: 1700000000,
              last_ts: 1700000600,
              acknowledged: false,
            },
          ],
        }),
      ),
    });
    render(<OperationsView client={client} />);
    await screen.findByTestId("ops-alert-w1");
    const alerts = screen.getByTestId("ops-alerts");
    expect(alerts.querySelectorAll('[data-testid^="ops-alert-"]:not([data-testid^="ops-alert-ack"])')).toHaveLength(2);
    expect(screen.queryByTestId("ops-alerts-filter-clear")).toBeNull();
  });
});

describe("OperationsView alerts filter mount", () => {
  it("when filter narrows list, renders only matching alerts (severity-only)", async () => {
    const client = makeClient({
      getOperations: vi.fn().mockResolvedValue(
        view({
          alerts: [
            {
              id: "w1",
              kind: "live_refused",
              severity: "warning",
              code: "live_disabled",
              venue: "kraken",
              pair: "SUIUSD",
              count: 1,
              first_ts: 1700000000,
              last_ts: 1700000600,
              acknowledged: false,
            },
            {
              id: "c1",
              kind: "pack_stale",
              severity: "critical",
              code: "pack_stale",
              venue: "coinbase",
              pair: "SUIUSD",
              count: 1,
              first_ts: 1700000000,
              last_ts: 1700000600,
              acknowledged: false,
            },
            {
              id: "w2",
              kind: "entries_paused",
              severity: "warning",
              code: "entries_paused",
              venue: "kraken",
              pair: "SUIUSD",
              count: 3,
              first_ts: 1700000000,
              last_ts: 1700000600,
              acknowledged: false,
            },
          ],
        }),
      ),
    });
    render(<OperationsView client={client} />);
    await screen.findByTestId("ops-alert-w1");
    fireEvent.change(screen.getByTestId("ops-alerts-filter-severity"), {
      target: { value: "warning" },
    });
    const alerts = screen.getByTestId("ops-alerts");
    const rows = alerts.querySelectorAll('[data-testid^="ops-alert-"]:not([data-testid^="ops-alert-ack"])');
    expect(Array.from(rows).map((r) => r.getAttribute("data-testid"))).toEqual([
      "ops-alert-w1",
      "ops-alert-w2",
    ]);
    expect(screen.queryByTestId("ops-alert-c1")).toBeNull();
    expect(screen.queryByTestId("ops-alerts-empty")).toBeNull();
  });

  it("when filter narrows list to nothing, shows the empty row instead of alert rows", async () => {
    const client = makeClient({
      getOperations: vi.fn().mockResolvedValue(
        view({
          alerts: [
            {
              id: "w1",
              kind: "live_refused",
              severity: "warning",
              code: "live_disabled",
              venue: "kraken",
              pair: "SUIUSD",
              count: 1,
              first_ts: 1700000000,
              last_ts: 1700000600,
              acknowledged: false,
            },
          ],
        }),
      ),
    });
    render(<OperationsView client={client} />);
    await screen.findByTestId("ops-alert-w1");
    fireEvent.change(screen.getByTestId("ops-alerts-filter-query"), {
      target: { value: "no-such-code" },
    });
    expect(screen.queryByTestId("ops-alert-w1")).toBeNull();
    expect(screen.getByTestId("ops-alerts-empty")).toBeTruthy();
        fireEvent.click(screen.getByTestId("ops-alerts-filter-clear"));
    await screen.findByTestId("ops-alert-w1");
    expect(screen.queryByTestId("ops-alerts-empty")).toBeNull();
  });
});
>>>>>>> 45f5aeb (feat(operations): add AlertsFilter to narrow visible alerts)
