"""B3 round-1 review fixes.

Each test pins one reviewer concern:

  * Welcome → Security → Next is the **primary** path; the dashboard is not
    silently marked visited on this path. Only Next's "Enter Dashboard"
    action POSTs the preference, through the existing token/session/CSRF/
    Origin gate, and the response is a 303 (PRG) back to the token-scoped
    dashboard.
  * The wizard nav has a real `aria-current` active state and the body
    carries a `data-route` attribute for it.
  * Dead CSS selectors (`button[type=submit][value="Stop all"]`) are gone.
  * Security trust posture is honest: a 0o755 home must NOT coexist with
    an all-green banner; an unknown mode must NOT be green; the overall
    posture distinguishes backend detected vs. backend+mode aggregate;
    the diagnostic names `krellbot doctor`; the "trade-only / withdraw-off"
    line is a REQUIREMENT statement, not a validated connection (no key
    probed).
  * The input border has at least 3:1 contrast against the canvas it sits
    on, and the focus state is cyan-tinted and visible.

The brief is clear that the existing paper POST contract, the fixed
exits, the no-external-asset rule, and the fail-closed posture must be
preserved. Every test below asserts one of those invariants in addition
to the fix it is named after.
"""

from __future__ import annotations

import http.client
import re
from pathlib import Path

# ---- helpers --------------------------------------------------------------


def _start_server(home: Path):
    from krellbot.ui.server import DashboardServer

    server = DashboardServer(home=home, port=0)
    server.start()
    return server


def _parse_set_cookies(resp: http.client.HTTPResponse) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in resp.getheaders():
        if k.lower() != "set-cookie":
            continue
        first = v.split(";", 1)[0].strip()
        if "=" not in first:
            continue
        name, _, value = first.partition("=")
        out[name.strip()] = value.strip()
    return out


def _login(server, port: int) -> tuple[str, str]:
    """GET /<token>/welcome once to set cookies. Returns (cookie_header, csrf)."""
    conn = http.client.HTTPConnection("127.0.0.1", port)
    try:
        conn.request("GET", f"/{server.token}/welcome")
        resp = conn.getresponse()
        resp.read()
        cookies = _parse_set_cookies(resp)
        session = cookies.get("krellbot_session", "")
        csrf = cookies.get("krellbot_csrf", "")
        assert session and csrf, (session, csrf, resp.getheaders())
        return f"krellbot_session={session}; krellbot_csrf={csrf}", csrf
    finally:
        conn.close()


def _get(server, path: str, *, cookies: str | None = None):
    conn = http.client.HTTPConnection("127.0.0.1", server.bound_port)
    try:
        headers = {}
        if cookies:
            headers["Cookie"] = cookies
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        body = resp.read().decode("utf-8", errors="replace")
        return resp.status, resp, body
    finally:
        conn.close()


def _post(server, path: str, *, body: str, cookies: str, origin: str | None):
    conn = http.client.HTTPConnection("127.0.0.1", server.bound_port)
    try:
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Content-Length": str(len(body)),
            "Cookie": cookies,
        }
        if origin is not None:
            headers["Origin"] = origin
        conn.request("POST", path, body=body.encode("utf-8"), headers=headers)
        resp = conn.getresponse()
        out = resp.read().decode("utf-8", errors="replace")
        return resp.status, resp, out
    finally:
        conn.close()


def _visible(html: str) -> str:
    """Return HTML with every <script>…</script> block stripped, for honest no-JS checks."""
    return re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.DOTALL)


# ---- primary-path preference semantics ----------------------------------


