import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SettingsView } from "../features/settings/SettingsView";
import { AppHome } from "./AppHome";

afterEach(() => {
  cleanup();
});

describe("Settings reconnect invite (primary session)", () => {
  it("issues a token and shows QR plus redeem URL in Settings → This computer", async () => {
    const onIssue = vi.fn().mockResolvedValue({
      token: "tok-primary-1",
      expiresAt: 1700000300,
      expiresIn: 300,
      redeemPath: "/?reconnect=tok-primary-1",
      qrPayload: "http://127.0.0.1:8080/?reconnect=tok-primary-1",
    });
    render(
      <SettingsView
        section="computer"
        onSectionChange={() => {}}
        onNavigate={() => {}}
        onIssueReconnect={onIssue}
      />,
    );

    fireEvent.click(screen.getByTestId("settings-reconnect-issue"));
    await waitFor(() => {
      expect(screen.getByTestId("settings-reconnect-offer")).toBeDefined();
    });
    expect(onIssue).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("settings-reconnect-token").textContent).toBe(
      "tok-primary-1",
    );
    expect(screen.getByTestId("settings-reconnect-url").textContent).toContain(
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
