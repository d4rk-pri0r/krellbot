/**
 * Kraken keys onboarding panel — Workspace form (KRELL-SIGNAL-20261010).
 *
 * Happy path and honest keyring errors use injectable fake clients only.
 * No real credentials, keyring, or exchange network.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { KeysOnboardingPanel } from "./KeysOnboardingPanel";
import type { KeysClient, KeysMutationResult, KeysStatus } from "./client";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const ABSENT: KeysStatus = {
  schema_version: "1",
  venue: "kraken",
  present: false,
  corrupt: false,
  message: "no key stored",
  backend_label: null,
  balances: null,
  balances_available: false,
};

const PRESENT: KeysStatus = {
  schema_version: "1",
  venue: "kraken",
  present: true,
  corrupt: false,
  message: "key present",
  backend_label: "FakeKeyring",
  balances: [
    { asset: "ZUSD", free: "100.5" },
    { asset: "XXBT", free: "0.01" },
  ],
  balances_available: true,
};

const STORED: KeysMutationResult = {
  schema_version: "1",
  venue: "kraken",
  status: "stored",
  ok: true,
  message: "stored in native OS keychain",
  effect: "changed",
  backend_label: "FakeKeyring",
};

const REMOVED: KeysMutationResult = {
  schema_version: "1",
  venue: "kraken",
  status: "removed",
  ok: true,
  message: "removed from keychain",
  effect: "changed",
  backend_label: "FakeKeyring",
};

const KEYRING_REFUSED: KeysMutationResult = {
  schema_version: "1",
  venue: "kraken",
  status: "unsupported_backend",
  ok: false,
  message: "keyring backend is not a native OS keychain; refused",
  effect: "refused",
  backend_label: null,
};

function makeClient(over: Partial<KeysClient> = {}): KeysClient {
  return {
    getStatus: vi.fn().mockResolvedValue(ABSENT),
    probeAndStore: vi.fn().mockResolvedValue(STORED),
    remove: vi.fn().mockResolvedValue(REMOVED),
    ...over,
  };
}

describe("KeysOnboardingPanel", () => {
  it("loads absent status and shows the probe-and-store form", async () => {
    const client = makeClient();
    render(<KeysOnboardingPanel client={client} />);

    expect(await screen.findByTestId("keys-onboarding")).toBeTruthy();
    expect((await screen.findByTestId("keys-status")).textContent).toMatch(/no key stored/i);
    expect(screen.getByTestId("keys-form")).toBeTruthy();
    expect(screen.getByTestId("keys-paper-only").textContent).toMatch(/paper-only/i);
    await waitFor(() => {
      expect(client.getStatus).toHaveBeenCalled();
    });
  });

  it("probes and stores then shows holdings from the refreshed status", async () => {
    const client = makeClient({
      getStatus: vi.fn().mockResolvedValueOnce(ABSENT).mockResolvedValueOnce(PRESENT),
      probeAndStore: vi.fn().mockResolvedValue(STORED),
    });
    render(<KeysOnboardingPanel client={client} />);
    await screen.findByTestId("keys-form");

    fireEvent.change(screen.getByTestId("keys-public"), {
      target: { value: "fake-public-key" },
    });
    fireEvent.change(screen.getByTestId("keys-private"), {
      target: { value: "fake-private-key" },
    });
    fireEvent.click(screen.getByTestId("keys-store"));

    await waitFor(() => {
      expect(client.probeAndStore).toHaveBeenCalledWith(
        "fake-public-key",
        "fake-private-key",
        "kraken",
      );
    });
    expect((await screen.findByTestId("keys-feedback")).textContent).toMatch(
      /stored in native OS keychain/i,
    );
    expect(await screen.findByTestId("keys-connected")).toBeTruthy();
    expect(screen.getByTestId("keys-balance-ZUSD").textContent).toMatch(/100\.5/);
    expect(screen.getByTestId("keys-balance-XXBT").textContent).toMatch(/0\.01/);
    expect(screen.queryByTestId("keys-public")).toBeNull();
  });

  it("shows the honest keyring-backend refusal from probe-and-store", async () => {
    const client = makeClient({
      probeAndStore: vi.fn().mockResolvedValue(KEYRING_REFUSED),
    });
    render(<KeysOnboardingPanel client={client} />);
    await screen.findByTestId("keys-form");

    fireEvent.change(screen.getByTestId("keys-public"), {
      target: { value: "fake-public-key" },
    });
    fireEvent.change(screen.getByTestId("keys-private"), {
      target: { value: "fake-private-key" },
    });
    fireEvent.click(screen.getByTestId("keys-store"));

    expect((await screen.findByTestId("keys-feedback")).textContent).toMatch(
      /keyring backend is not a native OS keychain/i,
    );
    expect(screen.getByTestId("keys-form")).toBeTruthy();
  });

  it("removes a stored key and returns to the form", async () => {
    const client = makeClient({
      getStatus: vi.fn().mockResolvedValueOnce(PRESENT).mockResolvedValueOnce(ABSENT),
      remove: vi.fn().mockResolvedValue(REMOVED),
    });
    render(<KeysOnboardingPanel client={client} />);
    expect(await screen.findByTestId("keys-connected")).toBeTruthy();

    fireEvent.click(screen.getByTestId("keys-remove"));
    await waitFor(() => {
      expect(client.remove).toHaveBeenCalledWith("kraken");
    });
    expect((await screen.findByTestId("keys-feedback")).textContent).toMatch(
      /removed from keychain/i,
    );
    expect(await screen.findByTestId("keys-form")).toBeTruthy();
  });

  it("surfaces load failures without inventing holdings", async () => {
    const client = makeClient({
      getStatus: vi.fn().mockRejectedValue(new Error("csrf required")),
    });
    render(<KeysOnboardingPanel client={client} />);
    expect((await screen.findByTestId("keys-error")).textContent).toMatch(/csrf required/);
    expect(screen.queryByTestId("keys-balances")).toBeNull();
    expect(screen.queryByTestId("keys-connected")).toBeNull();
  });

  it("waits for the session when disabled", () => {
    const client = makeClient();
    render(<KeysOnboardingPanel client={client} enabled={false} />);
    expect(screen.getByTestId("keys-waiting-session")).toBeTruthy();
    expect(client.getStatus).not.toHaveBeenCalled();
  });
});
