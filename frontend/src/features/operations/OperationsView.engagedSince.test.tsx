import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OperationsView } from "./OperationsView";
import type { OperationsClient, OperationsViewModel } from "./client";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

// Client doubles supply timestamp boundaries to the real mounted component;
// the runtime verifier separately exercises the production client and backend.
function setup(kill_switch: OperationsViewModel["live"]["kill_switch"]) {
  const view: OperationsViewModel = {
    schema_version: "1", deployments: [], alerts: [],
    live: { schema_version: "1", live_enabled: false, authorized: [], kill_switch,
      promotion_available: false, promotion_code: "live_disabled" },
  };
  const client: OperationsClient = {
    getOperations: vi.fn().mockResolvedValue(view),
    engageKill: vi.fn(), releaseKill: vi.fn(), promote: vi.fn(),
    pauseEntries: vi.fn(), resumeEntries: vi.fn(), ackAlert: vi.fn(),
  };
  render(<OperationsView client={client} />);
  return client;
}

const legacyEngagedPanel = "Kill switchKill switch: engaged — (no reason)ReasonEngage kill switchRelease kill switchEngaging stops new entries and all live sends. It does not sell or disarm.";

describe("kill switch engaged age", () => {
  it("adds a seconds-epoch age directly after the unchanged state paragraph", async () => {
    setup({ engaged: true, reason: "operator-test", engaged_at: Math.floor(Date.now() / 1000) - 5 });
    const since = await screen.findByTestId("ops-kill-engaged-since");
    expect(since.tagName).toBe("P");
    expect(since.className).toBe("kbot-ops__kill-since");
    expect(since.textContent).toMatch(/^Engaged for: [56]s ago$/);
    const state = screen.getByTestId("ops-kill-state");
    expect(state.textContent).toBe("Kill switch: engaged — operator-test");
    expect(state.className).toBe("kbot-ops__kill-state");
    expect(state.nextElementSibling).toBe(since);
    expect(since.closest("[data-testid='ops-kill']")).toBe(screen.getByTestId("ops-kill"));
  });

  it("preserves the entire legacy panel text when the timestamp is null", async () => {
    setup({ engaged: true, reason: null, engaged_at: null });
    await screen.findByTestId("ops-kill-state");
    expect(screen.queryByTestId("ops-kill-engaged-since")).toBeNull();
    expect(screen.getByTestId("ops-kill").textContent).toBe(legacyEngagedPanel);
  });

  it.each([null, 1700000000])("keeps released state byte-equal with timestamp %s", async engaged_at => {
    setup({ engaged: false, reason: null, engaged_at });
    expect((await screen.findByTestId("ops-kill-state")).textContent).toBe("Kill switch: released");
    expect(screen.queryByTestId("ops-kill-engaged-since")).toBeNull();
  });

  it.each([
    [-5, "0s ago"], [0, "0s ago"], [59, "59s ago"], [60, "1m 0s ago"],
    [90, "1m 30s ago"], [3599, "59m 59s ago"], [3600, "1h 0m ago"],
    [86399, "23h 59m ago"], [86400, "1d 0h ago"], [176400, "2d 1h ago"],
    [1700000100, "19675d 22h ago"],
  ])("humanizes %s seconds as %s", async (delta, expected) => {
    vi.spyOn(Date, "now").mockReturnValue(1700000100 * 1000);
    setup({ engaged: true, reason: "operator-test", engaged_at: 1700000100 - delta });
    expect((await screen.findByTestId("ops-kill-engaged-since")).textContent).toBe(`Engaged for: ${expected}`);
  });

  it("removes the age when a fresh operations read reports released", async () => {
    const client = setup({ engaged: true, reason: "operator-test", engaged_at: 1700000000 });
    await screen.findByTestId("ops-kill-engaged-since");
    const released: OperationsViewModel = {
      schema_version: "1", deployments: [], alerts: [],
      live: { schema_version: "1", live_enabled: false, authorized: [],
        kill_switch: { engaged: false, reason: null, engaged_at: null },
        promotion_available: false, promotion_code: "live_disabled" },
    };
    vi.mocked(client.getOperations).mockResolvedValue(released);
    fireEvent.click(screen.getByTestId("ops-refresh"));
    await screen.findByText("Kill switch: released");
    expect(screen.queryByTestId("ops-kill-engaged-since")).toBeNull();
  });
});
