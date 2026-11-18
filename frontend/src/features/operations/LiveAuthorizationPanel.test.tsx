import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LiveAuthorizationPanel } from "./LiveAuthorizationPanel";
import type { LiveAuthorizationView, OperationsClient } from "./client";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const PAPER_ONLY_VIEW: LiveAuthorizationView = {
  schema_version: "1",
  authorization: { active: false, expires_at: null, grants: [] },
  release_policy: "paper_only",
  release_policy_code: "live_disabled_paper_only_release",
  release_policy_message:
    "v0.9.7 is a paper-only release: live order send is disabled regardless of environment, stored keys, or authorization.",
  confirmation_required: "LIVE",
};

function makeClient(over: Partial<OperationsClient> = {}): OperationsClient {
  return {
    getOperations: vi.fn(),
    promote: vi.fn(),
    pauseEntries: vi.fn(),
    resumeEntries: vi.fn(),
    engageKill: vi.fn(),
    releaseKill: vi.fn(),
    ackAlert: vi.fn(),
    getLiveAuthorization: vi.fn().mockResolvedValue(PAPER_ONLY_VIEW),
    grantLiveAuthorization: vi.fn(),
    revokeLiveAuthorization: vi.fn(),
    ...over,
  };
}

describe("LiveAuthorizationPanel paper-only state", () => {
  it("shows the panel disabled with the paper-only reason", async () => {
    const client = makeClient();
    render(<LiveAuthorizationPanel client={client} />);

    const panel = await screen.findByTestId("ops-live-authorization");
    expect(panel).toBeTruthy();

    const reason = await screen.findByTestId("ops-live-auth-paper-only");
    expect(reason.textContent).toMatch(/paper-only release/i);
    expect(screen.getByTestId("ops-live-auth-paper-only-reason").textContent).toMatch(
      /live order send is disabled/i,
    );

    const venueSelect = screen.getByTestId("ops-live-auth-venue") as HTMLSelectElement;
    expect(venueSelect.disabled).toBe(true);
    expect(venueSelect.tagName).toBe("SELECT");
    expect(venueSelect.value).toBe("kraken");
    expect(Array.from(venueSelect.options).map((option) => option.value)).toEqual([
      "kraken",
      "coinbase",
    ]);
    const pairSelect = screen.getByTestId("ops-live-auth-pair") as HTMLSelectElement;
    expect(pairSelect.disabled).toBe(true);
    expect(pairSelect.tagName).toBe("SELECT");
    expect(pairSelect.value).toBe("XXBTZUSD");
    expect(Array.from(pairSelect.options).map((option) => option.value)).toEqual([
      "XXBTZUSD",
    ]);
    expect((screen.getByTestId("ops-live-auth-hours") as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByTestId("ops-live-auth-confirm") as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByTestId("ops-live-auth-grant") as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByTestId("ops-live-auth-revoke") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/For Kraken BTC\/USD grant XXBTZUSD/i)).toBeDefined();
    expect(screen.getByText(/For Coinbase BTC\/USD grant BTC-USD/i)).toBeDefined();
    expect(screen.getByText(/Binance is paper-only/i)).toBeDefined();

    await waitFor(() => {
      expect(client.getLiveAuthorization).toHaveBeenCalled();
    });
  });
});
