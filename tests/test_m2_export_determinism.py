"""M2-CE canonical-byte export determinism.

The brief pins backend determinism with a committed test. For two
independent fresh homes (``tmp_path/"a"``, ``tmp_path/"b"``) and a
second job inside home A, the ``GET /api/v1/jobs/{id}/result/download``
bytes must be byte-identical across the three runs. The body must
equal ``canonical_receipt_bytes(receipt)`` for the parsed receipt, the
receipt keys are exactly the locked set, and ``data_manifest_sha256``
equals the sha256 of the dataset CSV bytes.

Run with::

    H=$(mktemp -d "$TMPDIR/kb.XXXXXX"); KRELLBOT_HOME=$H KRELLBOT_ENABLE_LIVE=0 \
        PYTHON_KEYRING_BACKEND=tests.fakes.fake_keyring.FakeKeyring \
        uv run pytest -q -s -p no:cacheprovider tests/test_m2_export_determinism.py

The test prints the run sha256 to stdout so the Steward can read it
from the ``-s`` output without grepping.
"""

from __future__ import annotations

import hashlib
import json
import socket
import time
from pathlib import Path

import pytest

from krellbot.api.jobs import canonical_receipt_bytes
from krellbot.api.serve import WorkstationServer
from krellbot.application.strategy import StrategyDraftService

PACK: dict = {
    "schema_version": 1,
    "id": "m2-export-strategy",
    "version": "1.0.0",
    "label": "M2 export determinism",
    "author": "krellbot m2-ce tests",
    "timeframe": "1h",
    "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
    "entry": ["close", "crosses_above", "sma2"],
    "exit": ["close", "crosses_below", "sma2"],
    "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}},
    "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
}

EXPECTED_RECEIPT_KEYS = {
    "data_manifest_sha256",
    "engine_version",
    "equity_curve",
    "fee_bps",
    "from",
    "metrics",
    "pack_sha256",
    "pair",
    "slippage_bps",
    "slippage_mult",
    "tf",
    "to",
    "venue",
}


# ---------------------------------------------------------------------------
# Minimal loopback HTTP client (mirrors tests/test_lane_e_unaided.py)
# ---------------------------------------------------------------------------


