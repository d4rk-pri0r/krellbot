"""Task 4 — visual / docs polish for the new Exchange wizard step.

These tests pin the engine-side polish brief requirements:

  * the wizard forward flow is honest about the new four-step order
    (Welcome → Security → Exchange (keys) → Next) — copy, links,
    and step counter must reflect the new step;
  * the exchange page's rejection list ("what this page does not do")
    uses the historical-status wording that the slice-C ruling
    landed on (Task 3 fix round 1), never the stale
    "stored; no current verification" / "stored; last checked at";
  * SECURITY.md no longer labels the Exchange step a "future slice";
  * the JS stepperOrder in ``app.js`` matches the server-side
    stepper so the JS enhancement doesn't drop or duplicate a step;
  * the engine docs no longer reference the stale "stored; last
    checked at" comment language in server.py.

The tests are intentionally DOM-text-only — no JS execution, no
browser driver. The behaviour is observable from the rendered HTML
and the static asset text.
"""

from __future__ import annotations

import re
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parents[1] / "src" / "krellbot" / "ui" / "static"
SERVER_PY = Path(__file__).resolve().parents[1] / "src" / "krellbot" / "ui" / "server.py"
SECURITY_MD = Path(__file__).resolve().parents[1] / "SECURITY.md"


# ---- helpers --------------------------------------------------------------


def _start(home):
    from krellbot.ui.server import DashboardServer

    server = DashboardServer(home=home, port=0)
    server.start()
    return server


def _stop(server):
    try:
        server.stop()
    except (OSError, RuntimeError):
        pass


def _get(server, path):
    import http.client

    conn = http.client.HTTPConnection("127.0.0.1", server.bound_port)
    try:
        conn.request(
            "GET",
            path,
            headers={"Host": f"127.0.0.1:{server.bound_port}"},
        )
        resp = conn.getresponse()
        body = resp.read()
        return resp.status, dict(resp.getheaders()), body
    finally:
        conn.close()


def _visible(html: str) -> str:
    """Return HTML with every <script>...</script> block stripped."""
    return re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.DOTALL)


# ---- forward-flow nav (the four-step order) ------------------------------


def test_welcome_step_counter_says_one_of_four(home, fresh_keyring):
    """Welcome is step 1 of 4 — the brief re-states the four-step wizard."""
    server = _start(home)
    try:
        status, _h, body = _get(server, f"/{server.token}/welcome")
        assert status == 200
        visible = _visible(body.decode("utf-8", errors="replace"))
        assert "Step 1 of 4" in visible, "welcome copy must say 'Step 1 of 4' — there are now four wizard steps"
        assert "Step 1 of 3" not in visible, "stale 'Step 1 of 3' copy leaked into the welcome page"
    finally:
        _stop(server)


def test_welcome_links_to_security_then_skip_to_next(home, fresh_keyring):
    """Welcome exposes Continue-to-security AND Skip-to-next.

    The skip link is the user's out — it must keep working without
    having to walk through the security or exchange pages.
    """
    server = _start(home)
    try:
        status, _h, body = _get(server, f"/{server.token}/welcome")
        assert status == 200
        visible = _visible(body.decode("utf-8", errors="replace"))
        assert 'href="security"' in visible
        assert 'href="next"' in visible
    finally:
        _stop(server)


def test_security_continue_link_goes_to_exchange_not_next(home, fresh_keyring):
    """Security's forward link must go to the Exchange step, not skip it.

    Before Task 4 the security page skipped directly to next/ — that
    bypassed the new exchange-key step and was the underlying gap
    that motivated this slice.
    """
    server = _start(home)
    try:
        status, _h, body = _get(server, f"/{server.token}/security")
        assert status == 200
        visible = _visible(body.decode("utf-8", errors="replace"))
        # The forward affordance must point at the exchange step.
        assert 'href="keys"' in visible, "security must link forward to the exchange step ('keys')"
        # And the step counter must say step 2 of 4.
        assert "Step 2 of 4" in visible
    finally:
        _stop(server)


def test_exchange_page_continues_to_next_not_skip(home, fresh_keyring):
    """The exchange page must Continue to next, not Skip to next.

    Task 3 called it 'Skip' — that was misleading once the page
    became a real wizard step with a step counter. The honest label
    is 'Continue'.
    """
    server = _start(home)
    try:
        status, _h, body = _get(server, f"/{server.token}/keys")
        assert status == 200
        visible = _visible(body.decode("utf-8", errors="replace"))
        assert "Step 3 of 4" in visible, "exchange page must show 'Step 3 of 4' as its step counter"
        # Whole-page check: no literal 'Skip to next' on the exchange page.
        assert "Skip to next" not in visible, "exchange page must not say 'Skip to next' — it is now a real step"
        # The Continue affordance still points at the next step.
        assert 'href="next"' in visible
        # And the Back affordance still points at security.
        assert 'href="security"' in visible
    finally:
        _stop(server)


