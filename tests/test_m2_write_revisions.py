"""M2-WRITE: studio and editor saves create immutable revisions.

Server-side behavior under test:

  * ``edit`` with byte-identical bytes to the parent returns
    ``outcome == "unchanged"`` and leaves the parent's meta + rev files
    byte-identical.
  * ``edit`` with a different ``editor`` key than the parent still
    hashes to the parent's canonical bytes (editor is stripped before
    the hash). The outcome is ``"unchanged"`` and the parent is not
    rewritten.
  * ``edit`` with ``indicators.sma2.len`` 2 → 20 returns
    ``outcome == "created"`` and the parent's files are byte-identical
    before and after.
  * A → B (created), then ``edit(B, bytes-of-A)`` returns
    ``outcome == "existing"`` with the same revision id as A and A's
    meta file is byte-identical (still ``parent_revision_id is None``
    and still ``state == "validated"`` if A was validated first).
  * ``edit`` with a pack whose ``id`` differs from the parent's
    strategy id raises ``StrategyIdMismatch`` and writes nothing. The
    PUT route returns ``409 strategy_id_mismatch``.
  * ``POST /api/v1/research/jobs`` with both a non-empty ``pack_path``
    and a non-empty ``revision_id`` returns ``400
    ambiguous_pack_source`` and creates no job. The follow-up
    ``GET /api/v1/jobs`` lists zero jobs.
  * ``outcome`` is a ``str`` in every case.

The route tests use a real :class:`WorkstationServer` and a tiny
stdlib loopback HTTP client because ``fastapi.testclient`` is not
importable in this environment (httpx2 is missing). The same
``_LoopbackClient`` shape lives in :mod:`tests.test_lane_e_unaided`.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from krellbot.api.serve import WorkstationServer
from krellbot.application.strategy import (
    StrategyDraftService,
    StrategyIdMismatch,
)

# ---------------------------------------------------------------------------
# helpers — minimal loopback HTTP client mirroring _LoopbackClient
# ---------------------------------------------------------------------------


class _LoopbackClient:
    """Minimal cookie-aware loopback HTTP client."""

    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port
        self._cookie: str | None = None
        self._csrf: str | None = None

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        include_csrf: bool = False,
    ) -> tuple[int, dict[str, str], bytes]:
        headers = [
            f"Host: {self._host}:{self._port}",
            "Connection: close",
            f"Origin: http://{self._host}:{self._port}",
        ]
        if body is not None:
            headers.append(f"Content-Length: {len(body)}")
            headers.append("Content-Type: application/json")
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

    def request_full(
        self,
        method: str,
        path: str,
        payload: dict,
        *,
        include_csrf: bool = True,
    ) -> tuple[int, dict[str, str], bytes]:
        return self._request(
            method,
            path,
            body=json.dumps(payload).encode("utf-8"),
            include_csrf=include_csrf,
        )

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

    def bootstrap(self, token: str) -> tuple[int, bytes]:
        code, headers, raw = self._request(
            "POST",
            "/api/v1/session/bootstrap",
            body=json.dumps({"token": token}).encode("utf-8"),
        )
        set_cookie = headers.get("set-cookie", "")
        if "krellbot_session=" in set_cookie:
            for part in set_cookie.split(";"):
                if part.strip().startswith("krellbot_session="):
                    self._cookie = part.strip().split("=", 1)[1]
                    break
        try:
            parsed = json.loads(raw)
            csrf = parsed.get("csrf_token")
            if isinstance(csrf, str):
                self._csrf = csrf
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
        return code, raw

    def post_full(
        self,
        path: str,
        payload: dict,
        *,
        include_csrf: bool = True,
    ) -> tuple[int, dict[str, str], bytes]:
        return self.request_full("POST", path, payload, include_csrf=include_csrf)

    def put_full(
        self,
        path: str,
        payload: dict,
        *,
        include_csrf: bool = True,
    ) -> tuple[int, dict[str, str], bytes]:
        return self.request_full("PUT", path, payload, include_csrf=include_csrf)

    def post(
        self,
        path: str,
        payload: dict,
        *,
        include_csrf: bool = True,
    ) -> tuple[int, bytes]:
        code, _, body = self.post_full(path, payload, include_csrf=include_csrf)
        return code, body

    def get(self, path: str) -> tuple[int, bytes]:
        code, _, body = self._request("GET", path)
        return code, body


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


PACK_V1: dict = {
    "schema_version": 1,
    "id": "lane-e-strategy",
    "version": "1.0.0",
    "label": "Lane E fixture",
    "author": "krellbot m2-write tests",
    "timeframe": "1h",
    "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
    "entry": ["close", "crosses_above", "sma2"],
    "exit": ["close", "crosses_below", "sma2"],
    "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}},
    "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
}


@pytest.fixture
def fresh_home(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("KRELLBOT_HOME", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def workstation(fresh_home: Path):
    server = WorkstationServer(home=fresh_home, port=0)
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def client(workstation: WorkstationServer) -> _LoopbackClient:
    cli = _LoopbackClient(workstation.bound_host, workstation.bound_port)
    token = workstation.bootstrap_token
    assert isinstance(token, str) and token, token
    code, body = cli.bootstrap(token)
    assert code == 200, body
    return cli


def _strategy_dir(home: Path, strategy_id: str) -> Path:
    return home / "drafts" / strategy_id


def _read_bytes(path: Path) -> bytes:
    return path.read_bytes() if path.exists() else b""


def _post_create(client: _LoopbackClient, pack: dict) -> tuple[int, dict]:
    code, _h, body = client.post_full("/api/v1/strategies/drafts", {"pack": pack})
    return code, json.loads(body) if body else {}


def _post_edit(client: _LoopbackClient, revision_id: str, pack: dict) -> tuple[int, dict]:
    code, _h, body = client.put_full(f"/api/v1/strategies/drafts/{revision_id}", {"pack": pack})
    return code, json.loads(body) if body else {}


def _post_validate(client: _LoopbackClient, revision_id: str) -> tuple[int, dict]:
    code, _h, body = client.post_full(f"/api/v1/strategies/drafts/{revision_id}/validate", {})
    return code, json.loads(body) if body else {}


# ---------------------------------------------------------------------------
# 1. edit() with byte-identical canonical bytes returns "unchanged"
# ---------------------------------------------------------------------------


def test_edit_byte_identical_pack_returns_unchanged_and_keeps_parent_bytes(
    fresh_home: Path,
) -> None:
    """``edit(parent, pack)`` with the same pack returns ``outcome == 'unchanged'``,
    the parent's revision id, and the meta + rev files are byte-identical
    before and after."""

    service = StrategyDraftService(home=fresh_home)
    parent = service.create(PACK_V1)
    parent_id = parent["revision_id"]

    parent_rev_path = service.revision_path(parent_id)
    parent_meta_path = parent_rev_path.with_suffix(".meta.json")
    parent_rev_before = _read_bytes(parent_rev_path)
    parent_meta_before = _read_bytes(parent_meta_path)

    child = service.edit(parent_id, PACK_V1)

    assert child["outcome"] == "unchanged", child
    assert child["revision_id"] == parent_id, child

    parent_rev_after = _read_bytes(parent_rev_path)
    parent_meta_after = _read_bytes(parent_meta_path)
    assert parent_rev_after == parent_rev_before, (
        parent_rev_before,
        parent_rev_after,
    )
    assert parent_meta_after == parent_meta_before, (
        parent_meta_before,
        parent_meta_after,
    )
    assert isinstance(child["outcome"], str)


def test_edit_with_different_editor_key_returns_unchanged(
    fresh_home: Path,
) -> None:
    """Editor-only state is stripped before the hash, so re-saving the same
    pack with a new ``editor`` key is the same canonical bytes and returns
    ``outcome == 'unchanged'``."""

    service = StrategyDraftService(home=fresh_home)
    pack_with_editor = dict(PACK_V1)
    pack_with_editor["editor"] = {"pane": "raw"}
    parent = service.create(pack_with_editor)
    parent_id = parent["revision_id"]

    re_submitted = dict(pack_with_editor)
    re_submitted["editor"] = {"pane": "graph", "zoom": 1.5}
    child = service.edit(parent_id, re_submitted)

    assert child["outcome"] == "unchanged", child
    assert child["revision_id"] == parent_id, child


def test_edit_different_bytes_returns_created_and_preserves_parent(
    fresh_home: Path,
) -> None:
    """``edit`` with ``indicators.sma2.len`` 2 → 20 returns
    ``outcome == 'created'``, a new id whose parent is the requested parent,
    and the parent's files are byte-identical before and after."""

    service = StrategyDraftService(home=fresh_home)
    parent = service.create(PACK_V1)
    parent_id = parent["revision_id"]

    parent_rev_path = service.revision_path(parent_id)
    parent_meta_path = parent_rev_path.with_suffix(".meta.json")
    parent_rev_before = _read_bytes(parent_rev_path)
    parent_meta_before = _read_bytes(parent_meta_path)

    edited = dict(PACK_V1)
    edited["indicators"] = {
        "sma2": {"fn": "sma", "src": "close", "len": 20},
    }
    child = service.edit(parent_id, edited)

    assert child["outcome"] == "created", child
    assert child["revision_id"] != parent_id, child
    assert child["parent_revision_id"] == parent_id, child

    parent_rev_after = _read_bytes(parent_rev_path)
    parent_meta_after = _read_bytes(parent_meta_path)
    assert parent_rev_after == parent_rev_before
    assert parent_meta_after == parent_meta_before


