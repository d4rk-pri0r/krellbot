"""Opt-in desktop and email notifications for Operations alerts.

Notifications are off by default. The operator enables desktop and/or
email from the Settings UI; acknowledgement of alerts remains in-app.
Telemetry is a separate opt-in (see ``krellbot.telemetry``) and is never
toggled by this module.

Desktop is the preferred channel: it needs no external credentials.
Email is optional and never stores an SMTP password in
``notifications.json`` — when email is enabled the password is read
only from the ``KRELLBOT_SMTP_PASSWORD`` environment variable at send
time. No secrets ship in the repository.

Tests inject a ``FakeNotifier`` so no desktop bus or SMTP host is
touched.
"""

from __future__ import annotations

import json
import os
import smtplib
import subprocess
import sys
from dataclasses import dataclass, field
from email.message import EmailMessage
from pathlib import Path
from typing import Literal, Protocol

from krellbot import paths as kb_paths

SCHEMA_VERSION = "1"
CONFIG_FILE = "notifications.json"
SENT_FILE = "notifications-sent.json"
SMTP_PASSWORD_ENV = "KRELLBOT_SMTP_PASSWORD"

Channel = Literal["desktop", "email"]


class Notifier(Protocol):
    """Deliver one alert notification on a single channel."""

    def notify(
        self,
        *,
        channel: Channel,
        title: str,
        body: str,
        alert_id: str,
    ) -> None: ...


@dataclass
class FakeNotifier:
    """Test double that records every notify call and never egresses."""

    sent: list[dict[str, str]] = field(default_factory=list)

    def notify(
        self,
        *,
        channel: Channel,
        title: str,
        body: str,
        alert_id: str,
    ) -> None:
        self.sent.append(
            {
                "channel": channel,
                "title": title,
                "body": body,
                "alert_id": alert_id,
            }
        )


def _config_path(home: Path) -> Path:
    return Path(home) / CONFIG_FILE


def _sent_path(home: Path) -> Path:
    return Path(home) / "run" / SENT_FILE


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    kb_paths.atomic_write(path, (json.dumps(data, sort_keys=True) + "\n").encode("utf-8"))


