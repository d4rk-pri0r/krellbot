"""Execution-layer reservations: cash, restart blocks, action codes.

This module is the single owner of three things used by
``PaperService.arm`` and ``run.tick``:

1. **Cash reservation.** Each paper-armed pack reserves
   ``starting_cash * cap / 100`` cash from the paper account pool. The
   pool is the smallest ``starting_cash`` across all paper-armed packs.
   A new arm that would push the combined reservation above the pool is
   refused before any config byte changes — the second arm sees a typed
   ``over_reserved`` code and ``revision_after == revision_before``. The
   rule is enforced through ``PaperService.arm`` so the service remains
   the single application boundary; tick does not call this code.

2. **Restart block.** ``Outbox.dispatch`` returns ``"needs_reconcile"``
   when a paper order intent was committed but the send did not
   complete; ``audit_needs_reconcile`` records the row. ``tick`` must
   not submit a new entry on the same venue while a reconcile is
   outstanding. ``should_block_for_reconcile(home)`` is the gate; it is
   called from tick immediately before the entry block. Exits and the
   paid-expiry exit path stay unaffected — the existing ``blocked``
   flag check is untouched.

3. **Action codes.** Four distinct result codes — ``pause``,
   ``cancel_opening``, ``manage_exits``, ``flatten`` — for the
   lifecycle actions tick performs against an open or about-to-open
   position. ``flatten`` additionally has a refusal code
   (``flatten_not_owned``) for the case where the journal says the
   pack does not own the qty being sold; the journal is the source of
   truth, so venue balances for external holdings are never sold.

Money is ``Decimal`` throughout. No HTTP. No secret in any log line.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from krellbot import config as kb_config
from krellbot.storage.database import OperationalStore

# ---- Result codes ---------------------------------------------------------

# Typed refusal code used by PaperService.arm when the new arm would
# push the combined paper reservation above the account pool.
CODE_OVER_RESERVED = "over_reserved"

# Distinct action codes for the four lifecycle actions tick performs
# against a position. They are deliberately short strings with no
# overlap with the paper-command v1 codes ("armed", "disarmed", …).
CODE_PAUSE = "pause"
CODE_CANCEL_OPENING = "cancel_opening"
CODE_MANAGE_EXITS = "manage_exits"
CODE_FLATTEN = "flatten"

# Refusal code for flatten: the journal says the pack does not own the
# quantity being sold. The journal projection is authoritative for
# what this pack may exit; venue balances for external holdings stay
# untouched.
CODE_FLATTEN_NOT_OWNED = "flatten_not_owned"


# ---- Cash reservation -----------------------------------------------------


def paper_account_cash(home: Path, *, new_starting_cash: Decimal | None = None) -> Decimal:
    """Return the paper account's available cash pool.

    The pool is the largest ``starting_cash`` across paper-armed packs
    (the biggest deposit defines the account). When ``new_starting_cash``
    is supplied, it joins the max so a first arm on an empty home has
    its own deposit count toward the pool; a later arm may also raise
    the pool up to its deposit. With no paper packs and no proposed
    deposit, the pool is 0.
    """
    config = kb_config.load_config(home)
    candidates: list[Decimal] = [
        Decimal(str(a.starting_cash)) for a in config.armed if a.mode == "paper" and a.starting_cash is not None
    ]
    if new_starting_cash is not None:
        candidates.append(Decimal(str(new_starting_cash)))
    if not candidates:
        return Decimal(0)
    return max(candidates)


def reserved_cash(home: Path) -> Decimal:
    """Return the total cash reserved across all paper-armed packs.

    Each paper pack reserves ``starting_cash * cap / 100``. The value is
    a ``Decimal``; an empty ledger returns 0.
    """
    config = kb_config.load_config(home)
    total = Decimal(0)
    for a in config.armed:
        if a.mode == "paper" and a.starting_cash is not None:
            total += Decimal(str(a.starting_cash)) * Decimal(str(a.cap)) / Decimal(100)
    return total


def would_over_reserve(
    home: Path,
    *,
    new_starting_cash: Decimal,
    new_cap: Decimal,
) -> bool:
    """Return True if a new arm with these parameters would exceed the pool.

    ``PaperService.arm`` calls this before any byte change to the
    on-disk config; a True result becomes the typed ``over_reserved``
    refusal with ``revision_after == revision_before``.
    """
    new_reservation = Decimal(str(new_starting_cash)) * Decimal(str(new_cap)) / Decimal(100)
    pool = paper_account_cash(home, new_starting_cash=new_starting_cash)
    return reserved_cash(home) + new_reservation > pool


# ---- Restart block --------------------------------------------------------


def should_block_for_reconcile(home: Path) -> bool:
    """Return True if any ``needs_reconcile`` ledger row exists.

    The Outbox audits a ``needs_reconcile`` row when a paper send was
    committed but the venue call did not complete (return state
    ``"needs_reconcile"``). Until an operator reconciles from the
    venue snapshot, tick must not submit a new entry on the same
    venue. The block affects entries only — exits, ensure-stop, and
    paid-expiry exits continue to run. The check reads the store, not
    the legacy journal.
    """
    store = OperationalStore(home / "ops.sqlite")
    for _row_id, kind, _payload in store.read_ledger():
        if kind == "needs_reconcile":
            return True
    return False


# ---- Flatten ownership rule -----------------------------------------------


def _journal_owned_qty(home: Path, *, pack_id: str, pair: str) -> Decimal:
    """Return the journal projection of owned qty for ``pack_id``/``pair``.

    Reads the legacy journal's ``kind=tick`` records and sums
    ``entry_qty - exit_qty - stop_qty``. The reconcile module already
    exposes this projection; we import the implementation locally to
    avoid a cycle.
    """
    from krellbot.run.reconcile import _cumulative_owned_from_journal

    return _cumulative_owned_from_journal(home, pack_id=pack_id, pair=pair)


def flatten_result(home: Path, *, pack_id: str, pair: str, qty: Decimal) -> str:
    """Return the typed result of a flatten of ``qty`` for ``pack_id``.

    Returns ``CODE_FLATTEN`` when the journal projection of owned qty
    covers ``qty``. Returns ``CODE_FLATTEN_NOT_OWNED`` when the journal
    says the pack owns less than ``qty`` — the venue's free balance for
    the base asset may be larger (external holdings) and must not be
    sold. ``qty`` of zero is treated as not-owned to make the test for
    "do not sell external inventory" explicit.
    """
    if qty <= Decimal(0):
        return CODE_FLATTEN_NOT_OWNED
    owned = _journal_owned_qty(home, pack_id=pack_id, pair=pair)
    if owned >= Decimal(str(qty)):
        return CODE_FLATTEN
    return CODE_FLATTEN_NOT_OWNED
