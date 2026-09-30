"""Strategy drafts (NS08a) — the application-service boundary for v1 strategy revision ids.

Drafts live under the explicit ``home``. They are NOT the armed-pack
config and they are NOT a file already deployed under ``packs/``.

A v1 revision has:

  * ``strategy_id`` — stable id from the pack (``pack["id"]``).
  * ``revision_id`` — sha256 of canonical supported v1 JSON (sorted
    keys, ``(",", ":")`` separators, UTF-8). Editor-only keys named
    ``editor`` are stripped before the hash and before the stored
    bytes.
  * ``parent_revision_id`` — ``None`` for the initial revision of a
    strategy, otherwise the revision id of the one this edit descended
    from.
  * ``state`` — one of ``draft``, ``validated``, ``deployed``,
    ``archived``. Legacy packs stay in ``draft`` even after validate
    runs, because they are not runnable.

The service stores each revision on disk under
``<home>/drafts/<strategy_id>/<revision_id>.json`` plus a sibling
``<home>/drafts/<strategy_id>/<revision_id>.meta.json`` holding the
metadata (state, parent, created_at, runnable).

Storage layout:

  * The drafts tree is created on demand with the same per-parent mode
    the rest of the home layout uses.
  * The store writes bytes atomically through ``krellbot.paths`` so a
    crash mid-write never leaves a half-written revision file behind.
  * An existing revision is not rewritten by a re-POST of the same
    canonical JSON: the service returns the existing record so the
    ``revision_id`` is stable across repeated writes of identical
    bytes.

The service is the boundary. The versioned API route posts through
it; the paper command service consults it when ``paper.arm`` is
addressed by ``revision_id`` (without rewriting the draft file).
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path

from krellbot import paths as kb_paths
from krellbot.pack import lint as kb_pack_lint

SCHEMA_VERSION = "1"

STATE_DRAFT = "draft"
STATE_VALIDATED = "validated"
STATE_DEPLOYED = "deployed"
STATE_ARCHIVED = "archived"

_RUNNABLE_STATES = frozenset({STATE_VALIDATED, STATE_DEPLOYED})

_IS_WINDOWS = sys.platform == "win32"


def _canonical_bytes(pack: dict) -> bytes:
    """Render the canonical supported v1 JSON for ``pack``.

    ``editor`` keys are stripped because they are layout state, not
    pack semantics. The output is UTF-8 JSON with sorted keys and
    ``(",", ":")`` separators.
    """

    cleaned = {k: v for k, v in pack.items() if k != "editor"}
    return json.dumps(cleaned, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _revision_id(pack: dict) -> str:
    return hashlib.sha256(_canonical_bytes(pack)).hexdigest()


def _now_iso(clock: Callable[[], float] | None = None) -> str:
    from datetime import datetime, timezone

    if clock is None:
        now = datetime.now(timezone.utc)
    else:
        now = datetime.fromtimestamp(float(clock()), tz=timezone.utc)
    return now.replace(microsecond=0).isoformat().replace("+00:00", "Z")


class RevisionNotFound(FileNotFoundError):
    """The revision id is not in the draft store."""


class DraftNotRunnable(ValueError):
    """The revision exists but cannot be armed (state != validated)."""

    def __init__(self, revision_id: str, *, reason: str) -> None:
        super().__init__(f"draft {revision_id} is not runnable: {reason}")
        self.revision_id = revision_id
        self.reason = reason


class StrategyIdMismatch(ValueError):
    """The pack's strategy ``id`` differs from the parent revision's strategy.

    The PUT edit route catches this before the generic ``ValueError``
    branch and maps it to HTTP 409 ``strategy_id_mismatch``. Catching
    it specifically preserves the generic ``ValueError`` → 400 mapping
    for the rest of the put-edit errors (empty id, etc.).
    """

    def __init__(self, parent_revision_id: str, parent_strategy_id: str, pack_strategy_id: str) -> None:
        super().__init__(
            f"pack id {pack_strategy_id!r} does not match parent strategy {parent_strategy_id!r}",
        )
        self.parent_revision_id = parent_revision_id
        self.parent_strategy_id = parent_strategy_id
        self.pack_strategy_id = pack_strategy_id


class StrategyDraftService:
    """Application-layer boundary for strategy drafts."""

    def __init__(self, home: Path, *, clock: Callable[[], float] | None = None) -> None:
        self._home = Path(home)
        self._clock = clock

    @property
    def home(self) -> Path:
        return self._home

    # ---- layout --------------------------------------------------------

    def _drafts_root(self) -> Path:
        return self._home / "drafts"

    def _strategy_dir(self, strategy_id: str) -> Path:
        return self._drafts_root() / strategy_id

    def _ensure_strategy_dir(self, strategy_id: str) -> Path:
        path = self._strategy_dir(strategy_id)
        path.mkdir(parents=True, exist_ok=True)
        if not _IS_WINDOWS:
            os.chmod(path, 0o700)
        return path

    def revision_path(self, revision_id: str) -> Path:
        """Return the on-disk path of the stored revision JSON.

        The store does not keep a separate (strategy_id, revision_id)
        index: it walks the per-strategy directories. With per-strategy
        cardinality bounded by editing reality, the walk is cheap and
        avoids a stale-index bug.
        """

        drafts = self._drafts_root()
        if not drafts.exists():
            raise RevisionNotFound(revision_id)
        for strategy_dir in drafts.iterdir():
            if not strategy_dir.is_dir():
                continue
            candidate = strategy_dir / f"{revision_id}.json"
            if candidate.exists():
                return candidate
        raise RevisionNotFound(revision_id)

    def _strategy_for_revision(self, revision_id: str) -> str | None:
        drafts = self._drafts_root()
        if not drafts.exists():
            return None
        for strategy_dir in drafts.iterdir():
            if not strategy_dir.is_dir():
                continue
            if (strategy_dir / f"{revision_id}.json").exists():
                return strategy_dir.name
            if (strategy_dir / f"{revision_id}.meta.json").exists():
                return strategy_dir.name
        return None

    def _meta_path(self, strategy_id: str, revision_id: str) -> Path:
        return self._strategy_dir(strategy_id) / f"{revision_id}.meta.json"

    def _rev_path(self, strategy_id: str, revision_id: str) -> Path:
        return self._strategy_dir(strategy_id) / f"{revision_id}.json"

    def _write_meta(self, strategy_id: str, revision_id: str, meta: dict) -> None:
        path = self._meta_path(strategy_id, revision_id)
        kb_paths.atomic_write(path, (json.dumps(meta, sort_keys=True) + "\n").encode("utf-8"))

    def _write_rev(self, strategy_id: str, revision_id: str, canonical: bytes) -> None:
        path = self._rev_path(strategy_id, revision_id)
        kb_paths.atomic_write(path, canonical)

    def _read_meta(self, strategy_id: str, revision_id: str) -> dict:
        return json.loads(self._meta_path(strategy_id, revision_id).read_text(encoding="utf-8"))

    def _read_pack(self, strategy_id: str, revision_id: str) -> dict:
        return json.loads(self._rev_path(strategy_id, revision_id).read_text(encoding="utf-8"))

    # ---- create --------------------------------------------------------

    def create(self, pack: dict) -> dict:
        """Store an initial draft for the pack's strategy id.

        Returns a summary dict with ``schema_version``, ``strategy_id``,
        ``revision_id``, ``parent_revision_id``, ``state``,
        ``runnable``, ``created_at``, ``errors``, ``outcome``, and
        ``pack``. ``outcome`` is the literal ``"created"`` for a fresh
        write and ``"existing"`` for a repeated POST of identical
        canonical bytes.
        """

        strategy_id = str(pack.get("id") or "")
        if not strategy_id:
            raise ValueError("pack must have a non-empty id")
        rev_id = _revision_id(pack)
        self._ensure_strategy_dir(strategy_id)

        canonical = _canonical_bytes(pack)

        # Same canonical JSON → same revision id; return the existing
        # record so repeated POSTs are idempotent and the on-disk file
        # is not rewritten.
        if self._rev_path(strategy_id, rev_id).exists():
            summary = self._summary(strategy_id, rev_id)
            summary["outcome"] = "existing"
            return summary

        self._write_rev(strategy_id, rev_id, canonical)
        meta = {
            "schema_version": SCHEMA_VERSION,
            "strategy_id": strategy_id,
            "revision_id": rev_id,
            "parent_revision_id": None,
            "state": STATE_DRAFT,
            "runnable": False,
            "created_at": _now_iso(self._clock),
            "errors": [],
        }
        self._write_meta(strategy_id, rev_id, meta)
        summary = self._summary(strategy_id, rev_id)
        summary["outcome"] = "created"
        return summary

    # ---- edit ----------------------------------------------------------

    def edit(self, parent_revision_id: str, pack: dict) -> dict:
        """Create a new draft revision descending from ``parent_revision_id``.

        Returns the stored summary plus an ``outcome`` literal:

          * ``"unchanged"`` — canonical bytes equal the parent's.
            Nothing on disk changes; the returned ``revision_id`` is
            the parent's.
          * ``"existing"`` — canonical bytes equal a *different*
            revision already on disk. That revision is returned as
            stored; its meta (including ``parent_revision_id`` and
            ``state``) is not rewritten.
          * ``"created"`` — a new revision was written. Its meta
            ``parent_revision_id`` is the requested parent.
        """

        if not self.exists(parent_revision_id):
            raise RevisionNotFound(parent_revision_id)
        strategy_id = self._strategy_for_revision(parent_revision_id)
        assert strategy_id is not None
        pack_strategy_id = str(pack.get("id") or "")
        if not pack_strategy_id:
            raise ValueError("pack must have a non-empty id")
        if pack_strategy_id != strategy_id:
            raise StrategyIdMismatch(parent_revision_id, strategy_id, pack_strategy_id)

        rev_id = _revision_id(pack)
        self._ensure_strategy_dir(strategy_id)
        canonical = _canonical_bytes(pack)
        parent_canonical = self.canonical_bytes(parent_revision_id)

        # Branch 1 — unchanged save. Canonical bytes equal the parent.
        # The on-disk meta + rev files for the parent must be
        # byte-identical before and after; nothing is written.
        if canonical == parent_canonical:
            summary = self._summary(strategy_id, parent_revision_id)
            summary["outcome"] = "unchanged"
            return summary

        rev_path = self._rev_path(strategy_id, rev_id)
        if rev_path.exists():
            # Branch 2 — existing. The canonical bytes already live on
            # disk under a different revision id. Return it as stored;
            # do NOT rewrite its meta (the immutable ``parent_revision_id``
            # and the validated ``state`` must be preserved).
            summary = self._summary(strategy_id, rev_id)
            summary["outcome"] = "existing"
            return summary

        # Branch 3 — created. New revision file. Meta parent_revision_id
        # is the requested parent.
        self._write_rev(strategy_id, rev_id, canonical)
        meta = {
            "schema_version": SCHEMA_VERSION,
            "strategy_id": pack_strategy_id,
            "revision_id": rev_id,
            "parent_revision_id": parent_revision_id,
            "state": STATE_DRAFT,
            "runnable": False,
            "created_at": _now_iso(self._clock),
            "errors": [],
        }
        self._write_meta(strategy_id, rev_id, meta)
        summary = self._summary(strategy_id, rev_id)
        summary["outcome"] = "created"
        return summary

    # ---- validate ------------------------------------------------------

    def validate(self, revision_id: str) -> dict:
        """Run ``krellbot.pack.lint.check`` against this revision's pack.

        A clean non-legacy pack becomes ``state == validated``,
        ``runnable is True``. Errors carry the lint-provided field
        path. A legacy pack stays at ``state == draft`` and
        ``runnable is False`` — it can be stored but never armed.
        """

        if not self.exists(revision_id):
            raise RevisionNotFound(revision_id)
        strategy_id = self._strategy_for_revision(revision_id)
        assert strategy_id is not None

        pack = self._read_pack(strategy_id, revision_id)
        legacy = kb_pack_lint.is_legacy(pack)
        if legacy:
            errors: list[dict] = []
            state = STATE_DRAFT
            runnable = False
        else:
            errors = [dict(e) for e in kb_pack_lint.check(pack)]
            if errors:
                state = STATE_DRAFT
                runnable = False
            else:
                state = STATE_VALIDATED
                runnable = True

        meta = self._read_meta(strategy_id, revision_id)
        meta["state"] = state
        meta["runnable"] = runnable
        meta["errors"] = errors
        self._write_meta(strategy_id, revision_id, meta)
        return self._summary(strategy_id, revision_id)

    # ---- mark-deployed -------------------------------------------------

    def mark_deployed(self, revision_id: str) -> None:
        """Flip this revision's state to ``deployed``.

        Called by the paper service after a validated draft is armed.
        ``deployed`` revisions can still be ``edited`` into new
        drafts; the editor never mutates the deployed bytes.
        """

        if not self.exists(revision_id):
            raise RevisionNotFound(revision_id)
        strategy_id = self._strategy_for_revision(revision_id)
        assert strategy_id is not None
        meta = self._read_meta(strategy_id, revision_id)
        if meta.get("state") not in (STATE_VALIDATED, STATE_DEPLOYED):
            raise DraftNotRunnable(revision_id, reason="state is not validated or deployed")
        meta["state"] = STATE_DEPLOYED
        meta["runnable"] = True
        self._write_meta(strategy_id, revision_id, meta)

    # ---- accessors -----------------------------------------------------

    def exists(self, revision_id: str) -> bool:
        if not self._drafts_root().exists():
            return False
        try:
            self.revision_path(revision_id)
        except RevisionNotFound:
            return False
        return True

    def get(self, revision_id: str) -> dict | None:
        """Return ``{meta, pack}`` for ``revision_id`` or ``None``."""

        if not self.exists(revision_id):
            return None
        strategy_id = self._strategy_for_revision(revision_id)
        assert strategy_id is not None
        return self._summary(strategy_id, revision_id)

    def is_runnable(self, revision_id: str) -> bool:
        """True iff the revision can be armed."""

        snap = self.get(revision_id)
        if snap is None:
            return False
        return bool(snap.get("runnable"))

    def canonical_bytes(self, revision_id: str) -> bytes:
        """Return the on-disk canonical bytes of ``revision_id``."""

        return self.revision_path(revision_id).read_bytes()

    def pack_for_arm(self, revision_id: str) -> tuple[Path, dict]:
        """Return ``(path, pack)`` the paper service should arm.

        The path is the on-disk draft file. The paper service reads
        it without mutating it. Raises ``DraftNotRunnable`` if the
        revision is not validated.
        """

        snap = self.get(revision_id)
        if snap is None:
            raise RevisionNotFound(revision_id)
        if not snap.get("runnable"):
            raise DraftNotRunnable(revision_id, reason="state is not validated")
        return self.revision_path(revision_id), snap["pack"]

    # ---- internal ------------------------------------------------------

    def save_editor(self, revision_id: str, editor: dict) -> dict:
        """Store canvas layout on the revision meta. Pack bytes stay put."""

        if not isinstance(editor, dict):
            raise TypeError("editor must be a mapping")
        if not self.exists(revision_id):
            raise RevisionNotFound(revision_id)
        strategy_id = self._strategy_for_revision(revision_id)
        assert strategy_id is not None
        before = self.canonical_bytes(revision_id)
        meta = self._read_meta(strategy_id, revision_id)
        meta["editor"] = editor
        self._write_meta(strategy_id, revision_id, meta)
        after = self.canonical_bytes(revision_id)
        if after != before:
            raise RuntimeError("editor save rewrote the pack")
        return self._summary(strategy_id, revision_id)

    def _summary(self, strategy_id: str, revision_id: str) -> dict:
        meta = self._read_meta(strategy_id, revision_id)
        pack = self._read_pack(strategy_id, revision_id)
        summary = {
            "schema_version": SCHEMA_VERSION,
            "strategy_id": str(meta.get("strategy_id", strategy_id)),
            "revision_id": revision_id,
            "parent_revision_id": meta.get("parent_revision_id"),
            "state": str(meta.get("state", STATE_DRAFT)),
            "runnable": bool(meta.get("runnable", False)),
            "created_at": str(meta.get("created_at", "")),
            "errors": list(meta.get("errors") or []),
            "pack": pack,
        }
        if "editor" in meta:
            summary["editor"] = meta["editor"]
        return summary
