/**
 * Beginner copy / vocabulary honesty on the paper StatusPanel (M24.5).
 * Pins Start/Stop paper run paired labels and pause parenthetical.
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { StatusPanel } from "./StatusPanel";
import type { PaperClient, PaperStatus } from "./client";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function armedStatus(overrides: Partial<PaperStatus> = {}): PaperStatus {
  return {
    schema_version: "1",
    armed: true,
    venue: "kraken",
    pair: "SUIUSD",
    entries_paused: false,
    mode: "paper",
    pack_id: "trend-follow",
    ...overrides,
  };
}

function makeClient(
  overrides: Partial<PaperClient> = {},
): PaperClient {
  return {
    getStatus: vi.fn().mockResolvedValue({
      schema_version: "1",
      armed: false,
    }),
    getPosition: vi.fn().mockResolvedValue(null),
    listOwnedDrafts: vi.fn().mockResolvedValue([]),
    arm: vi.fn(),
    pauseEntries: vi.fn(),
    resumeEntries: vi.fn(),
    disarm: vi.fn(),
    raiseStop: vi.fn(),
    ...overrides,
  } as PaperClient;
}

describe("StatusPanel beginner copy honesty", () => {
  it("offers Start paper run when unarmed with a runnable revision", async () => {
    const client = makeClient({
      listOwnedDrafts: vi.fn().mockResolvedValue([
        {
          revision_id: "rev-1",
          label: "starter",
          pair: "SUIUSD",
          runnable: true,
        },
      ]),
    });
    render(<StatusPanel client={client} />);
    expect(
      await screen.findByRole("button", { name: /^start paper run$/i }),
    ).toBeDefined();
    expect(screen.getByText("Start your paper run")).toBeDefined();
  });

  it("pairs Start/Stop paper run and pause parenthetical when armed", async () => {
    render(
      <StatusPanel
        client={makeClient({
          getStatus: vi.fn().mockResolvedValue(armedStatus()),
        })}
      />,
    );
    await waitFor(() => {
      expect(
        screen.getByRole("button", {
          name: /pause new buys \(doesn't sell\)/i,
        }),
      ).toBeDefined();
    });
    expect(
      screen.getByRole("button", { name: /^stop paper run$/i }),
    ).toBeDefined();
    expect(
      screen.getByRole("button", { name: /^resume new buys$/i }),
    ).toBeDefined();
  });
});