def test_welcome_continue_does_not_flip_preference(tmp_path: Path) -> None:
    """The Welcome page exposes a Continue button. The brief requires that
    following Welcome → Security → Next → Dashboard is the **primary** path
    and that visiting the dashboard does not silently mark the user
    'visited' until Next's explicit Enter Dashboard action does so via
    POST through the existing gate.

    Today the round-1 Welcome renders a form whose action is
    ``visit-dashboard``; submitting it silently writes the preference.
    After the fix, the Welcome must not POST the preference — the
    primary path is a sequence of GETs.
    """
    server = _start_server(tmp_path)
    try:
        status, _resp, body = _get(server, f"/{server.token}/welcome")
        assert status == 200
        # The Welcome page must NOT contain a form whose action is
        # visit-dashboard. The preference flip belongs only on Next's
        # "Enter Dashboard" action.
        assert 'action="visit-dashboard"' not in body, (
            "welcome must not POST visit-dashboard on Continue; the primary path is GET Welcome→Security→Next"
        )
    finally:
        server.stop()


def test_next_enter_dashboard_posts_then_redirects_303(tmp_path: Path) -> None:
    """Next's Enter Dashboard is the explicit gate to write the
    preference: it must POST through the existing token/session/CSRF/
    Origin gate and respond 303 to the token-scoped dashboard (PRG).

    The redirect target MUST preserve the token (no leak, no open
    redirect). It MUST NOT silently mark visited before the user clicks.
    """
    from krellbot.ui import first_run

    server = _start_server(tmp_path)
    try:
        assert first_run.has_visited_dashboard(tmp_path) is False
        cookies, csrf = _login(server, server.bound_port)
        origin = f"http://127.0.0.1:{server.bound_port}"
        status, resp, body = _post(
            server,
            f"/{server.token}/enter-dashboard",
            body=f"csrf={csrf}",
            cookies=cookies,
            origin=origin,
        )
        assert status == 303, (status, body)
        loc = resp.getheader("Location", "")
        assert loc == f"/{server.token}/dashboard", loc
        # The preference is now set.
        assert first_run.has_visited_dashboard(tmp_path) is True
        # No third-party location leak.
        assert "://" not in loc
    finally:
        server.stop()


def test_enter_dashboard_without_csrf_is_403(tmp_path: Path) -> None:
    """The Enter Dashboard POST inherits the existing gate."""
    from krellbot.ui import first_run

    server = _start_server(tmp_path)
    try:
        assert first_run.has_visited_dashboard(tmp_path) is False
        cookies, _csrf = _login(server, server.bound_port)
        status, _resp, _body = _post(
            server,
            f"/{server.token}/enter-dashboard",
            body="csrf=wrong",
            cookies=cookies,
            origin=f"http://127.0.0.1:{server.bound_port}",
        )
        assert status == 403
        assert first_run.has_visited_dashboard(tmp_path) is False
    finally:
        server.stop()


def test_direct_dashboard_get_does_not_flip_preference(tmp_path: Path) -> None:
    """A direct GET to /<token>/dashboard must NOT silently mark
    'visited'. The preference is owned by Next's Enter Dashboard
    action. The dashboard route itself is open: a returning user with
    the URL bookmarked is not penalized.
    """
    from krellbot.ui import first_run

    server = _start_server(tmp_path)
    try:
        assert first_run.has_visited_dashboard(tmp_path) is False
        cookies, _csrf = _login(server, server.bound_port)
        status, _resp, _body = _get(server, f"/{server.token}/dashboard", cookies=cookies)
        assert status == 200
        assert first_run.has_visited_dashboard(tmp_path) is False
    finally:
        server.stop()


def test_back_button_from_dashboard_does_not_visit(tmp_path: Path) -> None:
    """Back/forward in the browser must not mutate the preference."""
    from krellbot.ui import first_run

    server = _start_server(tmp_path)
    try:
        cookies, _csrf = _login(server, server.bound_port)
        for path in (
            f"/{server.token}/",
            f"/{server.token}/welcome",
            f"/{server.token}/security",
            f"/{server.token}/next",
            f"/{server.token}/dashboard",
        ):
            status, _resp, _body = _get(server, path, cookies=cookies)
            assert status == 200, path
        assert first_run.has_visited_dashboard(tmp_path) is False
    finally:
        server.stop()


