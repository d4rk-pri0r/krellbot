import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { VersionClient } from "../api/version";
import type { KeysClient } from "../features/keys/client";
import { AppHome } from "./AppHome";

afterEach(() => {
  cleanup();
});

function silentKeysClient(): KeysClient {
  return {
    getStatus: vi.fn().mockResolvedValue({
      schema_version: "1",
      venue: "kraken",
      present: false,
      corrupt: false,
      message: "no key stored",
      backend_label: null,
      balances: null,
      balances_available: false,
    }),
    probeAndStore: vi.fn(),
    remove: vi.fn(),
  };
}

function silentVersionClient(): VersionClient {
  return {
    getVersion: vi.fn().mockResolvedValue({
      schema_version: "1",
      version: "0.9.7",
      channel: "prerelease",
      artifacts_signed: false,
    }),
  };
}

describe("AppHome reconnect invite (primary session)", () => {
  it("issues a token and shows QR plus redeem URL", async () => {
    const onIssue = vi.fn().mockResolvedValue({
      token: "tok-primary-1",
      expiresAt: 1700000300,
      expiresIn: 300,
      redeemPath: "/?reconnect=tok-primary-1",
      qrPayload: "http://127.0.0.1:8080/?reconnect=tok-primary-1",
    });
    render(
      <AppHome
        onNavigate={() => {}}
        keysClient={silentKeysClient()}
        versionClient={silentVersionClient()}
        onIssueReconnect={onIssue}
      />,
    );

    fireEvent.click(screen.getByTestId("app-home-reconnect-issue"));
    await waitFor(() => {
      expect(screen.getByTestId("app-home-reconnect-offer")).toBeDefined();
    });
    expect(onIssue).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("app-home-reconnect-token").textContent).toBe(
      "tok-primary-1",
    );
    expect(screen.getByTestId("app-home-reconnect-url").textContent).toContain(
      "reconnect=tok-primary-1",
    );
    expect(screen.getByTestId("app-home-reconnect-qr").tagName).toBe("svg");
  });
});

describe("AppHome reconnect paste (failed session)", () => {
  it("redeems a pasted token from the failure surface", async () => {
    const onRedeem = vi.fn().mockResolvedValue({ ok: true });
    render(
      <AppHome
        onNavigate={() => {}}
        keysClient={silentKeysClient()}
        versionClient={silentVersionClient()}
        sessionFailed
        onRedeemReconnect={onRedeem}
      />,
    );

    fireEvent.change(screen.getByTestId("app-home-reconnect-token-input"), {
      target: { value: " tok-second " },
    });
    fireEvent.click(screen.getByTestId("app-home-reconnect-redeem"));
    await waitFor(() => {
      expect(onRedeem).toHaveBeenCalledWith("tok-second");
    });
  });
});