def test_edit_to_existing_revision_returns_existing_preserves_parent_meta(
    fresh_home: Path,
) -> None:
    """A → B (created), then ``edit(B, bytes-of-A)`` returns
    ``outcome == 'existing'``, the revision id is A's, and A's meta file
    is byte-identical (still ``parent_revision_id is None`` and still
    ``state == 'validated'`` if A was validated first)."""

    service = StrategyDraftService(home=fresh_home)
    parent = service.create(PACK_V1)
    parent_id = parent["revision_id"]

    edited = dict(PACK_V1)
    edited["indicators"] = {
        "sma2": {"fn": "sma", "src": "close", "len": 20},
    }
    child = service.edit(parent_id, edited)
    child_id = child["revision_id"]
    assert child["outcome"] == "created", child

    # Validate the parent (id A) so its meta state becomes "validated".
    service.validate(parent_id)

    parent_meta_path = service.revision_path(parent_id).with_suffix(".meta.json")
    meta_before = _read_bytes(parent_meta_path)
    assert json.loads(meta_before)["state"] == "validated"

    reverted = service.edit(child_id, PACK_V1)

    assert reverted["outcome"] == "existing", reverted
    assert reverted["revision_id"] == parent_id, reverted
    # The returned summary is the stored one, including A's parent = None
    # and A's state = validated.
    assert reverted["parent_revision_id"] is None, reverted
    assert reverted["state"] == "validated", reverted

    meta_after = _read_bytes(parent_meta_path)
    assert meta_after == meta_before, (meta_before, meta_after)


