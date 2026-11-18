import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { AlertRow, OperationsClient } from "../features/operations/client";
import type {
  PaperArmedClient,
  PaperArmedRecord,
  PaperClient,
  PaperPosition,
  PaperStatus,
} from "../features/paper/client";
import { WorkstationShell } from "./WorkstationShell";
import { clickShellNav } from "./navTestUtils";

vi.mock("../session", () => ({
  redeemBootstrap: vi.fn(async () => undefined),
  recoverCsrf: vi.fn(async () => true),
}));

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

beforeAll(() => {
  if (typeof globalThis.ResizeObserver !== "function") {
    globalThis.ResizeObserver =
      ResizeObserverStub as unknown as typeof ResizeObserver;
  }
});

afterEach(() => {
  cleanup();
  document.head.innerHTML = "";
  vi.clearAllMocks();
});

const ARMED: PaperArmedRecord = {
  venue: "kraken",
  pair: "BTC/USD",
  mode: "paper",
  pack_id: "pack.sma",
  entries_paused: false,
};

const POSITION: PaperPosition = {
  schema_version: "1",
  armed: true,
  venue: "kraken",
  pair: "BTC/USD",
  mode: "paper",
  free_cash: "1000",
  holdings: [{ symbol: "BTC", qty: "0.02" }],
};

const STATUS: PaperStatus = {
  schema_version: "1",
  armed: true,
  venue: "kraken",
  pair: "BTC/USD",
  mode: "paper",
  pack_id: "pack.sma",
  entries_paused: false,
};

const ALERT: AlertRow = {
  id: "a-1",
  kind: "rate_limited",
  severity: "warning",
  code: "rl",
  venue: "kraken",
  pair: "BTC/USD",
  count: 1,
  first_ts: 1,
  last_ts: 2,
  acknowledged: false,
};

function paperClient(): PaperClient & PaperArmedClient {
  return {
    getStatus: vi.fn(async () => STATUS),
    getPosition: vi.fn(async () => POSITION),
    listArmed: vi.fn(async () => ({
      schema_version: "1",
      armed: true,
      records: [ARMED],
    })),
    pauseEntries: vi.fn(async () => ({
      schema_version: "1",
      code: "ok",
      ok: true,
    })),
    resumeEntries: vi.fn(async () => ({
      schema_version: "1",
      code: "ok",
      ok: true,
    })),
    disarm: vi.fn(async () => ({
      schema_version: "1",
      code: "ok",
      ok: true,
    })),
    listRuns: vi.fn(async () => ({ schema_version: "1", runs: [] })),
  } as PaperClient & PaperArmedClient;
}

function operationsClient(): OperationsClient {
  return {
    getOperations: vi.fn(async () => ({
      schema_version: "1",
      live: {
        schema_version: "1",
        live_enabled: false,
        authorized: [],
        kill_switch: { engaged: false, reason: null, engaged_at: null },
        promotion_available: false,
        promotion_code: "paper_only",
      },
      deployments: [],
      alerts: [ALERT],
    })),
    promote: vi.fn(),
    pauseEntries: vi.fn(),
    resumeEntries: vi.fn(),
    engageKill: vi.fn(),
    releaseKill: vi.fn(),
    ackAlert: vi.fn(),
  } as unknown as OperationsClient;
}

async function openWorkstation(): Promise<void> {
  render(
    <WorkstationShell
      paperClient={paperClient()}
      operationsClient={operationsClient()}
    />,
  );
  await act(async () => {
    await Promise.resolve();
  });
  clickShellNav("Run");
  await waitFor(() => {
    expect(screen.getByTestId("paper-status-panel")).toBeDefined();
  });
}

describe("WorkstationShell inspector selection wiring (M7.4)", () => {
  it("starts with the honest empty inspector on Workstation", async () => {
    await openWorkstation();
    expect(screen.getByTestId("inspector-empty").textContent).toMatch(
      /Nothing selected/,
    );
  });

  it("shows deployment context in the inspector when an armed row is selected", async () => {
    await openWorkstation();
    const row = await screen.findByTestId("paper-armed-row");
    fireEvent.click(row);
    const selected = await screen.findByTestId("inspector-selection");
    expect(selected.getAttribute("data-kind")).toBe("deployment");
    expect(selected.textContent).toContain("kraken:BTC/USD");
    expect(selected.textContent).toContain("pack.sma · paper");
    expect(screen.queryByTestId("inspector-empty")).toBeNull();
  });

  it("shows position context when the owned position control is pressed", async () => {
    await openWorkstation();
    const position = await screen.findByTestId("paper-position");
    fireEvent.click(position);
    const selected = await screen.findByTestId("inspector-selection");
    expect(selected.getAttribute("data-kind")).toBe("position");
    expect(selected.textContent).toContain("0.02 BTC");
    expect(screen.queryByTestId("inspector-empty")).toBeNull();
  });

  it("shows alert context when a workstation alert row is selected", async () => {
    await openWorkstation();
    const alertRow = await screen.findByTestId("workstation-alert-row");
    fireEvent.click(alertRow);
    const selected = await screen.findByTestId("inspector-selection");
    expect(selected.getAttribute("data-kind")).toBe("alert");
    expect(selected.textContent).toContain("a-1");
    expect(selected.textContent).toContain("Rate limited");
    expect(screen.queryByTestId("inspector-empty")).toBeNull();
  });
});
