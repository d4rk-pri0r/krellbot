"""A fixed-port workstation can be updated after an ordinary browser visit."""

import http.client
import sys

import pytest

from krellbot.api.serve import WorkstationServer


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX TIME_WAIT reuse; Windows binding is unchanged (#373)")
def test_fixed_port_restarts_after_a_keepalive_browser_connection(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html><head></head><body>Workstation</body></html>")
    first = WorkstationServer(tmp_path / "home", dist_dir=dist)
    replacement = None
    connection = None
    try:
        first.start()
        port = first.bound_port
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request("GET", "/")
        response = connection.getresponse()
        assert response.status == 200
        response.read()
        # A browser/proxy keeps its connection open. Shutdown actively closes
        # the server side, leaving a TIME_WAIT socket after the peer closes.
        first.stop()
        connection.close()
        replacement = WorkstationServer(tmp_path / "home", port=port, dist_dir=dist)
        replacement.start()
        assert replacement.bound_host == "127.0.0.1"
        assert replacement.bound_port == port
    finally:
        first.stop()
        if connection is not None:
            connection.close()
        if replacement is not None:
            replacement.stop()
