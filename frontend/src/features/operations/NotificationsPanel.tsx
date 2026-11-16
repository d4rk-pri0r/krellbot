import { useCallback, useEffect, useRef, useState, type JSX } from "react";
import "./NotificationsPanel.signal.css";
import type { NotificationsClient, NotificationSettings } from "./notificationsClient";

const PANEL_TITLE = "Notifications";
const LOADING_TEXT = "Loading notification settings…";
const LOAD_ERROR_PREFIX =
  "Could not load notification settings — check the workstation is running.";
const HELPER_TEXT =
  "Opt in to local desktop and/or email alerts. Acknowledgements stay in Operations. Telemetry is a separate opt-in and is not controlled here.";
const DESKTOP_LABEL = "Desktop notifications";
const EMAIL_LABEL = "Email notifications";
const DESKTOP_HINT = "Local only — no external credentials required.";
const EMAIL_HINT_PREFIX = "SMTP password is never stored here; set";
const SAVE_LABEL = "Save";
const SAVING_LABEL = "Saving…";
const CLIENT_UNAVAILABLE =
  "Notification settings are unavailable in this build.";

export type NotificationsPanelProps = {
  client: NotificationsClient;
};

function emptyEmail(): NotificationSettings["email"] {
  return { to: "", from_addr: "", smtp_host: "", smtp_port: 587 };
}

