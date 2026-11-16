"""Live preflight — sandbox-mode dry-run that never places an order.

The workstation runs ``live.preflight`` to confirm it can address a
candidate live deployment against an injectable venue transport seam
without ever sending a real order. The helper refuses *before* any
``transport.send`` call when the caller-provided ``account_id`` does
not match the transport's account, when ``revision_id`` is missing, or
when ``mode`` is not ``"sandbox"``. The wrong-mode refusal is typed as
``stored_mode_not_sandbox`` only when the stored deployment mode is
``live``; an omitted ``mode`` never overrides a stored live deployment
into sandbox.

On a successful sandbox path the helper checks trade-only permissions
and then reads balances. It never calls ``transport.send``. Production
wiring builds a venue-backed adapter over the injectable HTTP transport
(the same seam keys onboarding and web live-arm probes use). Tests
substitute either a spy ``LiveTransport`` or a fake venue HTTP transport
(``FakeKrakenTransport`` / ``FakeCoinbaseTransport``) under that adapter.

Contract:

  * ``evaluate(...)`` always returns a ``PreflightResult``; refusal
    codes never depend on order of input validation beyond what is
    documented below.
  * On any refusal ``transport.send`` is not called.
  * On success the result has ``ok=True`` and ``effect="unchanged"``;
    no state is mutated, no order is sent.
  * The stored-mode check is symmetric with ``stored_mode_not_paper``:
    a stored live deployment is preserved by any non-sandbox request.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

SCHEMA_VERSION = "1"

# Stable refusal codes for the live-preflight closed set.
CODE_OK = "ok"
CODE_ACCOUNT_MISMATCH = "account_mismatch"
CODE_REVISION_ID_MISSING = "revision_id_missing"
CODE_MODE_NOT_SANDBOX = "mode_not_sandbox"
CODE_STORED_MODE_NOT_SANDBOX = "stored_mode_not_sandbox"
CODE_VENUE_UNREACHABLE = "venue_unreachable"
CODE_PREFLIGHT_BLOCKED = "preflight_blocked"

MODE_SANDBOX = "sandbox"

SUPPORTED_PREFLIGHT_VENUES = frozenset({"kraken", "coinbase"})


class PreflightTransportError(Exception):
    """Typed transport failure mapped to a preflight refusal code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class PreflightUnreachableError(PreflightTransportError):
    def __init__(self, message: str = "venue unreachable") -> None:
        super().__init__(CODE_VENUE_UNREACHABLE, message)


class PreflightBlockedError(PreflightTransportError):
    def __init__(self, message: str = "preflight blocked") -> None:
        super().__init__(CODE_PREFLIGHT_BLOCKED, message)


@dataclass(frozen=True)
class PreflightPermissions:
    """Secret-free permission snapshot returned on a successful preflight."""

    can_trade: bool
    can_withdraw: bool

    def to_dict(self) -> dict[str, bool]:
        return {"can_trade": self.can_trade, "can_withdraw": self.can_withdraw}


class LiveTransport(Protocol):
    """The minimum surface the helper requires from any transport.

    ``send`` is the only call that could mutate venue state. The helper
    never invokes it; tests substitute a spy to assert the same.
    ``permissions`` and ``balances`` are read-only calls the helper
    makes on the sandbox success path.
    """

    account: str

    def send(self, *args: Any, **kwargs: Any) -> Any: ...

    def permissions(self) -> PreflightPermissions: ...

    def balances(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class PreflightResult:
    """Versioned preflight result.

    ``schema_version`` is the literal ``"1"``. ``effect`` is one of
    ``"unchanged"`` (success — preflight ran, no state mutation) or
    ``"refused"`` (one of the refusal codes fired). On success the
    ``balances`` and ``permissions`` fields carry the read-only status.
    """

    schema_version: str
    code: str
    ok: bool
    message: str
    effect: str
    account_id: str | None = None
    revision_id: str | None = None
    stored_mode: str | None = None
    balances: dict[str, Any] | None = None
    permissions: dict[str, bool] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "schema_version": self.schema_version,
            "code": self.code,
            "ok": self.ok,
            "message": self.message,
            "effect": self.effect,
        }
        if self.account_id is not None:
            out["account_id"] = self.account_id
        if self.revision_id is not None:
            out["revision_id"] = self.revision_id
        if self.stored_mode is not None:
            out["stored_mode"] = self.stored_mode
        if self.balances is not None:
            out["balances"] = self.balances
        if self.permissions is not None:
            out["permissions"] = self.permissions
        return out


