/**
 * M25.6 — first-session Run empty is a single arm prompt, not a cockpit dump.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PaperClient } from "./client";
import type { RehearsalClient, RehearsalStatus } from "./rehearsalClient";
import { StatusPanel } from "./StatusPanel";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  vi.restoreAllMocks();
});

function makeClient(over: Partial<PaperClient> = {}): PaperClient {
  return {
    getStatus: vi.fn().mockResolvedValue({
      schema_version: "1",
      armed: false,
      pack_id: null,
      venue: null,
      pair: null,
      entries_paused: false,
    }),
    pauseEntries: vi.fn(),
    resumeEntries: vi.fn(),
    disarm: vi.fn(),
    raiseStop: vi.fn(),
    arm: vi.fn(),
    listOwnedDrafts: vi.fn().mockResolvedValue([
      {
        revision_id: "rev-starter-1",
        label: "Dual moving average",
        pair: "XBT/USD",
        runnable: true,
      },
    ]),
    getPosition: vi.fn(),
    createRehearsalClient: () =>
      ({
        getStatus: vi.fn().mockResolvedValue({
          schema_version: "1",
          label: "SYNTHETIC PAPER REHEARSAL — simulated fixture, not market data",
          status: "idle",
          cursor: 0,
          total_bars: 20,
          balances: { USD: "1000" },
          position: "0",
          resting_stop: null,
          recent_fills: [],
        } satisfies RehearsalStatus),
        start: vi.fn(),
        pause: vi.fn(),
        resume: vi.fn(),
        exit: vi.fn(),
        stop: vi.fn(),
      }) as RehearsalClient,
    ...over,
  } as PaperClient;
}

describe("StatusPanel — first-session empty is a single arm prompt", () => {
  it("prompts to start a paper run instead of dumping No pack armed", async () => {
    render(
      <StatusPanel client={makeClient()} preferredRevisionId="rev-starter-1" />,
    );
    const prompt = await screen.findByTestId("paper-status-empty");
    expect(prompt.textContent).toMatch(
      /Start a paper run with the strategy you picked/i,
    );
    expect(prompt.textContent).not.toMatch(/No pack armed/i);
    expect(screen.getByTestId("paper-first-session-arm")).toBeTruthy();
    expect(screen.getByTestId("paper-arm-form").textContent).toMatch(
      /Start your paper run/i,
    );
    expect(screen.getByTestId("paper-status-next-action").textContent).toMatch(
      /start your paper run/i,
    );
  });

  it("keeps the honest empty chart behind Advanced until armed", async () => {
    render(<StatusPanel client={makeClient()} />);
    await screen.findByTestId("paper-first-session-arm");
    expect(screen.getByTestId("paper-first-session-chart-disclosure")).toBeTruthy();
    expect(screen.queryByTestId("paper-chart-honest-empty")).toBeTruthy();
    expect(
      screen.getByTestId("paper-first-session-chart-disclosure").getAttribute("data-open"),
    ).toBe("0");
  });

  it("demotes rehearsal behind Advanced while unarmed and still mounts it", async () => {
    render(<StatusPanel client={makeClient()} />);
    await screen.findByTestId("paper-rehearsal-disclosure");
    expect(
      screen.getByTestId("paper-rehearsal-disclosure").getAttribute("data-open"),
    ).toBe("0");
    expect(screen.getByTestId("rehearsal-panel")).toBeTruthy();
    // Collapsed Advanced: rehearsal controls are not exposed as primary.
    expect(
      screen.queryByRole("button", { name: /start rehearsal/i }),
    ).toBeNull();
  });

  it("keeps rehearsal collapsed behind Advanced even when a pack is armed, opening only on explicit toggle", async () => {
    const client = makeClient({
      getStatus: vi.fn().mockResolvedValue({
        schema_version: "1",
        armed: true,
        pack_id: "trend-follow",
        venue: "kraken",
        pair: "SUIUSD",
        entries_paused: false,
        mode: "paper",
      }),
      getPosition: vi.fn().mockResolvedValue({
        venue: "kraken",
        pair: "SUIUSD",
        free_cash: "1000",
        holdings: [],
      }),
    });
    render(<StatusPanel client={client} />);
    await screen.findByRole("button", { name: /pause new buys/i });
    const disclosure = screen.getByTestId("paper-rehearsal-disclosure");
    expect(disclosure.getAttribute("data-open")).toBe("0");
    expect(
      within(screen.getByTestId("paper-rehearsal-disclosure-toggle")).getByText(
        "Advanced",
      ),
    ).toBeTruthy();
    expect(screen.getAllByTestId("rehearsal-panel").length).toBe(1);

    fireEvent.click(screen.getByTestId("paper-rehearsal-disclosure-toggle"));
    await waitFor(() => {
      expect(disclosure.getAttribute("data-open")).toBe("1");
    });
    const panel = screen.getByTestId("rehearsal-panel");
    expect(
      within(panel).getByRole("button", { name: /start rehearsal/i }),
    ).toBeTruthy();
  });
});