def test_edit_with_strategy_id_mismatch_raises_and_writes_nothing(
    fresh_home: Path,
) -> None:
    """``edit(parent, pack)`` with a pack whose ``id`` differs from the
    parent's strategy id raises :class:`StrategyIdMismatch` and writes
    nothing on disk."""

    service = StrategyDraftService(home=fresh_home)
    parent = service.create(PACK_V1)
    parent_id = parent["revision_id"]

    drafts_root = fresh_home / "drafts"
    listing_before = sorted(p.name for p in drafts_root.rglob("*.json"))

    wrong = dict(PACK_V1)
    wrong["id"] = "different-strategy"

    with pytest.raises(StrategyIdMismatch):
        service.edit(parent_id, wrong)

    listing_after = sorted(p.name for p in drafts_root.rglob("*.json"))
    assert listing_after == listing_before, (listing_before, listing_after)


def test_edit_strategy_id_mismatch_via_route_is_409(fresh_home: Path, client: _LoopbackClient) -> None:
    """The PUT route maps :class:`StrategyIdMismatch` to HTTP 409 with the
    ``strategy_id_mismatch`` code; nothing on disk is written."""

    code, created = _post_create(client, PACK_V1)
    assert code == 200, created
    parent_id = created["revision_id"]

    drafts_root = fresh_home / "drafts"
    listing_before = sorted(p.name for p in drafts_root.rglob("*.json"))

    wrong = dict(PACK_V1)
    wrong["id"] = "different-strategy"
    code, resp = _post_edit(client, parent_id, wrong)

    assert code == 409, (code, resp)
    assert resp.get("schema_version") == "1", resp
    assert resp.get("code") == "strategy_id_mismatch", resp

    listing_after = sorted(p.name for p in drafts_root.rglob("*.json"))
    assert listing_after == listing_before, (listing_before, listing_after)


