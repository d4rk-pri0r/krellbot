import { afterEach, describe, expect, it, vi } from "vitest";
import {
  adaptNotificationSettings,
  createNotificationsHttpClient,
} from "./notificationsClient";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("adaptNotificationSettings", () => {
  it("defaults to opt-out and telemetry_separate", () => {
    const adapted = adaptNotificationSettings({});
    expect(adapted.desktop_enabled).toBe(false);
    expect(adapted.email_enabled).toBe(false);
    expect(adapted.telemetry_separate).toBe(true);
    expect(adapted.smtp_password_env).toBe("KRELLBOT_SMTP_PASSWORD");
  });
});

describe("createNotificationsHttpClient", () => {
  it("GETs and PUTs /api/v1/notifications", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        schema_version: "1",
        desktop_enabled: true,
        email_enabled: false,
        email_configured: false,
        email: { to: "", from_addr: "", smtp_host: "", smtp_port: 587 },
        smtp_password_env: "KRELLBOT_SMTP_PASSWORD",
        telemetry_separate: true,
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const client = createNotificationsHttpClient();
    const got = await client.getNotificationSettings();
    expect(got.desktop_enabled).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/notifications",
      expect.objectContaining({ method: "GET", credentials: "include" }),
    );

    await client.updateNotificationSettings({ desktop_enabled: true });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/notifications",
      expect.objectContaining({ method: "PUT", credentials: "include" }),
    );
  });
});
