"""In-memory fake keyring backend for tests.

KeyringBackend == the abstract base class of every keyring implementation. The
fake matches the 25.7.0 method signatures so secrets.py can target the real
backend interface without conditional code.
"""

import keyring.backend


class FakeKeyring(keyring.backend.KeyringBackend):
    priority = 1

    def __init__(self):
        self._store: dict[tuple[str, str], str] = {}

    def get_password(self, service, username):
        return self._store.get((service, username))

    def set_password(self, service, username, password):
        self._store[(service, username)] = password

    def delete_password(self, service, username):
        self._store.pop((service, username), None)
