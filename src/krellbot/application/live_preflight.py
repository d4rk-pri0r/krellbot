"""Live preflight — sandbox-only dry-run that never places an order.

The workstation runs ``live.preflight`` to confirm it can address a
candidate live deployment against a fake transport without ever sending
a real order. The helper refuses *before* any ``transport.send`` call
when the caller-provided ``account_id`` does not match the transport's
account, when ``revision_id`` is missing, or when ``mode`` is not
``"sandbox"``. The wrong-mode refusal is typed as
``stored_mode_not_sandbox`` only when the stored deployment mode is
``live``; an omitted ``mode`` never overrides a stored live deployment
into sandbox.

The fake transport is intentionally not a live venue client. It is the
test seam: production code wires a deterministic sandbox transport;
tests substitute a spy with a configurable ``account`` and a
``MagicMock`` for ``send`` to assert that no send ever occurs.

Contract:

  * ``evaluate(...)`` always returns a ``PreflightResult``; refusal
    codes never depend on order of input validation beyond what is
    documented below.
  * On any refusal ``transport.send`` is not called; ``transport.balances``
    is not called either (balances are only read on a successful
    sandbox preflight).
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

MODE_SANDBOX = "sandbox"


class LiveTransport(Protocol):
    """The minimum surface the helper requires from any transport.

    ``send`` is the only call that could mutate venue state. The helper
    never invokes it; tests substitute a spy to assert the same.
    ``balances`` is a read-only call the helper makes on success to
    confirm the candidate account is reachable in the sandbox.
    """

    account: str

    def send(self, *args: Any, **kwargs: Any) -> Any: ...

    def balances(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class PreflightResult:
    """Versioned preflight result.

    ``schema_version`` is the literal ``"1"``. ``effect`` is one of
    ``"unchanged"`` (success — preflight ran, no state mutation) or
    ``"refused"`` (one of the refusal codes fired). On success the
    ``balances`` field carries the read-only sandbox balances.
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

    On success the helper reads ``transport.balances()`` and returns
    it in the result. It never calls ``transport.send``.
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

    balances = transport.balances()
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
    )


@dataclass(frozen=True)
class SandboxTransport:
    """Production fake transport. Not a live venue client.

    The workstation wires this in by default so ``live.preflight`` is
    always a dry run; tests replace it with a spy through
    ``_AppState.live_transport``.
    """

    account: str
    _balances: dict[str, Any] = field(default_factory=lambda: {"USD": 0.0})

    def send(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover - never called from preflight
        raise RuntimeError("SandboxTransport.send is never invoked by live.preflight")

    def balances(self) -> dict[str, Any]:
        return dict(self._balances)