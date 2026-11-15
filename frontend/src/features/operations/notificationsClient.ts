import { getCsrf } from "../../session";

export type NotificationEmailSettings = {
  to: string;
  from_addr: string;
  smtp_host: string;
  smtp_port: number;
};

export type NotificationSettings = {
  schema_version: string;
  desktop_enabled: boolean;
  email_enabled: boolean;
  email_configured: boolean;
  email: NotificationEmailSettings;
  smtp_password_env: string;
  telemetry_separate: boolean;
};

export type NotificationSettingsPatch = {
  desktop_enabled?: boolean;
  email_enabled?: boolean;
  email?: Partial<NotificationEmailSettings>;
};

export type NotificationsClient = {
  getNotificationSettings(): Promise<NotificationSettings>;
  updateNotificationSettings(
    patch: NotificationSettingsPatch,
  ): Promise<NotificationSettings>;
};

function adaptEmail(raw: unknown): NotificationEmailSettings {
  const obj = (raw ?? {}) as Record<string, unknown>;
  const portRaw = obj.smtp_port;
  const port =
    typeof portRaw === "number" && Number.isFinite(portRaw)
      ? portRaw
      : typeof portRaw === "string"
        ? Number.parseInt(portRaw, 10)
        : 587;
  return {
    to: typeof obj.to === "string" ? obj.to : "",
    from_addr: typeof obj.from_addr === "string" ? obj.from_addr : "",
    smtp_host: typeof obj.smtp_host === "string" ? obj.smtp_host : "",
    smtp_port: Number.isFinite(port) && port > 0 ? port : 587,
  };
}

export function adaptNotificationSettings(raw: unknown): NotificationSettings {
  const obj = (raw ?? {}) as Record<string, unknown>;
  return {
    schema_version:
      typeof obj.schema_version === "string" ? obj.schema_version : "1",
    desktop_enabled: obj.desktop_enabled === true,
    email_enabled: obj.email_enabled === true,
    email_configured: obj.email_configured === true,
    email: adaptEmail(obj.email),
    smtp_password_env:
      typeof obj.smtp_password_env === "string"
        ? obj.smtp_password_env
        : "KRELLBOT_SMTP_PASSWORD",
    telemetry_separate: obj.telemetry_separate !== false,
  };
}

export function createNotificationsHttpClient(): NotificationsClient {
  return {
    async getNotificationSettings(): Promise<NotificationSettings> {
      const response = await fetch("/api/v1/notifications", {
        method: "GET",
        credentials: "include",
        headers: {
          "X-Krellbot-CSRF": getCsrf(),
        },
      });
      if (!response.ok) {
        throw new Error(`notification settings failed: ${response.status}`);
      }
      return adaptNotificationSettings(await response.json());
    },
    async updateNotificationSettings(
      patch: NotificationSettingsPatch,
    ): Promise<NotificationSettings> {
      const response = await fetch("/api/v1/notifications", {
        method: "PUT",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-Krellbot-CSRF": getCsrf(),
        },
        body: JSON.stringify(patch),
      });
      if (!response.ok) {
        let detail = "";
        try {
          const errBody = (await response.json()) as { message?: unknown };
          if (typeof errBody.message === "string") {
            detail = `: ${errBody.message}`;
          }
        } catch {
          // optional
        }
        throw new Error(
          `notification settings update failed: ${response.status}${detail}`,
        );
      }
      return adaptNotificationSettings(await response.json());
    },
  };
}
