"""Loader for the shipped free starter pack catalogue.

``krellbot.packs.examples`` is a package-data directory (the same
pattern ``krellbot.pack`` uses for ``schema.json``). It holds one
starter pack JSON per file plus a ``catalogue.json`` manifest that fixes
the order and the human-facing metadata of the catalogue. The loader is
read-only: it never writes under ``KRELLBOT_HOME`` and it never
validates user drafts.

Contract (frozen):

    GET /api/v1/packs/starters ->
        {"schema_version": "1",
         "catalogue_version": "1",
         "examples": [{"id", "label", "description", "pack"}, ...]}

The examples are ordinary valid DSL packs the existing validator
accepts. ``list_examples`` is the whole surface; there is no install,
validate-user-draft, arm, start, overwrite, or edit verb here.
"""

from __future__ import annotations

import json
from importlib import resources

SCHEMA_VERSION = "1"
CATALOGUE_VERSION = "1"

_EXAMPLES_PACKAGE = "krellbot.packs.examples"
_MANIFEST_NAME = "catalogue.json"


class StarterCatalogueError(RuntimeError):
    """The shipped catalogue is unreadable or inconsistent.

    Raised only when the package data itself is broken (missing
    manifest, missing example file, invalid JSON, or a pack whose ``id``
    does not match its manifest entry). A shipped catalogue that raises
    is a build bug, not a user state problem; the API route maps this to
    500 rather than serving a partial list.
    """


def _read_resource(name: str) -> str:
    return (
        resources.files(_EXAMPLES_PACKAGE)
        .joinpath(name)
        .read_text(encoding="utf-8")
    )


def _load_manifest() -> list[dict]:
    doc = json.loads(_read_resource(_MANIFEST_NAME))
    if not isinstance(doc, dict):
        raise StarterCatalogueError("catalogue manifest must be a JSON object")
    entries = doc.get("examples")
    if not isinstance(entries, list) or not entries:
        raise StarterCatalogueError("catalogue manifest must list at least one example")
    return entries


def list_examples() -> list[dict]:
    """Return the starter examples, manifest order, as fresh dicts.

    Each row is ``{"id", "label", "description", "pack"}``. The pack is
    a full ordinary DSL pack dict. Every call re-reads the package
    resources and returns fresh objects, so a caller can never mutate
    catalogue state through a returned row.
    """

    out: list[dict] = []
    for entry in _load_manifest():
        example_id = str(entry.get("id") or "")
        filename = str(entry.get("file") or "")
        if not example_id or not filename:
            raise StarterCatalogueError("catalogue manifest entry missing id or file")
        pack = json.loads(_read_resource(filename))
        if not isinstance(pack, dict) or pack.get("id") != example_id:
            raise StarterCatalogueError(
                f"starter example {filename!r} must be a JSON object with id {example_id!r}"
            )
        out.append(
            {
                "id": example_id,
                "label": str(entry.get("label") or ""),
                "description": str(entry.get("description") or ""),
                "pack": pack,
            }
        )
    return out


def catalogue_document() -> dict:
    """Return the frozen API body for ``GET /api/v1/packs/starters``."""

    return {
        "schema_version": SCHEMA_VERSION,
        "catalogue_version": CATALOGUE_VERSION,
        "examples": list_examples(),
    }
