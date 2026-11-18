"""Shipped free starter packs and built-in trading-mode packs.

Public surface:
    * ``catalogue`` - loads the starter examples from package resources
      (``krellbot.packs.examples``) for ``GET /api/v1/packs/starters``.
    * ``mode_packs`` - loads built-in DCA/grid/rebalance packs from
      ``krellbot.packs.modes`` (read-only package data).
    * ``creator_signed`` - signed third-party creator pack envelope +
      rev-share verify-before-install (docs/creator-packs.md).
    * ``rev_share_ledger`` - local owed-share ledger + fake settlement
      transport for paid creator install/redeem (docs/creator-packs.md).

The examples are ordinary valid DSL packs. They are project-authored
read-only catalogue entries: nothing here installs a pack, writes under
``KRELLBOT_HOME``, arms a strategy, or holds entitlements. A user turns a
starter into an owned editable copy by POSTing ``pack`` through the
existing draft flow (``POST /api/v1/strategies/drafts``).
"""

from __future__ import annotations

from . import catalogue, creator_signed, mode_packs, rev_share_ledger

__all__ = ["catalogue", "creator_signed", "mode_packs", "rev_share_ledger"]