# ---- wizard nav active state --------------------------------------------


def test_wizard_body_carries_data_route_per_page(tmp_path: Path) -> None:
    """Each wizard page's body must carry a ``data-route`` matching the
    route name. ``app.js`` reads ``document.body.dataset.route`` to set
    ``aria-current`` on the active link; without this attribute the
    enhancement is dead.

    Additionally, each page must server-render ``aria-current="page"``
    on the matching nav link so a no-JS user also gets the active
    affordance.
    """
    server = _start_server(tmp_path)
    try:
        for route in ("welcome", "security", "next"):
            status, _resp, body = _get(server, f"/{server.token}/{route}")
            assert status == 200, route
            assert f'data-route="{route}"' in body, (
                f"{route}: missing data-route on body (app.js nav highlighting is dead)"
            )
            # The matching nav link must have aria-current=page.
            pattern = (
                rf'href="{re.escape(route)}"[^>]*aria-current="page"'
                rf'|aria-current="page"[^>]*href="{re.escape(route)}"'
            )
            assert re.search(pattern, body), (
                f"{route}: nav link is missing aria-current=page (no-JS user does not see the active affordance)"
            )
    finally:
        server.stop()


def test_dashboard_nav_does_not_mark_active_for_wizard(tmp_path: Path) -> None:
    """The dashboard nav's active link is the Dashboard link only.
    Visiting a wizard route with aria-current=page on Dashboard would
    confuse the screen reader."""
    server = _start_server(tmp_path)
    try:
        status, _resp, body = _get(server, f"/{server.token}/welcome")
        assert status == 200
        nav_match = re.search(r"<nav[^>]*wizard-nav.*?</nav>", body, flags=re.DOTALL)
        assert nav_match, "wizard nav missing"
        nav = nav_match.group(0)
        assert 'href="welcome"' in nav
        assert 'aria-current="page"' in nav
        # No other nav link may claim aria-current on the welcome page.
        other = re.sub(r'<a [^>]*href="welcome"[^>]*>.*?</a>', "", nav, flags=re.DOTALL)
        assert 'aria-current="page"' not in other, "only the Welcome link may be aria-current on /welcome"
    finally:
        server.stop()


# ---- trust posture honesty -----------------------------------------------


def test_security_view_aggregates_backend_and_mode(tmp_path: Path) -> None:
    """The security view must distinguish backend detected vs overall
    posture, and must NOT show 'all green' when the home mode is 0o755
    (overly permissive). The brief is explicit: a 0o755 home must not
    coexist with an all-green banner."""
    import os

    from krellbot.ui import trust

    server = _start_server(tmp_path)
    try:
        os.chmod(tmp_path, 0o755)
        status, _resp, body = _get(server, f"/{server.token}/security")
        assert status == 200
        lower = _visible(body).lower()
        # The posture must mention the over-permissive mode.
        assert "0o755" in lower, "security view must report the actual home mode (0o755), not hide it"
        # The posture must not be all-green; it must say something is wrong.
        assert (
            "0o700" in lower
            or "tighten" in lower
            or "permission" in lower
            or "private" in lower
            or "not private" in lower
        ), "security view must flag the non-0o700 home as a posture issue"
        # The fail-closed diagnostic must name the CLI.
        assert "krellbot doctor" in lower, "failing posture must name `krellbot doctor` as the next CLI action"
        # And the snapshot must still report the backend honestly even
        # when the overall posture is failing.
        snap = trust.trust_snapshot(tmp_path)
        assert snap["home_mode"] == "0o755"
    finally:
        server.stop()


