/**
 * M23.4: Ops live authorization admits coinbase as the second qualified live venue.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LiveAuthorizationPanel } from "./LiveAuthorizationPanel";
import type { LiveAuthorizationView, OperationsClient } from "./client";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const READY_VIEW: LiveAuthorizationView = {
  schema_version: "1",
  authorization: { active: false, expires_at: null, grants: [] },
  release_policy: "live_capable",
  release_policy_code: "ok",
  release_policy_message: null,
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
    getLiveAuthorization: vi.fn().mockResolvedValue(READY_VIEW),
    grantLiveAuthorization: vi.fn(),
    revokeLiveAuthorization: vi.fn(),
    ...over,
  };
}

describe("LiveAuthorizationPanel second venue", () => {
  it("switches pair options to Coinbase BTC-USD when venue is coinbase", async () => {
    render(<LiveAuthorizationPanel client={makeClient()} />);

    const venueSelect = (await screen.findByTestId("ops-live-auth-venue")) as HTMLSelectElement;
    expect(Array.from(venueSelect.options).map((option) => option.value)).toEqual([
      "kraken",
      "coinbase",
    ]);
    expect(venueSelect.value).toBe("kraken");

    fireEvent.change(venueSelect, { target: { value: "coinbase" } });

    await waitFor(() => {
      expect(venueSelect.value).toBe("coinbase");
    });
    const pairSelect = screen.getByTestId("ops-live-auth-pair") as HTMLSelectElement;
    expect(pairSelect.value).toBe("BTC-USD");
    expect(Array.from(pairSelect.options).map((option) => option.value)).toEqual(["BTC-USD"]);
  });
});
