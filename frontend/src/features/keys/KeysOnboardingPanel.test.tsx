/**
 * Exchange keys onboarding panel — Workspace form (KRELL-SIGNAL-20261010).
 *
 * Happy path and honest keyring errors use injectable fake clients only.
 * No real credentials, keyring, or exchange network. Covers Kraken and
 * Coinbase via the shared panel.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { KeysOnboardingPanel } from "./KeysOnboardingPanel";
import type { KeysClient, KeysMutationResult, KeysStatus, KeysVenue } from "./client";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function absent(venue: KeysVenue): KeysStatus {
  return {
    schema_version: "1",
    venue,
    present: false,
    corrupt: false,
    message: "no key stored",
    backend_label: null,
    balances: null,
    balances_available: false,
  };
}

function present(venue: KeysVenue, balances: KeysStatus["balances"]): KeysStatus {
  return {
    schema_version: "1",
    venue,
    present: true,
    corrupt: false,
    message: "key present",
    backend_label: "FakeKeyring",
    balances,
    balances_available: true,
  };
}

function stored(venue: KeysVenue): KeysMutationResult {
  return {
    schema_version: "1",
    venue,
    status: "stored",
    ok: true,
    message: "stored in native OS keychain",
    effect: "changed",
    backend_label: "FakeKeyring",
  };
}

function removed(venue: KeysVenue): KeysMutationResult {
  return {
    schema_version: "1",
    venue,
    status: "removed",
    ok: true,
    message: "removed from keychain",
    effect: "changed",
    backend_label: "FakeKeyring",
  };
}

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
    getStatus: vi.fn().mockResolvedValue(absent("kraken")),
    probeAndStore: vi.fn().mockResolvedValue(stored("kraken")),
    remove: vi.fn().mockResolvedValue(removed("kraken")),
    ...over,
  };
}

describe.each([
  {
    venue: "kraken" as const,
    title: /Kraken exchange key/i,
    balances: [
      { asset: "ZUSD", free: "100.5" },
      { asset: "XXBT", free: "0.01" },
    ],
    publicValue: "fake-public-key",
    privateValue: "fake-private-key",
  },
  {
    venue: "coinbase" as const,
    title: /Coinbase exchange key/i,
    balances: [
      { asset: "USD", free: "250.75" },
      { asset: "BTC", free: "0.002" },
    ],
    publicValue: "organizations/fake/apiKeys/fake",
    privateValue: "-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----",
  },
])("KeysOnboardingPanel ($venue)", ({ venue, title, balances, publicValue, privateValue }) => {
  it("loads absent status and shows the probe-and-store form", async () => {
    const client = makeClient({
      getStatus: vi.fn().mockResolvedValue(absent(venue)),
    });
    render(<KeysOnboardingPanel client={client} venue={venue} />);

    expect(await screen.findByTestId(`keys-onboarding-${venue}`)).toBeTruthy();
    expect(screen.getByTestId(`keys-onboarding-${venue}`).textContent).toMatch(title);
    expect((await screen.findByTestId(`keys-status-${venue}`)).textContent).toMatch(
      /no key stored/i,
    );
    expect(screen.getByTestId(`keys-form-${venue}`)).toBeTruthy();
    expect(screen.getByTestId(`keys-paper-only-${venue}`).textContent).toMatch(/paper-only/i);
    await waitFor(() => {
      expect(client.getStatus).toHaveBeenCalledWith(venue);
    });
  });

  it("probes and stores then shows holdings from the refreshed status", async () => {
    const client = makeClient({
      getStatus: vi
        .fn()
        .mockResolvedValueOnce(absent(venue))
        .mockResolvedValueOnce(present(venue, balances)),
      probeAndStore: vi.fn().mockResolvedValue(stored(venue)),
    });
    render(<KeysOnboardingPanel client={client} venue={venue} />);
    await screen.findByTestId(`keys-form-${venue}`);

    fireEvent.change(screen.getByTestId(`keys-public-${venue}`), {
      target: { value: publicValue },
    });
    fireEvent.change(screen.getByTestId(`keys-private-${venue}`), {
      target: { value: privateValue },
    });
    fireEvent.click(screen.getByTestId(`keys-store-${venue}`));

    await waitFor(() => {
      expect(client.probeAndStore).toHaveBeenCalledWith(publicValue, privateValue, venue);
    });
    expect((await screen.findByTestId(`keys-feedback-${venue}`)).textContent).toMatch(
      /stored in native OS keychain/i,
    );
    expect(await screen.findByTestId(`keys-stored-${venue}`)).toBeTruthy();
    for (const row of balances) {
      expect(screen.getByTestId(`keys-balance-${venue}-${row.asset}`).textContent).toMatch(
        new RegExp(row.free.replace(".", "\\.")),
      );
    }
    expect(screen.queryByTestId(`keys-public-${venue}`)).toBeNull();
  });

  it("shows the honest keyring-backend refusal from probe-and-store", async () => {
    const client = makeClient({
      getStatus: vi.fn().mockResolvedValue(absent(venue)),
      probeAndStore: vi.fn().mockResolvedValue({ ...KEYRING_REFUSED, venue }),
    });
    render(<KeysOnboardingPanel client={client} venue={venue} />);
    await screen.findByTestId(`keys-form-${venue}`);

    fireEvent.change(screen.getByTestId(`keys-public-${venue}`), {
      target: { value: publicValue },
    });
    fireEvent.change(screen.getByTestId(`keys-private-${venue}`), {
      target: { value: privateValue },
    });
    fireEvent.click(screen.getByTestId(`keys-store-${venue}`));

    expect((await screen.findByTestId(`keys-feedback-${venue}`)).textContent).toMatch(
      /keyring backend is not a native OS keychain/i,
    );
    expect(screen.getByTestId(`keys-form-${venue}`)).toBeTruthy();
  });

  it("removes a stored key and returns to the form", async () => {
    const client = makeClient({
      getStatus: vi
        .fn()
        .mockResolvedValueOnce(present(venue, balances))
        .mockResolvedValueOnce(absent(venue)),
      remove: vi.fn().mockResolvedValue(removed(venue)),
    });
    render(<KeysOnboardingPanel client={client} venue={venue} />);
    expect(await screen.findByTestId(`keys-stored-${venue}`)).toBeTruthy();

    fireEvent.click(screen.getByTestId(`keys-remove-${venue}`));
    await waitFor(() => {
      expect(client.remove).toHaveBeenCalledWith(venue);
    });
    expect((await screen.findByTestId(`keys-feedback-${venue}`)).textContent).toMatch(
      /removed from keychain/i,
    );
    expect(await screen.findByTestId(`keys-form-${venue}`)).toBeTruthy();
  });

  it("surfaces load failures without inventing holdings", async () => {
    const client = makeClient({
      getStatus: vi.fn().mockRejectedValue(new Error("csrf required")),
    });
    render(<KeysOnboardingPanel client={client} venue={venue} />);
    expect((await screen.findByTestId(`keys-error-${venue}`)).textContent).toMatch(
      /csrf required/,
    );
    expect(screen.queryByTestId(`keys-balances-${venue}`)).toBeNull();
    expect(screen.queryByTestId(`keys-stored-${venue}`)).toBeNull();
  });

  it("waits for the session when disabled", () => {
    const client = makeClient();
    render(<KeysOnboardingPanel client={client} venue={venue} enabled={false} />);
    expect(screen.getByTestId(`keys-waiting-session-${venue}`)).toBeTruthy();
    expect(client.getStatus).not.toHaveBeenCalled();
  });
});

describe("KeysOnboardingPanel Coinbase PEM field", () => {
  it("uses a multiline private-key field for Coinbase", async () => {
    const client = makeClient({
      getStatus: vi.fn().mockResolvedValue(absent("coinbase")),
    });
    render(<KeysOnboardingPanel client={client} venue="coinbase" />);
    await screen.findByTestId("keys-form-coinbase");
    const secret = screen.getByTestId("keys-private-coinbase");
    expect(secret.tagName).toBe("TEXTAREA");
    expect(screen.getByLabelText(/Private key \(PEM\)/i)).toBeTruthy();
    expect(screen.getByLabelText(/API key name/i)).toBeTruthy();
  });
});