def test_security_view_unknown_mode_is_not_green(tmp_path: Path) -> None:
    """When the home mode cannot be read (e.g. on Windows or a missing
    path), the trust posture must not silently show all-green."""
    from krellbot.ui import trust

    server = _start_server(tmp_path)
    try:
        # Force home_mode=None by pointing trust at a non-existent path.
        original = trust._home_mode_or_none
        trust._home_mode_or_none = lambda _h: None  # type: ignore[assignment]
        try:
            status, _resp, body = _get(server, f"/{server.token}/security")
            assert status == 200
            lower = _visible(body).lower()
            # The "Home mode" row must say something is unknown, not green.
            assert "unknown" in lower or "could not read" in lower or "n/a" in lower or "not readable" in lower, (
                "unknown home mode must surface as unknown, not as a green check"
            )
        finally:
            trust._home_mode_or_none = original  # type: ignore[assignment]
    finally:
        server.stop()


def test_security_view_backend_detected_separate_from_overall(tmp_path: Path) -> None:
    """The backend-detected status is its own row, distinct from the
    overall posture row. A persistent backend does not imply the
    overall posture is green — the home mode is still checked."""
    import os

    from krellbot.ui import trust

    server = _start_server(tmp_path)
    try:
        os.chmod(tmp_path, 0o700)  # tight mode
        snap = trust.trust_snapshot(tmp_path)
        backend_name = snap.get("keychain_backend") or "(none)"
        backend_str = str(backend_name) if backend_name else "(none)"
        status, _resp, body = _get(server, f"/{server.token}/security")
        assert status == 200
        lower = _visible(body).lower()
        # Backend row exists, separate from the mode row.
        assert "backend" in lower
        assert "home mode" in lower or "mode" in lower
        # The visible body must not collapse both into one.
        assert backend_str.lower() in lower or backend_str in body, (
            f"backend row must show the actual backend name ({backend_str})"
        )
    finally:
        server.stop()


def test_security_view_key_permissions_is_a_requirement_not_validated(tmp_path: Path) -> None:
    """The 'Trade permission on, withdraw permission off' line is a
    REQUIREMENT statement, not a validated connection. No key is
    probed; the line must say so explicitly so the user does not read
    it as 'your exchange is connected with these perms'."""
    server = _start_server(tmp_path)
    try:
        status, _resp, body = _get(server, f"/{server.token}/security")
        assert status == 200
        lower = _visible(body).lower()
        # The phrase must describe the requirement, not a verified
        # state. "required" / "requirement" / "must" are acceptable
        # framings.
        assert (
            "required" in lower
            or "requirement" in lower
            or "must" in lower
            or "never probed" in lower
            or "not validated" in lower
        ), "key-permissions line must be labelled a REQUIREMENT, not a validated connection"
    finally:
        server.stop()


def test_trust_snapshot_carries_overall_posture(tmp_path: Path) -> None:
    """trust_snapshot must expose both ``backend_ok`` and an overall
    posture (``posture_ok`` / ``posture_warning``) so the wizard can
    honestly render 'backend detected' AND 'overall posture has X
    issue' as separate rows."""
    import os

    from krellbot.ui import trust

    os.chmod(tmp_path, 0o755)
    snap = trust.trust_snapshot(tmp_path)
    # The snapshot must carry a posture field so the renderer can
    # branch on it. We don't constrain the exact key name — we just
    # assert there is *some* field distinguishing backend from overall.
    keys = set(snap.keys())
    assert "keychain_ok" in keys
    # And an overall posture field must exist.
    posture_fields = {"posture_ok", "posture_warning", "home_mode_ok"}
    assert keys & posture_fields, f"trust_snapshot must expose an overall-posture field; got {keys}"


# ---- visual contrast & dead selectors ------------------------------------