export function NotificationsPanel({
  client,
}: NotificationsPanelProps): JSX.Element {
  const [settings, setSettings] = useState<NotificationSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [desktopEnabled, setDesktopEnabled] = useState(false);
  const [emailEnabled, setEmailEnabled] = useState(false);
  const [emailTo, setEmailTo] = useState("");
  const [emailFrom, setEmailFrom] = useState("");
  const [smtpHost, setSmtpHost] = useState("");
  const [smtpPort, setSmtpPort] = useState("587");
  const requestRef = useRef(0);
  const inFlight = useRef(false);

  const hasClient = typeof client.getNotificationSettings === "function";

  const applySettings = useCallback((next: NotificationSettings): void => {
    setSettings(next);
    setDesktopEnabled(next.desktop_enabled);
    setEmailEnabled(next.email_enabled);
    const email = next.email ?? emptyEmail();
    setEmailTo(email.to);
    setEmailFrom(email.from_addr);
    setSmtpHost(email.smtp_host);
    setSmtpPort(String(email.smtp_port || 587));
  }, []);

  const load = useCallback(async (): Promise<void> => {
    if (!hasClient) {
      setSettings(null);
      setError(CLIENT_UNAVAILABLE);
      setLoading(false);
      return;
    }
    const requestId = ++requestRef.current;
    setLoading(true);
    setError(null);
    try {
      const next = await client.getNotificationSettings();
      if (requestId !== requestRef.current) {
        return;
      }
      applySettings(next);
    } catch (err) {
      if (requestId !== requestRef.current) {
        return;
      }
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (requestId === requestRef.current) {
        setLoading(false);
      }
    }
  }, [applySettings, client, hasClient]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleSave = useCallback(async (): Promise<void> => {
    if (inFlight.current || !hasClient) {
      return;
    }
    inFlight.current = true;
    setPending(true);
    setFeedback(null);
    const portNum = Number.parseInt(smtpPort, 10);
    try {
      const next = await client.updateNotificationSettings({
        desktop_enabled: desktopEnabled,
        email_enabled: emailEnabled,
        email: {
          to: emailTo.trim(),
          from_addr: emailFrom.trim(),
          smtp_host: smtpHost.trim(),
          smtp_port: Number.isFinite(portNum) && portNum > 0 ? portNum : 587,
        },
      });
      applySettings(next);
      setFeedback("Notification settings saved.");
    } catch (err) {
      setFeedback(
        `Save failed: ${err instanceof Error ? err.message : String(err)}`,
      );
    } finally {
      inFlight.current = false;
      setPending(false);
    }
  }, [
    applySettings,
    client,
    desktopEnabled,
    emailEnabled,
    emailFrom,
    emailTo,
    hasClient,
    smtpHost,
    smtpPort,
  ]);

  const busy = pending || loading;
  const passwordEnv =
    settings?.smtp_password_env ?? "KRELLBOT_SMTP_PASSWORD";

  return (
    <div
      className="kbot-ops__notifications"
      data-testid="ops-notifications"
    >
      <div className="kbot-ops__notifications-head">
        <h2 className="kbot-ops__panel-title" id="ops-notifications-title">
          {PANEL_TITLE}
        </h2>
        <button
          type="button"
          className="kbot-ops__notifications-refresh"
          data-testid="ops-notifications-refresh"
          disabled={busy || !hasClient}
          aria-busy={loading || undefined}
          onClick={() => {
            void load();
          }}
        >
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>

      <p className="kbot-ops__notifications-helper">{HELPER_TEXT}</p>

      {!hasClient ? (
        <p
          className="kbot-ops__notifications-error"
          role="alert"
          data-testid="ops-notifications-unavailable"
        >
          {CLIENT_UNAVAILABLE}
        </p>
      ) : null}

      {hasClient && loading && settings === null ? (
        <p
          className="kbot-ops__notifications-status"
          role="status"
          data-testid="ops-notifications-loading"
        >
          {LOADING_TEXT}
        </p>
      ) : null}

      {error !== null ? (
        <p
          className="kbot-ops__notifications-error"
          role="alert"
          data-testid="ops-notifications-error"
        >
          {LOAD_ERROR_PREFIX} ({error})
        </p>
      ) : null}

      {settings !== null ? (
        <form
          className="kbot-ops__notifications-form"
          data-testid="ops-notifications-form"
          onSubmit={(event) => {
            event.preventDefault();
            void handleSave();
          }}
        >
          <label className="kbot-ops__notifications-toggle">
            <input
              type="checkbox"
              data-testid="ops-notifications-desktop"
              checked={desktopEnabled}
              disabled={busy}
              onChange={(event) => setDesktopEnabled(event.target.checked)}
            />
            <span>
              <span className="kbot-ops__notifications-toggle-label">
                {DESKTOP_LABEL}
              </span>
              <span className="kbot-ops__notifications-toggle-hint">
                {DESKTOP_HINT}
              </span>
            </span>
          </label>

          <label className="kbot-ops__notifications-toggle">
            <input
              type="checkbox"
              data-testid="ops-notifications-email"
              checked={emailEnabled}
              disabled={busy}
              onChange={(event) => setEmailEnabled(event.target.checked)}
            />
            <span>
              <span className="kbot-ops__notifications-toggle-label">
                {EMAIL_LABEL}
              </span>
              <span className="kbot-ops__notifications-toggle-hint">
                {EMAIL_HINT_PREFIX}{" "}
                <code className="kbot-ops__notifications-env">{passwordEnv}</code>.
              </span>
            </span>
          </label>

          {emailEnabled ? (
            <div
              className="kbot-ops__notifications-email-fields"
              data-testid="ops-notifications-email-fields"
            >
              <label className="kbot-ops__notifications-field">
                <span>To</span>
                <input
                  type="email"
                  data-testid="ops-notifications-email-to"
                  autoComplete="off"
                  value={emailTo}
                  disabled={busy}
                  onChange={(event) => setEmailTo(event.target.value)}
                />
              </label>
              <label className="kbot-ops__notifications-field">
                <span>From</span>
                <input
                  type="email"
                  data-testid="ops-notifications-email-from"
                  autoComplete="off"
                  value={emailFrom}
                  disabled={busy}
                  onChange={(event) => setEmailFrom(event.target.value)}
                />
              </label>
              <label className="kbot-ops__notifications-field">
                <span>SMTP host</span>
                <input
                  type="text"
                  data-testid="ops-notifications-smtp-host"
                  autoComplete="off"
                  spellCheck={false}
                  value={smtpHost}
                  disabled={busy}
                  onChange={(event) => setSmtpHost(event.target.value)}
                />
              </label>
              <label className="kbot-ops__notifications-field">
                <span>SMTP port</span>
                <input
                  type="number"
                  data-testid="ops-notifications-smtp-port"
                  autoComplete="off"
                  value={smtpPort}
                  disabled={busy}
                  onChange={(event) => setSmtpPort(event.target.value)}
                />
              </label>
            </div>
          ) : null}

          <div className="kbot-ops__notifications-actions">
            <button
              type="submit"
              className="kbot-ops__notifications-save"
              data-testid="ops-notifications-save"
              disabled={busy}
              aria-busy={pending || undefined}
            >
              {pending ? SAVING_LABEL : SAVE_LABEL}
            </button>
          </div>
        </form>
      ) : null}

      {feedback !== null ? (
        <p
          className="kbot-ops__notifications-feedback"
          role="status"
          data-testid="ops-notifications-feedback"
        >
          {feedback}
        </p>
      ) : null}
    </div>
  );
}
