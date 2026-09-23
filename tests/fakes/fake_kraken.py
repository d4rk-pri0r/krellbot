"""Fake Kraken transport for tests.

The fake records every POST: the URL, the form, and the headers. Tests pass a
list of `responses` and an optional `rate_limit_bodies` count to simulate the
documented backoff sequence.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RecordedCall:
    """One POST the venue made through the transport."""

    url: str
    form: dict[str, str]
    headers: dict[str, str]


class FakeKrakenTransport:
    """Returns the next body in `responses` for each POST.

    Set `rate_limit_first_n=2` to make the first two POSTs return
    `{"error": ["EAPI:Rate limit exceeded"]}`. Set `withdraw_methods` to
    the payload `/private/WithdrawMethods` should produce.
    """

    def __init__(
        self,
        responses: list[dict] | None = None,
        *,
        withdraw_methods: list | dict | None = None,
        rate_limit_first_n: int = 0,
        permission_error_on: set[str] | None = None,
    ) -> None:
        self._responses = list(responses or [])
        self._withdraw_methods = withdraw_methods
        self._rate_limit_first = rate_limit_first_n
        self._permission_error_on = permission_error_on or set()
        self.calls: list[RecordedCall] = []

    def post(self, url: str, form: dict[str, str], headers: dict[str, str]) -> dict:
        self.calls.append(RecordedCall(url=url, form=dict(form), headers=dict(headers)))
        endpoint = url.rsplit("/", 1)[-1]
        if endpoint in self._permission_error_on:
            return {"error": ["EAPI:Invalid key: Permission denied"]}
        if self._rate_limit_first > 0:
            self._rate_limit_first -= 1
            return {"error": ["EAPI:Rate limit exceeded"]}
        if endpoint == "WithdrawMethods":
            if self._withdraw_methods is None:
                return {"error": ["EAPI:Invalid key: Permission denied"]}
            if isinstance(self._withdraw_methods, list):
                return {"result": self._withdraw_methods}
            return self._withdraw_methods
        if not self._responses:
            return {"result": {}}
        return self._responses.pop(0)
