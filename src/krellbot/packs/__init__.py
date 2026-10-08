"""Shipped free starter packs (read-only educational examples).

Public surface:
    * ``catalogue`` - loads the starter examples from package resources
      (``krellbot.packs.examples``) for ``GET /api/v1/packs/starters``.

The examples are ordinary valid DSL packs. They are project-authored
read-only catalogue entries: nothing here installs a pack, writes under
``KRELLBOT_HOME``, arms a strategy, or holds entitlements. A user turns a
starter into an owned editable copy by POSTing ``pack`` through the
existing draft flow (``POST /api/v1/strategies/drafts``).
"""

from __future__ import annotations

from . import catalogue

__all__ = ["catalogue"]