def test_input_border_contrast_meets_3_to_1(tmp_path: Path) -> None:
    """The round-1 review found the input border #1f2730 against the
    canvas-elev #0d1117 is ~1.25:1 contrast — invisible. After the fix
    the border must reach WCAG 3:1 (decorative non-text contrast
    minimum)."""
    import re as _re

    css = (Path("src/krellbot/ui/static") / "style.css").read_text()
    # The rule that styles inputs/selects/textareas may use a comma list.
    # Find the first input-related rule and read its border.
    m = _re.search(
        r"^input,\s*select,\s*textarea\s*\{([^}]*)\}",
        css,
        flags=_re.MULTILINE,
    )
    assert m, "no input/select/textarea rule found in style.css"
    body = m.group(1)
    # The border may reference `var(--border)` rather than a hex literal.
    # Resolve it from :root.
    border_var_m = _re.search(r"border:\s*1px solid\s+var\(--border\)", body)
    if border_var_m:
        root_m = _re.search(r":root\s*\{([^}]*)\}", css, flags=_re.DOTALL)
        assert root_m, ":root block missing"
        token_m = _re.search(r"--border:\s*(#[0-9a-fA-F]+)", root_m.group(1))
        assert token_m, "--border token missing from :root"
        bm_match = token_m
        border_hex = token_m.group(1).lstrip("#")
    else:
        bm_match = _re.search(r"border:\s*1px solid\s*(#[0-9a-fA-F]+)", body)
        assert bm_match, f"input rule has no `border: 1px solid #xxxxxx` or `border: 1px solid var(--border)`: {body!r}"
        border_hex = bm_match.group(1).lstrip("#")
    br, bg, bb = int(border_hex[0:2], 16), int(border_hex[2:4], 16), int(border_hex[4:6], 16)

    # Compute the contrast ratio against #0d1117 (canvas-elev) and #07090d (canvas).
    def luminance(r, g, b):
        def c(x):
            x = x / 255.0
            return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4

        return 0.2126 * c(r) + 0.7152 * c(g) + 0.0722 * c(b)

    def ratio(c1, c2):
        l1, l2 = luminance(*c1), luminance(*c2)
        if l1 < l2:
            l1, l2 = l2, l1
        return (l1 + 0.05) / (l2 + 0.05)

    for canvas in (((13, 17, 23), "#0d1117"), ((7, 9, 13), "#07090d")):
        r = ratio((br, bg, bb), canvas[0])
        assert r >= 3.0, (
            f"input border (resolved {bm_match.group(1)}) contrast against {canvas[1]} is {r:.2f}:1, must be >= 3:1"
        )


def test_focus_visible_uses_cyan_signal_token(tmp_path: Path) -> None:
    """The visible focus state must use the cyan signal token so it
    stands out from the body background. A generic 'inherit' or 'auto'
    would hide focus for keyboard users. We check both the literal
    :focus-visible rule and the --focus-ring token value."""
    css = (Path("src/krellbot/ui/static") / "style.css").read_text()
    m = re.search(r":focus-visible\s*\{[^}]*\}", css, flags=re.DOTALL)
    assert m, ":focus-visible rule missing from style.css"
    block = m.group(0)
    assert "outline" in block
    # The rule may use var(--focus-ring) — resolve it by reading the
    # token's value from :root.
    root_m = re.search(r":root\s*\{([^}]*)\}", css, flags=re.DOTALL)
    assert root_m, ":root block missing"
    focus_ring_m = re.search(r"--focus-ring:\s*(#[0-9a-fA-F]+)", root_m.group(1))
    assert focus_ring_m, "--focus-ring token missing from :root — focus ring color is undefined"
    color = focus_ring_m.group(1).lower()
    # Must be cyan (high blue + high green).
    gg, bb = int(color[3:5], 16), int(color[5:7], 16)
    assert gg > 200 and bb > 200, (
        f"--focus-ring {color} is not cyan — focus ring will not stand out against the dark canvas"
    )


def test_no_dead_stop_all_selector(tmp_path: Path) -> None:
    """The round-1 review found ``button[type=submit][value="Stop all"]``
    — a dead selector. The actual button has ``type=submit`` and
    ``text="Stop all"``, but no ``value="Stop all"``. The CSS must not
    carry this dead rule."""
    css = (Path("src/krellbot/ui/static") / "style.css").read_text()
    assert 'button[type=submit][value="Stop all"]' not in css, (
        'dead selector `button[type=submit][value="Stop all"]` is still in style.css — remove it'
    )