def evaluate(
    *,
    account_id: str,
    revision_id: str | None,
    mode: str | None,
    transport: LiveTransport,
    stored_mode: str | None = None,
) -> PreflightResult:
    """Run a sandbox-only live preflight against ``transport``.

    Validation order is fixed so codes are stable for callers:

      1. ``revision_id`` present and non-empty — else
         ``CODE_REVISION_ID_MISSING``.
      2. ``account_id == transport.account`` — else
         ``CODE_ACCOUNT_MISMATCH``.
      3. ``mode == "sandbox"`` — else, when ``stored_mode == "live"``,
         ``CODE_STORED_MODE_NOT_SANDBOX``; otherwise
         ``CODE_MODE_NOT_SANDBOX``.
      4. ``transport.permissions()`` must be trade-only — else
         ``CODE_PREFLIGHT_BLOCKED`` (or ``CODE_VENUE_UNREACHABLE``).
      5. ``transport.balances()`` — else ``CODE_VENUE_UNREACHABLE``.

    On success the helper returns balances and permissions. It never
    calls ``transport.send``.
    """

    if not revision_id:
        return PreflightResult(
            schema_version=SCHEMA_VERSION,
            code=CODE_REVISION_ID_MISSING,
            ok=False,
            message="revision_id is required",
            effect="refused",
            account_id=account_id,
            revision_id=revision_id,
            stored_mode=stored_mode,
        )

    if account_id != transport.account:
        return PreflightResult(
            schema_version=SCHEMA_VERSION,
            code=CODE_ACCOUNT_MISMATCH,
            ok=False,
            message=f"account_id {account_id!r} does not match transport.account {transport.account!r}",
            effect="refused",
            account_id=account_id,
            revision_id=revision_id,
            stored_mode=stored_mode,
        )

    if mode != MODE_SANDBOX:
        if stored_mode == "live":
            return PreflightResult(
                schema_version=SCHEMA_VERSION,
                code=CODE_STORED_MODE_NOT_SANDBOX,
                ok=False,
                message="stored deployment is live; live.preflight requires mode=sandbox",
                effect="refused",
                account_id=account_id,
                revision_id=revision_id,
                stored_mode=stored_mode,
            )
        return PreflightResult(
            schema_version=SCHEMA_VERSION,
            code=CODE_MODE_NOT_SANDBOX,
            ok=False,
            message=f"mode {mode!r} is not sandbox",
            effect="refused",
            account_id=account_id,
            revision_id=revision_id,
            stored_mode=stored_mode,
        )

    try:
        perms = transport.permissions()
    except PreflightTransportError as exc:
        return PreflightResult(
            schema_version=SCHEMA_VERSION,
            code=exc.code,
            ok=False,
            message=exc.message,
            effect="refused",
            account_id=account_id,
            revision_id=revision_id,
            stored_mode=stored_mode,
        )

    if not perms.can_trade or perms.can_withdraw:
        return PreflightResult(
            schema_version=SCHEMA_VERSION,
            code=CODE_PREFLIGHT_BLOCKED,
            ok=False,
            message="key is not trade-only; live preflight refused",
            effect="refused",
            account_id=account_id,
            revision_id=revision_id,
            stored_mode=stored_mode,
            permissions=perms.to_dict(),
        )

    try:
        balances = transport.balances()
    except PreflightTransportError as exc:
        return PreflightResult(
            schema_version=SCHEMA_VERSION,
            code=exc.code,
            ok=False,
            message=exc.message,
            effect="refused",
            account_id=account_id,
            revision_id=revision_id,
            stored_mode=stored_mode,
            permissions=perms.to_dict(),
        )

    return PreflightResult(
        schema_version=SCHEMA_VERSION,
        code=CODE_OK,
        ok=True,
        message="sandbox preflight ok",
        effect="unchanged",
        account_id=account_id,
        revision_id=revision_id,
        stored_mode=stored_mode,
        balances=balances,
        permissions=perms.to_dict(),
    )


