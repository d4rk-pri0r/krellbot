"""Copy contract: loopback form, outbound venue probe, no current-status claim."""

import re
from pathlib import Path

from test_ui_keys_polish_task4 import _get, _start, _stop, _visible

ROOT = Path(__file__).resolve().parents[1]


def test_exchange_wizard_discloses_venue_egress(home, fresh_keyring):
    server = _start(home)
    try:
        status, _, body = _get(server, f"/{server.token}/keys")
        assert status == 200
        visible = _visible(body.decode("utf-8"))
        assert "no call leaves this machine" not in visible.lower()
        assert "nothing leaves this machine" not in visible.lower()
        assert "loopback" in visible.lower()
        assert "authenticated HTTPS" in visible
        assert "Kraken" in visible and "Coinbase" in visible
        assert "krellbot.dev never receives" in visible.lower()
    finally:
        _stop(server)


def test_static_and_security_docs_do_not_denounce_actual_probe():
    static = (ROOT / "src/krellbot/ui/static/index.html").read_text()
    assert "no call leaves this machine" not in static.lower()
    assert "exchange" in static.lower() and "venue" in static.lower()

    security = (ROOT / "SECURITY.md").read_text()
    dashboard = (ROOT / "docs/dashboard.md").read_text()
    module_doc = (ROOT / "src/krellbot/ui/__init__.py").read_text()
    for name, text in (("SECURITY.md", security), ("docs/dashboard.md", dashboard), ("ui/__init__.py", module_doc)):
        assert "no call to a live venue" not in text.lower(), name
        assert "never calls Kraken, Coinbase" not in text, name
        assert "No call to Kraken, Coinbase" not in text, name
        assert "authenticated HTTPS" in text, name
        assert "krellbot.dev" in text, name
    assert "the wizard is read-only" not in security.lower()
    assert "three steps: welcome, security, next" not in dashboard.lower()
    assert "exchange connection (slice C) and pack adoption" not in dashboard
    assert "Step 1 of 3" not in dashboard and "3 of 3" not in dashboard


def test_overview_and_getting_started_match_four_step_probe():
    readme = (ROOT / "README.md").read_text()
    getting_started = (ROOT / "docs/getting-started.md").read_text()
    server_doc = (ROOT / "src/krellbot/ui/server.py").read_text().split('"""', 2)[1]
    assert "The UI does not call any exchange" not in readme
    assert "authenticated HTTPS" in readme
    assert "three\nsteps: Welcome, Security, Next" not in getting_started
    assert "visit-dashboard" not in getting_started
    assert "Exchange" in getting_started and "authenticated HTTPS" in getting_started
    assert "No call to Kraken,\nCoinbase" not in server_doc
    assert re.search(r"authenticated\s+HTTPS", server_doc)


def test_docs_explain_env_pair_can_override_wizard_key():
    for name in ("SECURITY.md", "docs/dashboard.md", "docs/getting-started.md"):
        text = (ROOT / name).read_text()
        assert "KRELLBOT_<VEN>_KEY" in text, name
        assert "KRELLBOT_<VEN>_SECRET" in text, name
        assert "precedence" in text.lower(), name
        assert "keyring" in text.lower(), name
