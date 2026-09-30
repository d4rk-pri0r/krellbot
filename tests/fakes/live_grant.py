"""Operator-grant writer for the live authorization gate.

The brief is explicit: only ``tests/fakes/live_grant.py`` may write
``live-authorization.json``. The product (``src/``) never creates the
file, and the live gate's ``read_authorization`` is the only reader.
The fake matches the v1 schema the gate validates:

    {
      "schema_version": "1",
      "granted_by": "operator",
      "expires_at": <int epoch>,
      "grants": [{"venue": <str>, "pair": <str>}, ...]
    }

Tests call ``write_grant(home, venue="kraken", pair="SUIUSD")`` after
``monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")`` so the live gate
lets a ``run.tick`` past.
"""

from __future__ import annotations

import json
from pathlib import Path

from krellbot.application import live_gate

DEFAULT_EXPIRES_AT = 4_102_444_800  # 2100-01-01T00:00:00Z


def write_grant(
    home: Path,
    *,
    venue: str,
    pair: str,
    expires_at: int = DEFAULT_EXPIRES_AT,
) -> Path:
    """Write a single-grant authorization record under ``home``.

    Returns the file path so a test can stat it, mtime it, or delete
    it between phases. The file is JSON with sorted keys and the
    minimum whitespace so byte-comparison assertions stay stable.
    """
    payload = {
        "schema_version": "1",
        "granted_by": "operator",
        "expires_at": int(expires_at),
        "grants": [{"venue": str(venue), "pair": str(pair)}],
    }
    path = live_gate.auth_path(home)
    path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    return path
