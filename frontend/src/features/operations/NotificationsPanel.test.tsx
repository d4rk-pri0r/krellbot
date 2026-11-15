import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { NotificationsPanel } from "./NotificationsPanel";
import type {
  NotificationSettings,
  NotificationsClient,
} from "./notificationsClient";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function settings(over: Partial<NotificationSettings> = {}): NotificationSettings {
  return {
    schema_version: "1",
    desktop_enabled: false,
    email_enabled: false,
    email_configured: false,
    email: { to: "", from_addr: "", smtp_host: "", smtp_port: 587 },
    smtp_password_env: "KRELLBOT_SMTP_PASSWORD",
    telemetry_separate: true,
    ...over,
  };
}

function makeClient(
  over: Partial<NotificationsClient> = {},
): NotificationsClient {
  return {
    getNotificationSettings: vi.fn().mockResolvedValue(settings()),
    updateNotificationSettings: vi
      .fn()
      .mockImplementation(async (patch) =>
        settings({
          desktop_enabled: patch.desktop_enabled === true,
          email_enabled: patch.email_enabled === true,
          email: {
            to: patch.email?.to ?? "",
            from_addr: patch.email?.from_addr ?? "",
            smtp_host: patch.email?.smtp_host ?? "",
            smtp_port: patch.email?.smtp_port ?? 587,
          },
          email_configured: Boolean(patch.email?.to && patch.email?.smtp_host),
        }),
      ),
    ...over,
  };
}

describe("NotificationsPanel opt-in settings", () => {
  it("loads defaults and states telemetry is separate", async () => {
    const client = makeClient();
    render(<NotificationsPanel client={client} />);

    expect(await screen.findByTestId("ops-notifications")).toBeTruthy();
    await waitFor(() => {
      expect(
        (screen.getByTestId("ops-notifications-desktop") as HTMLInputElement)
          .checked,
      ).toBe(false);
    });
    expect(
      (screen.getByTestId("ops-notifications-email") as HTMLInputElement)
        .checked,
    ).toBe(false);
    expect(screen.getByText(/Telemetry is a separate opt-in/i)).toBeTruthy();
    expect(screen.queryByTestId("ops-notifications-email-fields")).toBeNull();
  });

  it("enables desktop via save without requiring email fields", async () => {
    const client = makeClient();
    render(<NotificationsPanel client={client} />);
    await screen.findByTestId("ops-notifications-form");

    fireEvent.click(screen.getByTestId("ops-notifications-desktop"));
    fireEvent.click(screen.getByTestId("ops-notifications-save"));

    await waitFor(() => {
      expect(client.updateNotificationSettings).toHaveBeenCalledWith(
        expect.objectContaining({ desktop_enabled: true, email_enabled: false }),
      );
    });
    expect(
      (await screen.findByTestId("ops-notifications-feedback")).textContent,
    ).toMatch(/saved/i);
  });

  it("reveals email fields when email is enabled and saves SMTP settings", async () => {
    const client = makeClient();
    render(<NotificationsPanel client={client} />);
    await screen.findByTestId("ops-notifications-form");

    fireEvent.click(screen.getByTestId("ops-notifications-email"));
    expect(screen.getByTestId("ops-notifications-email-fields")).toBeTruthy();
    fireEvent.change(screen.getByTestId("ops-notifications-email-to"), {
      target: { value: "ops@example.com" },
    });
    fireEvent.change(screen.getByTestId("ops-notifications-smtp-host"), {
      target: { value: "smtp.example.com" },
    });
    fireEvent.click(screen.getByTestId("ops-notifications-save"));

    await waitFor(() => {
      expect(client.updateNotificationSettings).toHaveBeenCalledWith(
        expect.objectContaining({
          email_enabled: true,
          email: expect.objectContaining({
            to: "ops@example.com",
            smtp_host: "smtp.example.com",
          }),
        }),
      );
    });
    expect(screen.getByText(/KRELLBOT_SMTP_PASSWORD/)).toBeTruthy();
  });

  it("surfaces load failures as an alert", async () => {
    const client = makeClient({
      getNotificationSettings: vi
        .fn()
        .mockRejectedValue(new Error("network down")),
    });
    render(<NotificationsPanel client={client} />);
    const alert = await screen.findByTestId("ops-notifications-error");
    expect(alert.getAttribute("role")).toBe("alert");
    expect(alert.textContent).toContain("network down");
  });
});
