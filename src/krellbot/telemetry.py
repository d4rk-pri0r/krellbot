"""Telemetry: opt-in fill reporting.

Telemetry is off by default. `enable` prints an example payload and writes
the install only when the operator types `y` on stdin. `disable` flips it
off. `show` prints what is currently stored without sending. `maybe_send`
is the hook the engine calls after a paper fill; it returns without
calling the injected transport when telemetry is disabled.

A fill payload has exactly eleven keys (see `PAYLOAD_KEYS`) and never
includes a balance, an API key, a license, an IP, or the raw quantity.
The quantity is bucketed: `qty_bucket` is `floor(log2(USD_notional))` so
the precise size of a trade never leaves the machine.
"""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Protocol

from krellbot import paths as kb_paths

DEFAULT_URL = "https://krellbot.dev/api/telemetry"
CONFIG_FILE = "telemetry.json"

PAYLOAD_KEYS: tuple[str, ...] = (
    "install_id",
    "pack_id",
    "pack_version",
    "venue",
    "pair",
    "side",
    "bar_ts",
    "modeled_px",
    "fill_px",
    "qty_bucket",
    "fee_bps",
)


class Transport(Protocol):
    """HTTP-shaped transport for telemetry POSTs."""

    def post(self, url: str, body: bytes, headers: dict) -> object: ...


def _path(home: Path) -> Path:
    return Path(home) / CONFIG_FILE


def _load(home: Path) -> dict:
    p = _path(home)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(home: Path, data: dict) -> None:
    kb_paths.atomic_write(_path(home), (json.dumps(data, sort_keys=True) + "\n").encode("utf-8"))


def is_enabled(home: Path) -> bool:
    """True if telemetry is currently enabled on this install."""
    return bool(_load(home).get("enabled"))


def example_payload(install_id: str) -> dict:
    """Return an example fill payload with placeholder values.

    The placeholder values are empty strings or zero so an operator reading
    the example sees the exact eleven keys that ship in a real fill.
    """
    return {
        "install_id": install_id,
        "pack_id": "",
        "pack_version": "",
        "venue": "",
        "pair": "",
        "side": "buy",
        "bar_ts": 0,
        "modeled_px": "0",
        "fill_px": "0",
        "qty_bucket": 0,
        "fee_bps": 0,
    }


def enable(home: Path, *, stdin_fn=None) -> bool:
    """Print an example payload, ask the operator, enable only on `y`.

    `stdin_fn` defaults to the built-in `input` for the CLI; tests inject a
    callable that returns the answer string so the suite never blocks. The
    install_id is a UUID4 generated the first time and persisted so re-runs
    do not double-count.
    """
    if stdin_fn is None:
        stdin_fn = input
    kb_paths.ensure_layout()
    data = _load(home)
    install_id = data.get("install_id") or str(uuid.uuid4())
    print(json.dumps(example_payload(install_id), indent=2, sort_keys=True))
    try:
        answer = stdin_fn().strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    if answer != "y":
        return False
    data["enabled"] = True
    data["install_id"] = install_id
    data.setdefault("url", DEFAULT_URL)
    _save(home, data)
    return True


def disable(home: Path) -> None:
    """Turn telemetry off. Persists the flag so a future enable reuses the install_id."""
    data = _load(home)
    data["enabled"] = False
    _save(home, data)


def show(home: Path) -> None:
    """Print what is currently stored. Does not send."""
    data = _load(home)
    print(json.dumps(data, indent=2, sort_keys=True))


def qty_bucket(usd_notional) -> int:
    """Floor of log2 of the USD notional.

    A $1 trade lands in bucket 0, a $2 trade in bucket 1, $4 in 2, $100 in 6,
    $1024 in 10. The raw quantity never leaves the machine: only the bucket.
    """
    try:
        n = float(usd_notional)
    except (TypeError, ValueError):
        return 0
    if n <= 0:
        return 0
    return math.floor(math.log2(n))


def resolve_transport(home: Path, transport: Transport | None) -> Transport | None:
    """Use the caller's transport. When omitted, send only if telemetry is on."""
    if transport is not None:
        return transport
    if not is_enabled(home):
        return None
    return UrllibTransport()


def _payload(fill: dict, install_id: str) -> dict | None:
    """Keep only the eleven allowed keys. Extra fields are dropped, not sent."""
    out = {"install_id": install_id}
    for key in PAYLOAD_KEYS:
        if key == "install_id":
            continue
        if key not in fill:
            return None
        out[key] = fill[key]
    return out


def maybe_send(home: Path, fill: dict, transport: Transport) -> None:
    """Send fill telemetry if enabled. Returns without touching `transport`
    when telemetry is off.

    `install_id` is injected from the install record if the caller did not
    set one. The URL is the stored URL or `DEFAULT_URL`. The transport is
    called only when telemetry is enabled, so a disabled install never
    makes an HTTP request.
    """
    data = _load(home)
    if not data.get("enabled"):
        return
    install_id = str(fill.get("install_id") or data.get("install_id") or "")
    body_obj = _payload(fill, install_id)
    if body_obj is None or not install_id:
        return
    url = str(data.get("url") or DEFAULT_URL)
    body = json.dumps(body_obj, sort_keys=True).encode("utf-8")
    headers = {"content-type": "application/json", "user-agent": "krellbot/0.1"}
    transport.post(url, body, headers)


class UrllibTransport:
    """Default transport used by the CLI. Tests inject their own."""

    def __init__(self, *, timeout: float = 10.0) -> None:
        self._timeout = timeout

    def post(self, url: str, body: bytes, headers: dict) -> object:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        from krellbot.tls import urlopen

        try:
            with urlopen(req, timeout=self._timeout) as res:
                return res.read()
        except urllib.error.URLError:
            # Telemetry is best-effort. A failed POST must not crash the tick.
            return None