# ---------------------------------------------------------------------------
# 2. POST /api/v1/research/jobs refuses ambiguous pack source
# ---------------------------------------------------------------------------


def test_research_jobs_rejects_both_pack_path_and_revision_id(fresh_home: Path, client: _LoopbackClient) -> None:
    """A research job body that carries both a non-empty ``pack_path`` and
    a non-empty ``revision_id`` is refused with ``400
    ambiguous_pack_source``; no job is created."""

    service = StrategyDraftService(home=fresh_home)
    summary = service.create(PACK_V1)
    revision_id = summary["revision_id"]

    code, _hdrs, body = client.post_full(
        "/api/v1/research/jobs",
        {
            "revision_id": revision_id,
            "pack_path": "/some/other/path.json",
            "dataset_id": "any",
        },
    )
    body_text = body.decode("utf-8") if body else ""
    parsed = json.loads(body_text) if body_text else {}
    assert code == 400, (code, parsed)
    assert parsed.get("schema_version") == "1", parsed
    assert parsed.get("code") == "ambiguous_pack_source", parsed

    code_list, body_list = client.get("/api/v1/jobs")
    assert code_list == 200, (code_list, body_list)
    listed = json.loads(body_list) if body_list else {}
    assert listed.get("jobs") == [], listed


def test_research_jobs_does_not_create_job_on_ambiguous_source(fresh_home: Path, client: _LoopbackClient) -> None:
    """Even after the refusal, a follow-up ``GET /api/v1/jobs`` lists zero
    jobs. The contract is refuse-without-side-effect."""

    code, _hdrs, body = client.post_full(
        "/api/v1/research/jobs",
        {
            "revision_id": "deadbeef" * 8,
            "pack_path": "any.json",
        },
    )
    assert code == 400, code

    code, body = client.get("/api/v1/jobs")
    parsed = json.loads(body) if body else {}
    assert parsed.get("jobs") == [], parsed


# ---------------------------------------------------------------------------
# 3. outcome type discipline — every outcome is a str, never None / bool
# ---------------------------------------------------------------------------


def test_outcome_is_a_str_in_every_branch(fresh_home: Path) -> None:
    """Each of the three outcomes the contract enumerates is exactly a
    ``str``. No None, no bool fallback."""

    service = StrategyDraftService(home=fresh_home)
    parent = service.create(PACK_V1)
    parent_id = parent["revision_id"]

    # unchanged branch
    unchanged = service.edit(parent_id, PACK_V1)
    assert type(unchanged["outcome"]) is str, unchanged

    # created branch
    edited = dict(PACK_V1)
    edited["indicators"] = {
        "sma2": {"fn": "sma", "src": "close", "len": 20},
    }
    created = service.edit(parent_id, edited)
    assert type(created["outcome"]) is str, created

    # existing branch — revert B back to A's bytes
    existing = service.edit(created["revision_id"], PACK_V1)
    assert type(existing["outcome"]) is str, existing


# ---------------------------------------------------------------------------
# 4. write-path call-site table — every writer is grepped (read-only)
# ---------------------------------------------------------------------------


def test_writer_call_site_map_is_complete() -> None:
    """Sentinel test: every ``/api/v1/strategies/drafts`` writer is
    listed in the report's write-path table. If a new writer is added,
    the list grows; if this test does not assert against the report, it
    must at least record the canonical writers today.

    The check is a static scan over :mod:`krellbot.api.app` for the
    methods (``POST`` / ``PUT``) on the drafts tree.
    """

    import re

    app_path = Path("src/krellbot/api/app.py")
    assert app_path.is_file(), app_path
    text = app_path.read_text(encoding="utf-8")
    drafts_writer_paths = re.findall(
        r'@app\.(post|put)\(\s*"(?P<path>/api/v1/strategies/drafts[^"]*)"',
        text,
    )
    method_path_pairs = sorted({(m, p) for m, p in drafts_writer_paths})
    # The set today: POST create, PUT edit, POST validate, POST editor.
    expected = {
        ("post", "/api/v1/strategies/drafts"),
        ("put", "/api/v1/strategies/drafts/{revision_id}"),
        ("post", "/api/v1/strategies/drafts/{revision_id}/validate"),
        ("post", "/api/v1/strategies/drafts/{revision_id}/editor"),
    }
    assert set(method_path_pairs) == expected, (method_path_pairs, expected)
