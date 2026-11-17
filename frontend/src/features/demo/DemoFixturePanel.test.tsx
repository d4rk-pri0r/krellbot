/**
 * Demo fixture seed panel honesty — M18.5 / docs/ui-density.md.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DemoFixturePanel } from "./DemoFixturePanel";
import type { DemoFixtureClient, DemoFixtureStatus } from "./demoFixtureClient";
import { adaptDemoFixtureStatus } from "./demoFixtureClient";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function emptyStatus(): DemoFixtureStatus {
  return {
    schema_version: "1",
    enabled: false,
    label: null,
    badge: null,
    honesty_note:
      "Opt-in local preview seed only. Labeled fixture/demo/rehearsal — never live P&L, market performance, or soak PASS.",
    is_fixture: false,
    live_performance: false,
    soak_proof: false,
    deployments: [],
    message: "Demo fixture seed is off. Fresh home stays empty and honest.",
  };
}

function seededStatus(): DemoFixtureStatus {
  return {
    schema_version: "1",
    enabled: true,
    label: "Fixture / demo rehearsal — not live performance",
    badge: "Fixture demo",
    honesty_note: emptyStatus().honesty_note,
    is_fixture: true,
    live_performance: false,
    soak_proof: false,
    deployments: [
      {
        id: "fixture-demo-paper-1",
        label: "Demo paper deployment (fixture)",
        venue: "kraken",
        pair: "SUIUSD",
        mode: "paper",
        pack_id: "fixture-demo-sma",
        status: "rehearsal_idle",
        is_fixture: true,
        live_performance: false,
        soak_proof: false,
      },
    ],
    message: "Demo fixture seed enabled — labeled fixture/demo only.",
  };
}

function makeClient(
  overrides: Partial<DemoFixtureClient> = {},
): DemoFixtureClient {
  return {
    getStatus: vi.fn().mockResolvedValue(emptyStatus()),
    seed: vi.fn().mockResolvedValue(seededStatus()),
    clear: vi.fn().mockResolvedValue(emptyStatus()),
    ...overrides,
  };
}

describe("DemoFixturePanel honesty", () => {
  it("defaults empty/honest and seeds only with a labeled fixture badge", async () => {
    const client = makeClient();
    render(<DemoFixturePanel client={client} />);
    await screen.findByTestId("demo-fixture-message");
    expect(screen.getByTestId("demo-fixture-honesty").textContent).toMatch(
      /never live P&L/i,
    );
    expect(screen.queryByTestId("demo-fixture-badge")).toBeNull();
    fireEvent.click(screen.getByTestId("demo-fixture-seed"));
    await waitFor(() => {
      expect(client.seed).toHaveBeenCalledWith(true);
    });
    await screen.findByTestId("demo-fixture-badge");
    expect(screen.getByTestId("demo-fixture-badge").textContent).toMatch(
      /Fixture demo/i,
    );
    expect(screen.getByTestId("demo-fixture-label").textContent).toMatch(
      /not live performance/i,
    );
    expect(
      screen.getByTestId("demo-fixture-row-fixture-demo-paper-1").textContent,
    ).toMatch(/fixture/i);
    // Badge/label refuse live or soak proof framing.
    expect(screen.getByTestId("demo-fixture-badge").textContent).not.toMatch(
      /soak|live p&l|market performance/i,
    );
    expect(screen.getByTestId("demo-fixture-label").textContent).toMatch(
      /not live/i,
    );
  });

  it("clears back to empty honest default", async () => {
    const client = makeClient({
      getStatus: vi.fn().mockResolvedValue(seededStatus()),
    });
    render(<DemoFixturePanel client={client} />);
    await screen.findByTestId("demo-fixture-badge");
    fireEvent.click(screen.getByTestId("demo-fixture-clear"));
    await waitFor(() => {
      expect(client.clear).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(screen.queryByTestId("demo-fixture-badge")).toBeNull();
    });
  });

  it("adaptDemoFixtureStatus strips live/soak claims from wire payloads", () => {
    const adapted = adaptDemoFixtureStatus({
      schema_version: "1",
      enabled: true,
      label: "x",
      badge: "Fixture demo",
      honesty_note: "n",
      is_fixture: true,
      live_performance: true,
      soak_proof: true,
      deployments: [
        {
          id: "a",
          label: "row",
          venue: "kraken",
          pair: "SUIUSD",
          mode: "paper",
          pack_id: "p",
          status: "idle",
          is_fixture: false,
          live_performance: true,
          soak_proof: true,
        },
      ],
      message: "m",
    });
    expect(adapted.live_performance).toBe(false);
    expect(adapted.soak_proof).toBe(false);
    expect(adapted.deployments[0]?.live_performance).toBe(false);
    expect(adapted.deployments[0]?.soak_proof).toBe(false);
    expect(adapted.deployments[0]?.is_fixture).toBe(true);
  });
});