@dataclass(frozen=True)
class SandboxTransport:
    """Legacy stub transport. Not used as the production default.

    Kept for unit spies that still want a deterministic in-memory
    balances map. Production wiring uses
    ``build_venue_preflight_transport`` instead.
    """

    account: str
    _balances: dict[str, Any] = field(default_factory=lambda: {"USD": 0.0})
    _can_trade: bool = True
    _can_withdraw: bool = False

    def send(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover - never called from preflight
        raise RuntimeError("SandboxTransport.send is never invoked by live.preflight")

    def permissions(self) -> PreflightPermissions:
        return PreflightPermissions(can_trade=self._can_trade, can_withdraw=self._can_withdraw)

    def balances(self) -> dict[str, Any]:
        return dict(self._balances)


@dataclass
class VenueBackedPreflightTransport:
    """Read-only preflight adapter over a live venue client.

    ``account`` is the venue id (e.g. ``"kraken"``). ``send`` is never
    called by ``evaluate``; calling it raises. Permissions and balances
    are read through the venue's ``check_key`` / ``snapshot`` surface,
    which itself uses the injectable HTTP transport.
    """

    account: str
    _venue: Any

    def send(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("VenueBackedPreflightTransport.send is never invoked by live.preflight")

    def permissions(self) -> PreflightPermissions:
        from krellbot.venues.base import WithdrawCapableError

        try:
            perms = self._venue.check_key()
        except WithdrawCapableError:
            raise PreflightBlockedError("key permissions refuse live preflight") from None
        except (OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError):
            raise PreflightUnreachableError("venue unreachable; cannot verify permissions") from None
        return PreflightPermissions(can_trade=bool(perms.can_trade), can_withdraw=bool(perms.can_withdraw))

    def balances(self) -> dict[str, Any]:
        try:
            truth = self._venue.snapshot()
        except (OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError):
            raise PreflightUnreachableError("venue unreachable; cannot read balances") from None
        out: dict[str, Any] = {}
        for bal in getattr(truth, "balances", ()) or ():
            asset = getattr(bal, "asset", None)
            free = getattr(bal, "free", None)
            if not isinstance(asset, str) or not asset or free is None:
                continue
            out[asset] = format(free, "f")
        return out


@dataclass
class _BlockedPreflightTransport:
    """Transport that refuses permissions when no usable key is present."""

    account: str
    message: str = "no key stored for venue"

    def send(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("_BlockedPreflightTransport.send is never invoked by live.preflight")

    def permissions(self) -> PreflightPermissions:
        raise PreflightBlockedError(self.message)

    def balances(self) -> dict[str, Any]:
        raise PreflightUnreachableError("venue unreachable; cannot read balances")


def build_venue_preflight_transport(
    *,
    venue: str,
    http_transport: Any | None = None,
) -> LiveTransport:
    """Build the production preflight transport for ``venue``.

    Uses stored credentials and an injectable HTTP transport (or the
    venue's real ``HttpTransport`` when none is provided). Never returns
    ``SandboxTransport``. Missing or unreadable keys yield a blocked
    transport that refuses on the permissions check.
    """
    if venue not in SUPPORTED_PREFLIGHT_VENUES:
        return _BlockedPreflightTransport(
            account=venue,
            message=f"unsupported preflight venue {venue!r}",
        )

    from krellbot import secrets as kb_secrets

    try:
        api_key, api_secret = kb_secrets.get(venue)
    except (FileNotFoundError, ValueError, PermissionError):
        return _BlockedPreflightTransport(account=venue, message="no key stored for venue")

    if venue == "kraken":
        from krellbot.venues.kraken import HttpTransport, KrakenVenue

        venue_obj = KrakenVenue(
            api_key,
            api_secret,
            http_transport or HttpTransport(),
            min_interval_ms=0,
        )
        return VenueBackedPreflightTransport(account=venue, _venue=venue_obj)

    if venue == "coinbase":
        from krellbot.venues.coinbase import CoinbaseVenue, HttpTransport

        venue_obj = CoinbaseVenue(
            api_key,
            api_secret,
            http_transport or HttpTransport(),
        )
        return VenueBackedPreflightTransport(account=venue, _venue=venue_obj)

    return _BlockedPreflightTransport(
        account=venue,
        message=f"unsupported preflight venue {venue!r}",
    )
