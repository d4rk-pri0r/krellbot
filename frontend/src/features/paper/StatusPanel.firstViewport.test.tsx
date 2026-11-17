/**
 * Paper workstation first-viewport density — KRELL-SIGNAL-20261010 /
 * docs/ui-density.md (M18.3).
 *
 * Pins empty vs fixture-seeded states at the 1440×900 operator summary:
 * status + next action + chart or honest empty, never fabricated series
 * when no journal exists.
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PaperChart, PaperClient, PaperCommandResult, PaperStatus } from "./client";
import { StatusPanel } from "./StatusPanel";

const here = dirname(fileURLToPath(import.meta.url));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

function armedStatus(extra: Partial<PaperStatus> = {}): PaperStatus {
  return {
    schema_version: "1",
    armed: true,
    venue: "kraken",
    pair: "SUIUSD",
    entries_paused: false,
    mode: "paper",
    pack_id: "trend-follow",
    ...extra,
  };
}

function fixtureChart(overrides: Partial<PaperChart> = {}): PaperChart {
  return {
    schema_version: "1",
    armed: true,
    venue: "kraken",
    pair: "SUIUSD",
    mode: "paper",
    pack_id: "trend-follow",
    starting_cash: "1000",
    pnl: [
      { ts_ms: 1000, value: "0" },
      { ts_ms: 2000, value: "1.5" },
    ],
    position: [
      { ts_ms: 1000, qty: "0" },
      { ts_ms: 2000, qty: "2" },
    ],
    marks: [{ ts_ms: 2000, price: "10" }],
    ...overrides,
  };
}

function makeClient(overrides: Partial<PaperClient> = {}): PaperClient {
  return {
    getStatus: vi.fn().mockResolvedValue({
      schema_version: "1",
      armed: false,
    } satisfies PaperStatus),
    pauseEntries: vi.fn().mockResolvedValue({
      schema_version: "1",
      code: "entries_paused",
      ok: true,
      message: "ok",
      effect: "changed",
      revision_before: "a",
      revision_after: "b",
    } satisfies PaperCommandResult),
    resumeEntries: vi.fn().mockResolvedValue({
      schema_version: "1",
      code: "entries_resumed",
      ok: true,
      message: "ok",
      effect: "changed",
      revision_before: "a",
      revision_after: "b",
    } satisfies PaperCommandResult),
    disarm: vi.fn().mockResolvedValue({
      schema_version: "1",
      code: "disarmed",
      ok: true,
      message: "ok",
      effect: "changed",
      revision_before: "a",
      revision_after: "b",
    } satisfies PaperCommandResult),
    ...overrides,
  };
}

function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "");
}

describe("workstation first-viewport empty vs fixture-seeded", () => {
  it("empty unarmed state shows status, next action, and honest empty chart", async () => {
    render(<StatusPanel client={makeClient()} />);
    await screen.findByTestId("paper-status-empty");

    const first = screen.getByTestId("paper-workstation-first-viewport");
    expect(first.contains(screen.getByTestId("paper-status-empty"))).toBe(true);
    expect(screen.getByTestId("paper-status-next-action").textContent).toMatch(
      /Next: arm a paper pack/i,
    );
    const honest = screen.getByTestId("paper-chart-honest-empty");
    expect(first.contains(honest)).toBe(true);
    expect(honest.textContent).toMatch(/No journal series yet/i);
    expect(honest.textContent).toMatch(/never fabricated/i);
    expect(screen.queryByTestId("paper-pnl-chart-svg")).toBeNull();
    expect(screen.queryByTestId("paper-pnl-position-chart")).toBeNull();
  });

  it("fixture-seeded armed state shows status, next action, and real chart series", async () => {
    const client = makeClient({
      getStatus: vi.fn().mockResolvedValue(armedStatus()),
      getChart: vi.fn().mockResolvedValue(fixtureChart()),
      getPosition: vi.fn().mockResolvedValue({
        schema_version: "1",
        armed: true,
        venue: "kraken",
        pair: "SUIUSD",
        mode: "paper",
        owned_base_qty: "2",
        free_quote: "980",
      }),
    });
    render(<StatusPanel client={client} />);

    await screen.findByTestId("paper-status-entries");
    expect(screen.getByTestId("paper-status-next-action").textContent).toMatch(
      /Next: pause entries, resume, or disarm/i,
    );
    expect(screen.queryByTestId("paper-chart-honest-empty")).toBeNull();
    await screen.findByTestId("paper-pnl-chart-svg");
    const first = screen.getByTestId("paper-workstation-first-viewport");
    expect(first.contains(screen.getByTestId("paper-pnl-position-chart"))).toBe(
      true,
    );
    expect(screen.getByRole("button", { name: /pause entries/i })).toBeTruthy();
  });

  it("armed empty journal stays unavailable — never fabricates a flat series", async () => {
    const client = makeClient({
      getStatus: vi.fn().mockResolvedValue(armedStatus()),
      getChart: vi.fn().mockResolvedValue(
        fixtureChart({ pnl: [], position: [], marks: [] }),
      ),
      getPosition: vi.fn().mockResolvedValue({
        schema_version: "1",
        armed: true,
        venue: "kraken",
        pair: "SUIUSD",
        mode: "paper",
        owned_base_qty: "0",
        free_quote: "1000",
      }),
    });
    render(<StatusPanel client={client} />);
    await screen.findByTestId("paper-pnl-chart-unavailable");
    expect(screen.getByTestId("paper-pnl-chart-unavailable").textContent).toBe(
      "unavailable",
    );
    expect(screen.queryByTestId("paper-pnl-chart-svg")).toBeNull();
  });

  it("ships dense first-viewport CSS for the operator summary", () => {
    const css = stripComments(
      readFileSync(join(here, "StatusPanel.signal.css"), "utf8"),
    );
    expect(css).toMatch(
      /\.kbot-paper-status__first-viewport\s*\{[^}]*display:\s*grid/,
    );
    expect(css).toMatch(
      /\.kbot-paper-status__next\s*\{[^}]*color:\s*var\(--seafoam\)/,
    );
    expect(css).toMatch(/\.kbot-paper-chart--honest-empty/);
  });

  it("keeps Advanced armed-records collapsed by default in the shell stylesheet contract", async () => {
    // Structural pin: StatusPanel empty path is ready before shell mounts.
    render(<StatusPanel client={makeClient()} />);
    await waitFor(() => {
      expect(screen.getByTestId("paper-workstation-first-viewport")).toBeTruthy();
    });
    const shell = readFileSync(
      join(here, "../../shell/WorkstationShell.tsx"),
      "utf8",
    );
    expect(shell).toMatch(
      /data-testid="paper-armed-records-disclosure"[\s\S]*?defaultOpen=\{false\}|defaultOpen=\{false\}[\s\S]*?data-testid="paper-armed-records-disclosure"/,
    );
  });
});
