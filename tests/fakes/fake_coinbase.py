"""Fake Coinbase transport for tests.

The fake records every GET and POST. Tests pass a list of `responses` for
POSTs and a list of `get_responses` for GETs (matched positionally, consumed
in order). The `key_permissions` controls what `check_key` sees.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RecordedCall:
    """One HTTP call the venue made through the transport."""

    method: str
    url: str
    headers: dict[str, str]
    body: dict | None = None


class FakeCoinbaseTransport:
    """Returns the next response per method.

    `key_permissions` is the body that `GET /api/v3/brokerage/key_permissions`
    returns; if it's None the fake raises so tests catch an accidental hit.
    """

    def __init__(
        self,
        post_responses: list[dict] | None = None,
        get_responses: list[dict] | None = None,
        *,
        key_permissions: dict | list | None = None,
    ) -> None:
        self._post_responses = list(post_responses or [])
        self._get_responses = list(get_responses or [])
        self._key_permissions = key_permissions
        self.calls: list[RecordedCall] = []

    def post(self, url: str, body: dict, headers: dict[str, str]) -> dict:
        self.calls.append(RecordedCall(method="POST", url=url, headers=dict(headers), body=dict(body)))
        if not self._post_responses:
            return {"success": True}
        return self._post_responses.pop(0)

    def get(self, url: str, headers: dict[str, str]) -> dict:
        self.calls.append(RecordedCall(method="GET", url=url, headers=dict(headers)))
        if "key_permissions" in url:
            if self._key_permissions is None:
                return {"scopes": []}
            return self._key_permissions
        if not self._get_responses:
            return {}
        return self._get_responses.pop(0)