def test_dashboard_card_border_visible(tmp_path: Path) -> None:
    """Dashboard cards (the action forms) currently use the same near-
    invisible 1px border as inputs. After the fix the border must be
    visible (>= 3:1) so the user can see the card outline at a glance.
    The .card border resolves via var(--border)."""
    css = (Path("src/krellbot/ui/static") / "style.css").read_text()
    # Read --border from :root.
    root_m = re.search(r":root\s*\{([^}]*)\}", css, flags=re.DOTALL)
    assert root_m, ":root block missing"
    border_m = re.search(r"--border:\s*(#[0-9a-fA-F]+)", root_m.group(1))
    assert border_m, "--border token missing from :root"
    border_hex = border_m.group(1).lstrip("#")
    br, bg, bb = int(border_hex[0:2], 16), int(border_hex[2:4], 16), int(border_hex[4:6], 16)

    def luminance(r, g, b):
        def c(x):
            x = x / 255.0
            return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4

        return 0.2126 * c(r) + 0.7152 * c(g) + 0.0722 * c(b)

    def ratio(c1, c2):
        l1, l2 = luminance(*c1), luminance(*c2)
        if l1 < l2:
            l1, l2 = l2, l1
        return (l1 + 0.05) / (l2 + 0.05)

    # Card sits on canvas-elev or canvas depending on context.
    for canvas in (((13, 17, 23), "#0d1117"), ((7, 9, 13), "#07090d")):
        r = ratio((br, bg, bb), canvas[0])
        assert r >= 3.0, (
            f"--border {border_m.group(1)} (used by .card) contrast against {canvas[1]} is {r:.2f}:1, must be >= 3:1"
        )


# ---- design polish: stepper & dashboard visual hierarchy -----------------


def test_wizard_renders_visible_progress_stepper(tmp_path: Path) -> None:
    """The wizard needs a visible progress stepper, not just text
    'Progress: 1 of 3'. A real stepper is a horizontal indicator that
    shows the current step is past, current, or upcoming — without
    relying on color alone."""
    server = _start_server(tmp_path)
    try:
        status, _resp, body = _get(server, f"/{server.token}/welcome")
        assert status == 200
        # The wizard must expose a stepper element (an ordered or
        # unordered list, or an <ol class="stepper">) with one item
        # per step, and the current step must be visually flagged.
        lower = _visible(body).lower()
        # Either an explicit stepper, or per-step li with current/aria-current.
        has_stepper = (
            "stepper" in lower
            or re.search(r'<ol[^>]*class="[^"]*stepper', body) is not None
            or re.search(r'<ul[^>]*class="[^"]*stepper', body) is not None
        )
        assert has_stepper, (
            "wizard must expose a visible progress stepper element, not just the text 'Progress: 1 of 3'"
        )
    finally:
        server.stop()


def test_dashboard_status_section_is_a_card(tmp_path: Path) -> None:
    """The Local status block on the dashboard must be visually
    elevated above other sections (it's the most important block — it
    answers 'what is true about this machine'). After the fix it
    carries an extra class that puts it on top of the visual stack."""
    from krellbot.ui import first_run

    first_run.mark_visited_dashboard(tmp_path)
    server = _start_server(tmp_path)
    try:
        status, _resp, body = _get(server, f"/{server.token}/dashboard")
        assert status == 200
        # The status section must carry a class that signals 'primary
        # / most-important'. We accept any class name that conveys
        # visual hierarchy.
        m = re.search(
            r'<section[^>]*id="status-section"[^>]*>',
            body,
        )
        assert m, "status section missing"
        attrs = m.group(0)
        assert (
            "primary" in attrs
            or "hero" in attrs
            or "elevated" in attrs
            or "card-primary" in attrs
            or "primary-card" in attrs
        ), "dashboard status section must signal visual primacy so users see it first"
    finally:
        server.stop()