def test_next_page_says_step_four_of_four(home, fresh_keyring):
    """Next is step 4 of 4 — pre-existing copy already said 'Step 4 of 4'
    so this is a regression guard rather than a new label."""
    server = _start(home)
    try:
        status, _h, body = _get(server, f"/{server.token}/next")
        assert status == 200
        visible = _visible(body.decode("utf-8", errors="replace"))
        assert "Step 4 of 4" in visible
    finally:
        _stop(server)


# ---- historical-status wording on the exchange page ----------------------


def test_exchange_rejection_list_uses_historical_language(home, fresh_keyring):
    """The 'what this page does not do' block on the exchange page must
    describe the historical 'last stored through wizard at <ts>; current
    key presence not checked' language and the unknown /
    'not currently verified' fallback — never the stale
    'stored; last checked at' or 'stored; no current verification'.
    """
    server = _start(home)
    try:
        status, _h, body = _get(server, f"/{server.token}/keys")
        assert status == 200
        visible = _visible(body.decode("utf-8", errors="replace"))
        # Both honest framings must be described in the rejection list.
        assert "last stored through wizard at" in visible
        assert "not currently verified" in visible
        # Stale language must NOT appear in the user-facing copy.
        assert "stored; no current verification" not in visible, (
            "stale 'stored; no current verification' wording still on the page"
        )
        assert "stored; last checked at" not in visible, "stale 'stored; last checked at' wording still on the page"
    finally:
        _stop(server)


def test_exchange_rejection_list_explains_cli_rotation_unseen(home, fresh_keyring):
    """The exchange page's rejection list must explain that CLI-side key
    rotation is not detectable without a credential read — otherwise
    users would assume a 'no current verification' row implies the
    keyring is empty.
    """
    server = _start(home)
    try:
        status, _h, body = _get(server, f"/{server.token}/keys")
        assert status == 200
        visible = _visible(body.decode("utf-8", errors="replace"))
        # Honest about the fact that current key presence is never
        # probed (and never proven absent) on render.
        assert "CLI-side rotation" in visible or "cli-side rotation" in visible.lower()
    finally:
        _stop(server)


# ---- stale-comment cleanup in server.py ---------------------------------


def test_server_py_has_no_stale_last_checked_at_comment():
    """server.py used to carry the stale 'stored; last checked at <ts>'
    comment in two places. The fix updates both to the historical
    'last stored through wizard at <ts>; current key presence not checked'
    language so future readers do not reintroduce the live-claim
    framing.
    """
    text = SERVER_PY.read_text(encoding="utf-8")
    assert "stored; last checked at" not in text, (
        "stale 'stored; last checked at' comment language is still in server.py"
    )
    # The replacement language is in the production copy (the user-facing
    # explanation on the exchange page). The two stale comment sites have
    # been updated to match.
    assert "last stored through wizard at" in text


# ---- app.js stepperOrder matches the server-side stepper ----------------


def test_appjs_stepper_order_includes_exchange_step():
    """The JS enhancement that visually 'turns past steps cyan' uses a
    hard-coded stepperOrder list. If it omits 'keys', the enhancement
    silently de-highlights the security step when the user is on the
    exchange page. The list must match the server-side stepper.
    """
    text = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    m = re.search(
        r"stepperOrder\s*=\s*\[([^\]]+)\]",
        text,
    )
    assert m, "stepperOrder literal not found in app.js"
    items = [s.strip().strip("\"'") for s in m.group(1).split(",")]
    assert items == ["welcome", "security", "keys", "next"], (
        f"app.js stepperOrder {items!r} does not match the server-side stepper ['welcome', 'security', 'keys', 'next']"
    )


# ---- SECURITY.md no longer labels Exchange a future slice ----------------


def test_security_md_does_not_label_exchange_a_future_slice():
    """SECURITY.md previously said 'Next page labels exchange connection
    (slice C) and pack adoption (slice D) as future slices'. Slice C
    Exchange is now part of the wizard; SECURITY.md must reflect that
    or it will mislead readers.
    """
    text = SECURITY_MD.read_text(encoding="utf-8")
    assert "exchange connection (slice C) and pack adoption" not in text, (
        "SECURITY.md still labels slice C Exchange as a future slice"
    )
    # The honest framing is present.
    assert "Slice C" in text
    assert "Exchange" in text or "exchange" in text
    # The historical status line is documented.
    assert "last stored through wizard at" in text
    assert "not currently verified" in text
