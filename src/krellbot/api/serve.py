"""Loopback launcher for the FastAPI workstation shell.

`WorkstationServer` is the in-process launcher the ``krellbot workstation``
CLI uses to bind the FastAPI app built by :func:`krellbot.api.app.create_app`
to a single loopback socket and serve it on a daemon thread. The socket
is pre-bound by this module and handed to ``uvicorn.Server.run`` via
``sockets=[...]`` so uvicorn never opens a second socket — there is
exactly one TCP listener, and it is bound to ``127.0.0.1``.

The bootstrap token is generated here with ``secrets.token_urlsafe`` and
passed to ``create_app``. The same bound port is passed in so the
session-gate, origin check, and loopback-host middleware all share the
real OS-assigned port. ``port=0`` is never threaded into ``create_app``
after the socket has a real port: doing so would let the app's middleware
reject every loopback request because the port would no longer match.

The server thread is daemonised so a hard exit (signal-killed child) does
not leak a process. ``stop()`` flips ``should_exit`` on the uvicorn
Server and joins the thread; the daemon flag is the backstop.
"""

from __future__ import annotations

import secrets
import socket
import threading
import time
from pathlib import Path

import uvicorn

_BIND_HOST = "127.0.0.1"


class WorkstationServer:
    """Pre-bind one loopback socket, hand it to uvicorn, run on a thread.

    Parameters
    ----------
    home:
        Krellbot data home. Passed verbatim to ``create_app`` so the API
        routes read state from the same directory the CLI uses.
    port:
        TCP port to bind. ``0`` means the OS assigns one; the assigned
        port is exposed as ``bound_port`` after :meth:`start` returns.
    dist_dir:
        Optional frontend ``dist`` directory. When ``None``,
        ``create_app`` falls back to its built-in resolver (the
        PyInstaller ``_MEIPASS`` path or the repo ``frontend/dist``).
        Callers (tests, custom builds) can pin a fixture here.

    Attributes
    ----------
    bound_host:
        Always ``"127.0.0.1"``. The launcher never widens the bind.
    bound_port:
        ``0`` until :meth:`start` returns, then the OS-assigned port.
    url:
        ``"http://127.0.0.1:{bound_port}/"``. Updated by :meth:`start`
        once the port is known. The bootstrap token is intentionally
        absent from the URL — the shell retrieves it from the
        ``<meta name="krellbot-bootstrap">`` tag in the served HTML.
    bootstrap_token:
        ``""`` until :meth:`start` returns, then the same URL-safe
        token handed to ``create_app``. A read-only, in-process
        attribute for callers (tests, the CLI) that need to redeem a
        session without parsing HTML. It is never printed, logged, or
        placed in a URL, and :meth:`stop` clears it back to ``""``.
    """

    def __init__(
        self,
        home: Path,
        *,
        port: int = 0,
        dist_dir: Path | None = None,
    ) -> None:
        self._home = Path(home)
        self._requested_port = int(port)
        self._dist_dir = Path(dist_dir) if dist_dir is not None else None
        self.bound_host: str = _BIND_HOST
        self.bound_port: int = 0
        self.url: str = ""
        self.bootstrap_token: str = ""
        self._socket: socket.socket | None = None
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Bind the socket, build the app, and serve it on a daemon thread.

        Idempotent: a second call after a successful start is a no-op so
        a test can start, GET, and stop once without tracking extra
        state. A failed start (bind refused, app build raises) leaves
        ``bound_port`` at ``0`` so callers can detect the failure.
        """

        if self._server is not None:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind((_BIND_HOST, self._requested_port))
        except OSError:
            sock.close()
            raise
        # We own the socket now; uvicorn takes ownership once handed
        # the list. Mark it non-blocking only after the bind so the
        # server thread can loop on accept().
        sock.listen(128)
        self._socket = sock
        self.bound_port = int(sock.getsockname()[1])
        self.url = f"http://{self.bound_host}:{self.bound_port}/"

        from krellbot.api.app import create_app

        bootstrap_token = secrets.token_urlsafe(32)
        app = create_app(
            self._home,
            port=self.bound_port,
            bootstrap_token=bootstrap_token,
            dist_dir=self._dist_dir,
        )
        self.bootstrap_token = bootstrap_token

        config = uvicorn.Config(
            app,
            host=_BIND_HOST,
            port=self.bound_port,
            log_level="warning",
        )
        server = uvicorn.Server(config)
        self._server = server
        thread = threading.Thread(
            target=server.run,
            kwargs={"sockets": [sock]},
            name="krellbot-workstation",
            daemon=True,
        )
        self._thread = thread
        thread.start()
        self._wait_until_http()

    def _wait_until_http(self) -> None:
        """Return only after the bound socket accepts an HTTP request.

        The URL is printed by the CLI after ``start`` returns. A bound
        socket that is not yet listening answers with connection refused.
        """

        deadline = time.monotonic() + 5
        last_error: OSError | None = None
        request = (f"GET / HTTP/1.1\r\nHost: {self.bound_host}:{self.bound_port}\r\nConnection: close\r\n\r\n").encode()
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(
                    (self.bound_host, self.bound_port),
                    timeout=0.2,
                ) as conn:
                    conn.sendall(request)
                    data = conn.recv(12)
                if data.startswith(b"HTTP/"):
                    return
            except OSError as exc:
                last_error = exc
                time.sleep(0.02)
        raise RuntimeError(f"workstation did not accept on {self.url}: {last_error}")

    def stop(self) -> None:
        """Signal the uvicorn server to exit and join the thread.

        Sets ``should_exit`` so the server loop drains in-flight
        requests and returns. The daemon thread is joined with a short
        timeout; a wedged worker cannot wedge the launcher because the
        thread will eventually die when the process exits.
        """

        server = self._server
        thread = self._thread
        if server is not None:
            # ``should_exit`` is a plain attribute on uvicorn 0.54.0;
            # guarding the assignment keeps the cleanup path resilient
            # if a future refactor replaces it with a property.
            try:
                server.should_exit = True
            except (AttributeError, TypeError):
                pass
        if thread is not None:
            thread.join(timeout=2)
        self._thread = None
        self._server = None
        sock = self._socket
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
            self._socket = None
        self.bound_port = 0
        self.url = ""
        self.bootstrap_token = ""