class _LoopbackClient:
    """Cookie-aware loopback HTTP client."""

    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port
        self._cookie: str | None = None
        self._csrf: str | None = None

    @property
    def csrf(self) -> str | None:
        return self._csrf

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        content_type: str | None = None,
        origin: str | None = None,
        include_csrf: bool = False,
    ) -> tuple[int, dict[str, str], bytes]:
        headers = [
            f"Host: {self._host}:{self._port}",
            "Connection: close",
        ]
        if body is not None:
            headers.append(f"Content-Length: {len(body)}")
            headers.append(f"Content-Type: {content_type or 'application/json'}")
        if origin is not None:
            headers.append(f"Origin: {origin}")
        if self._cookie is not None:
            headers.append(f"Cookie: krellbot_session={self._cookie}")
        if include_csrf and self._csrf is not None:
            headers.append(f"X-Krellbot-CSRF: {self._csrf}")
        request = (method + " " + path + " HTTP/1.1\r\n" + "\r\n".join(headers) + "\r\n\r\n").encode("ascii")
        if body is not None:
            request += body

        with socket.create_connection((self._host, self._port), timeout=5) as sock:
            sock.sendall(request)
            chunks = bytearray()
            while True:
                try:
                    chunk = sock.recv(65536)
                except OSError:
                    break
                if not chunk:
                    break
                chunks.extend(chunk)
        return self._parse(bytes(chunks))

    @staticmethod
    def _parse(raw: bytes) -> tuple[int, dict[str, str], bytes]:
        head, _, body = raw.partition(b"\r\n\r\n")
        lines = head.split(b"\r\n")
        status_line = lines[0].decode("ascii", errors="replace")
        code = int(status_line.split(" ", 2)[1])
        header_map: dict[str, str] = {}
        for line in lines[1:]:
            if b":" not in line:
                continue
            name, _, value = line.partition(b":")
            header_map[name.decode("ascii").strip().lower()] = value.decode("ascii").strip()
        return code, header_map, body

    def _capture_csrf(self, payload: bytes) -> None:
        try:
            parsed = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        if isinstance(parsed, dict):
            csrf = parsed.get("csrf_token")
            if isinstance(csrf, str):
                self._csrf = csrf

    def get(self, path: str) -> tuple[int, bytes]:
        code, _, body = self._request("GET", path)
        return code, body

    def post(
        self,
        path: str,
        payload: dict | None = None,
        *,
        origin: str | None = None,
        include_csrf: bool = False,
        capture: bool = False,
    ) -> tuple[int, bytes]:
        body = json.dumps(payload or {}).encode("utf-8")
        origin_value = origin if origin is not None else f"http://{self._host}:{self._port}"
        code, headers, raw = self._request(
            "POST",
            path,
            body=body,
            content_type="application/json",
            origin=origin_value,
            include_csrf=include_csrf,
        )
        set_cookie = headers.get("set-cookie", "")
        if "krellbot_session=" in set_cookie:
            for part in set_cookie.split(";"):
                if part.strip().startswith("krellbot_session="):
                    self._cookie = part.strip().split("=", 1)[1]
                    break
        if capture:
            self._capture_csrf(raw)
        return code, raw

    def bootstrap(self, token: str) -> tuple[int, bytes]:
        return self.post(
            "/api/v1/session/bootstrap",
            {"token": token},
            origin=f"http://{self._host}:{self._port}",
            capture=True,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_csv_bytes(rows: int = 400) -> bytes:
    """Render a deterministic zig-zag CSV the way the e2e harness does."""

    lines = ["ts_ms,open,high,low,close,volume"]
    for i in range(rows):
        ts = 1_700_000_000_000 + i * 3_600_000
        open_ = 100 + (i % 7)
        high = open_ + 1
        low = open_ - 1
        close = open_ + ((-1) ** i)
        lines.append(f"{ts},{open_},{high},{low},{close},0.0")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _run_one_job(
    home: Path,
    csv_path: Path,
    dataset_id: str,
    catalog: dict[str, str],
    *,
    fee_bps: int = 10,
) -> bytes:
    """Spin up a workstation on ``home``, submit one job, return the download bytes."""

    (home / "datasets.json").write_text(json.dumps(catalog, sort_keys=True), encoding="utf-8")

    server = WorkstationServer(home=home, port=0)
    server.start()
    try:
        client = _LoopbackClient(server.bound_host, server.bound_port)
        token = server.bootstrap_token
        assert isinstance(token, str) and token, token
        code, body = client.bootstrap(token)
        assert code == 200, body

        draft_service = StrategyDraftService(home=home)
        summary = draft_service.create(PACK)
        validated = draft_service.validate(summary["revision_id"])
        assert validated["state"] == "validated", validated

        code, body = client.post(
            "/api/v1/research/jobs",
            {
                "kind": "research.backtest",
                "revision_id": validated["revision_id"],
                "dataset_id": dataset_id,
                "fee_bps": fee_bps,
            },
            include_csrf=True,
        )
        assert code == 200, (code, body)
        job = json.loads(body)
        job_id = job["id"]
        assert job_id, job

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            code, body = client.get(f"/api/v1/jobs/{job_id}")
            assert code == 200, (code, body)
            snap = json.loads(body)
            if snap["state"] == "succeeded":
                break
            if snap["state"] == "failed":
                pytest.fail(f"job failed: {snap}")
            time.sleep(0.05)
        else:
            pytest.fail(f"job {job_id} did not succeed within deadline")

        code, body = client.get(f"/api/v1/jobs/{job_id}/result/download")
        assert code == 200, (code, body)
        return body
    finally:
        server.stop()


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


def test_m2_export_determinism(tmp_path: Path) -> None:
    csv_bytes = _build_csv_bytes(rows=400)
    csv_path_a = tmp_path / "a" / "dataset.csv"
    csv_path_a.parent.mkdir(parents=True, exist_ok=True)
    csv_path_a.write_bytes(csv_bytes)
    csv_path_b = tmp_path / "b" / "dataset.csv"
    csv_path_b.parent.mkdir(parents=True, exist_ok=True)
    csv_path_b.write_bytes(csv_bytes)
    csv_path_a2 = tmp_path / "a" / "dataset.csv"  # same file -> same sha

    home_a = tmp_path / "a" / "home"
    home_a.mkdir(parents=True, exist_ok=True)
    home_b = tmp_path / "b" / "home"
    home_b.mkdir(parents=True, exist_ok=True)

    catalog_a = {"m2_export_csv": str(csv_path_a)}
    catalog_b = {"m2_export_csv": str(csv_path_b)}

    body_a = _run_one_job(home_a, csv_path_a, "m2_export_csv", catalog_a, fee_bps=10)
    body_b = _run_one_job(home_b, csv_path_b, "m2_export_csv", catalog_b, fee_bps=10)
    body_a2 = _run_one_job(home_a, csv_path_a2, "m2_export_csv", catalog_a, fee_bps=10)

    sha_a = hashlib.sha256(body_a).hexdigest()
    sha_b = hashlib.sha256(body_b).hexdigest()
    sha_a2 = hashlib.sha256(body_a2).hexdigest()
    print(f"[m2-export] sha256(home A run 1)={sha_a}")
    print(f"[m2-export] sha256(home B run 1)={sha_b}")
    print(f"[m2-export] sha256(home A run 2)={sha_a2}")

    # All three runs are byte-identical.
    assert body_a == body_b == body_a2, (sha_a, sha_b, sha_a2)

    # The body parses as JSON; ``parse_constant`` raising proves there
    # are no NaN/Infinity sentinel numbers in the receipt.
    parsed = json.loads(
        body_a.decode("utf-8"),
        parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("non-finite literal in receipt")),
    )
    assert isinstance(parsed, dict)

    # Each body equals the canonical bytes of the parsed receipt.
    assert body_a == canonical_receipt_bytes(parsed)

    # The receipt keys are exactly the locked set.
    assert set(parsed.keys()) == EXPECTED_RECEIPT_KEYS, set(parsed.keys()) - EXPECTED_RECEIPT_KEYS

    # data_manifest_sha256 == sha256(csv bytes).
    expected_manifest = hashlib.sha256(csv_bytes).hexdigest()
    assert parsed["data_manifest_sha256"] == expected_manifest, (
        parsed["data_manifest_sha256"],
        expected_manifest,
    )