def _normalize_email(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict):
        raw = {}
    port_raw = raw.get("smtp_port", 587)
    try:
        port = int(port_raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        port = 587
    if port <= 0 or port > 65535:
        port = 587
    return {
        "to": str(raw.get("to") or ""),
        "from_addr": str(raw.get("from_addr") or ""),
        "smtp_host": str(raw.get("smtp_host") or ""),
        "smtp_port": port,
    }


def _load(home: Path) -> dict:
    data = _load_json(_config_path(home))
    return {
        "desktop_enabled": bool(data.get("desktop_enabled")),
        "email_enabled": bool(data.get("email_enabled")),
        "email": _normalize_email(data.get("email")),
    }


def _save(home: Path, data: dict) -> None:
    payload = {
        "desktop_enabled": bool(data.get("desktop_enabled")),
        "email_enabled": bool(data.get("email_enabled")),
        "email": _normalize_email(data.get("email")),
    }
    _save_json(_config_path(home), payload)


def email_is_configured(email: dict[str, object]) -> bool:
    """True when SMTP host and destination address are both set."""
    return bool(str(email.get("to") or "").strip() and str(email.get("smtp_host") or "").strip())


def get_settings(home: Path) -> dict:
    """Closed-shape settings for the Settings UI / API (no secrets)."""
    data = _load(home)
    email = data["email"]
    assert isinstance(email, dict)
    return {
        "schema_version": SCHEMA_VERSION,
        "desktop_enabled": bool(data["desktop_enabled"]),
        "email_enabled": bool(data["email_enabled"]),
        "email_configured": email_is_configured(email),
        "email": {
            "to": str(email["to"]),
            "from_addr": str(email["from_addr"]),
            "smtp_host": str(email["smtp_host"]),
            "smtp_port": int(email["smtp_port"]),  # type: ignore[arg-type]
        },
        "smtp_password_env": SMTP_PASSWORD_ENV,
        "telemetry_separate": True,
    }


def update_settings(home: Path, patch: dict) -> dict:
    """Apply a settings patch. Unknown keys are ignored. Never stores a password."""

    if not isinstance(patch, dict):
        raise TypeError("settings patch must be an object")
    data = _load(home)
    if "desktop_enabled" in patch:
        data["desktop_enabled"] = bool(patch["desktop_enabled"])
    if "email_enabled" in patch:
        data["email_enabled"] = bool(patch["email_enabled"])
    if "email" in patch:
        email_patch = patch["email"]
        if email_patch is None:
            data["email"] = _normalize_email({})
        elif isinstance(email_patch, dict):
            # Reject password-shaped fields so secrets never land on disk.
            forbidden = {"password", "smtp_password", "secret", "api_key"}
            if forbidden.intersection(email_patch):
                raise ValueError(f"email password must come from ${SMTP_PASSWORD_ENV}, not settings")
            merged = dict(data["email"])  # type: ignore[arg-type]
            for key in ("to", "from_addr", "smtp_host", "smtp_port"):
                if key in email_patch:
                    merged[key] = email_patch[key]
            data["email"] = _normalize_email(merged)
        else:
            raise TypeError("email must be an object")
    _save(home, data)
    return get_settings(home)


def desktop_enabled(home: Path) -> bool:
    return bool(_load(home)["desktop_enabled"])


def email_enabled(home: Path) -> bool:
    return bool(_load(home)["email_enabled"])


def _load_sent(home: Path) -> dict[str, int]:
    raw = _load_json(_sent_path(home))
    out: dict[str, int] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        try:
            out[key] = int(value)
        except (TypeError, ValueError):
            continue
    return out


def _save_sent(home: Path, sent: dict[str, int]) -> None:
    _save_json(_sent_path(home), sent)


def _alert_title(alert: object) -> str:
    kind = getattr(alert, "kind", None)
    if isinstance(alert, dict):
        kind = alert.get("kind")
    severity = getattr(alert, "severity", None)
    if isinstance(alert, dict):
        severity = alert.get("severity")
    kind_s = str(kind or "alert")
    sev_s = str(severity or "warning")
    return f"Krellbot {sev_s}: {kind_s}"


def _alert_body(alert: object) -> str:
    if isinstance(alert, dict):
        code = alert.get("code")
        venue = alert.get("venue")
        pair = alert.get("pair")
        count = alert.get("count", 1)
        acknowledged = alert.get("acknowledged")
    else:
        code = getattr(alert, "code", None)
        venue = getattr(alert, "venue", None)
        pair = getattr(alert, "pair", None)
        count = getattr(alert, "count", 1)
        acknowledged = getattr(alert, "acknowledged", False)
    parts = [f"count={count}"]
    if code:
        parts.append(f"code={code}")
    if venue:
        parts.append(f"venue={venue}")
    if pair:
        parts.append(f"pair={pair}")
    parts.append("ack=in-app" if not acknowledged else "ack=done")
    return " ".join(parts)


def _alert_id(alert: object) -> str | None:
    if isinstance(alert, dict):
        value = alert.get("id")
    else:
        value = getattr(alert, "id", None)
    return value if isinstance(value, str) and value else None


def _alert_last_ts(alert: object) -> int:
    if isinstance(alert, dict):
        value = alert.get("last_ts", 0)
    else:
        value = getattr(alert, "last_ts", 0)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _alert_acknowledged(alert: object) -> bool:
    if isinstance(alert, dict):
        return bool(alert.get("acknowledged"))
    return bool(getattr(alert, "acknowledged", False))


class DesktopLocalNotifier:
    """Best-effort local desktop notification (notify-send / osascript)."""

    def notify(
        self,
        *,
        channel: Channel,
        title: str,
        body: str,
        alert_id: str,
    ) -> None:
        if channel != "desktop":
            return
        try:
            if sys.platform == "darwin":
                script = f"display notification {json.dumps(body)} with title {json.dumps(title)}"
                subprocess.run(
                    ["osascript", "-e", script],
                    check=False,
                    capture_output=True,
                    timeout=5,
                )
            elif sys.platform.startswith("linux"):
                subprocess.run(
                    ["notify-send", "--app-name=Krellbot", title, body],
                    check=False,
                    capture_output=True,
                    timeout=5,
                )
            # Windows and unknown platforms: soft no-op (no secrets, no crash).
        except (OSError, subprocess.SubprocessError):
            return


class EmailSmtpNotifier:
    """Best-effort SMTP email. Password from ``KRELLBOT_SMTP_PASSWORD`` only."""

    def __init__(self, email: dict[str, object], *, password: str | None = None) -> None:
        self._email = _normalize_email(email)
        self._password = password if password is not None else os.environ.get(SMTP_PASSWORD_ENV, "")

    def notify(
        self,
        *,
        channel: Channel,
        title: str,
        body: str,
        alert_id: str,
    ) -> None:
        if channel != "email":
            return
        if not email_is_configured(self._email):
            return
        to_addr = str(self._email["to"]).strip()
        from_addr = str(self._email["from_addr"]).strip() or to_addr
        host = str(self._email["smtp_host"]).strip()
        port = int(self._email["smtp_port"])  # type: ignore[arg-type]
        msg = EmailMessage()
        msg["Subject"] = title
        msg["From"] = from_addr
        msg["To"] = to_addr
        msg.set_content(f"{body}\n\nalert_id={alert_id}\n")
        try:
            with smtplib.SMTP(host, port, timeout=10) as smtp:
                smtp.ehlo()
                try:
                    smtp.starttls()
                    smtp.ehlo()
                except smtplib.SMTPException:
                    pass
                if self._password:
                    smtp.login(from_addr, self._password)
                smtp.send_message(msg)
        except (OSError, smtplib.SMTPException):
            return


@dataclass
class CompositeNotifier:
    """Routes channel-tagged notify calls to desktop and email backends."""

    desktop: Notifier
    email: Notifier

    def notify(
        self,
        *,
        channel: Channel,
        title: str,
        body: str,
        alert_id: str,
    ) -> None:
        if channel == "desktop":
            self.desktop.notify(channel=channel, title=title, body=body, alert_id=alert_id)
        elif channel == "email":
            self.email.notify(channel=channel, title=title, body=body, alert_id=alert_id)


def default_notifier(home: Path) -> Notifier:
    """Build the production composite notifier from current settings."""
    data = _load(home)
    email = data["email"]
    assert isinstance(email, dict)
    return CompositeNotifier(
        desktop=DesktopLocalNotifier(),
        email=EmailSmtpNotifier(email),
    )


def maybe_notify(
    home: Path,
    alerts: list,
    *,
    notifier: Notifier | None = None,
) -> int:
    """Notify for newly seen unacknowledged alerts on enabled channels.

    Returns the number of channel deliveries attempted. Acknowledged
    alerts are skipped (ack remains in-app). When both channels are
    disabled the notifier is never called. Dedupes by ``alert_id`` +
    ``last_ts`` so a later occurrence re-notifies.
    """

    data = _load(home)
    desktop_on = bool(data["desktop_enabled"])
    email_on = bool(data["email_enabled"])
    email_cfg = data["email"]
    assert isinstance(email_cfg, dict)
    email_ready = email_on and email_is_configured(email_cfg)
    if not desktop_on and not email_ready:
        return 0

    active = notifier if notifier is not None else default_notifier(home)
    sent = _load_sent(home)
    deliveries = 0
    dirty = False

    for alert in alerts:
        alert_id = _alert_id(alert)
        if alert_id is None:
            continue
        if _alert_acknowledged(alert):
            continue
        last_ts = _alert_last_ts(alert)
        previous = sent.get(alert_id, 0)
        if last_ts <= previous:
            continue
        title = _alert_title(alert)
        body = _alert_body(alert)
        if desktop_on:
            active.notify(channel="desktop", title=title, body=body, alert_id=alert_id)
            deliveries += 1
        if email_ready:
            active.notify(channel="email", title=title, body=body, alert_id=alert_id)
            deliveries += 1
        sent[alert_id] = last_ts
        dirty = True

    if dirty:
        _save_sent(home, sent)
    return deliveries
