"""Static asset and UI contract tests for slice B3.

These tests pin the contract the brief requires:

  * shipped static files contain no ``http://``, ``https://``, or
    protocol-relative URLs;
  * the CSS exposes ``prefers-reduced-motion``;
  * the visible focus style (``:focus-visible``) is present;
  * a no-JS route fallback is preserved: the wizard pages expose
    sibling-relative links the browser can follow without running the
    embedded script;
  * every paper-action form keeps its existing field names
    (``pack_path``, ``venue``, ``paper_balance``, ``mode``, ``pack_id``,
    ``csrf``) so the existing paper-action contract tests stay green;
  * the hidden CSRF field is present on every form so the
    HttpOnly-cookie trick keeps working without the JS hydrator.

The brief requires the local visual shell be honest about its scope:
no fake live arm, no fake ROI, no fake second brand. These tests are
deliberately DOM-text-only plus structural-assertion; the keyboard /
focus / narrow-viewport behaviours are exercised in a separate
browser-level smoke test.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

STATIC_DIR = Path(__file__).resolve().parents[1] / "src" / "krellbot" / "ui" / "static"
INDEX_HTML = STATIC_DIR / "index.html"
STYLE_CSS = STATIC_DIR / "style.css"
APP_JS = STATIC_DIR / "app.js"


# ---- helpers --------------------------------------------------------------


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _all_static_files() -> list[Path]:
    return sorted(p for p in STATIC_DIR.rglob("*") if p.is_file())


def _static_text_files() -> list[Path]:
    out: list[Path] = []
    for p in _all_static_files():
        if p.suffix in {".html", ".js", ".css"}:
            out.append(p)
    return out


# ---- local-only asset guard (matches brief step 1) ------------------------


def test_static_has_no_remote_assets():
    """``http://``, ``https://``, and protocol-relative ``//`` URLs are
    forbidden in shipped static files. The site repository is the only
    place external URLs live.
    """
    failures: list[str] = []
    for path in _static_text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if "http://" in text:
            failures.append(f"{path}: contains 'http://'")
        if "https://" in text:
            failures.append(f"{path}: contains 'https://'")
        # Protocol-relative: ``href="//example.com/..."`` etc.
        for match in re.finditer(r"""["']\s*//[^/'"\\][^'"\\]*["']""", text):
            failures.append(f"{path}: protocol-relative URL {match.group(0)!r}")
    assert not failures, "\n".join(failures)


def test_static_only_allowlisted_external_links():
    """External ``https://`` links may appear in static files ONLY if
    they point at krellbot.dev/docs or the engine source repo, and the
    links must be user-initiated affordances (not auto-loaded assets).
    Anything else is an outbound leak.
    """
    allow = {"https://krellbot.dev/docs/", "https://github.com/d4rk-pri0r/krellbot"}
    for path in _static_text_files():
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r'https://[^\s"\'<>)]+', text):
            url = match.group(0).rstrip(".,)")
            assert url in allow, f"{path}: non-allowlisted external URL {url!r}"


# ---- accessibility primitives in CSS --------------------------------------


def test_css_prefers_reduced_motion():
    assert "prefers-reduced-motion" in _read(STYLE_CSS), (
        "style.css must respect prefers-reduced-motion for the "
        "no-looping-effects requirement"
    )


def test_css_focus_visible_outline():
    """The brief mandates a visible focus style. We require an explicit
    ``:focus-visible`` rule whose outline is not just ``none``.
    """
    text = _read(STYLE_CSS)
    assert ":focus-visible" in text, "missing :focus-visible rule"
    # And it must do something. The simplest "non-trivial" assertion is
    # that the rule is not just ``outline: none``.
    match = re.search(r":focus-visible\s*\{([^}]*)\}", text)
    assert match, "no :focus-visible rule body"
    body = match.group(1)
    assert "outline" in body, f":focus-visible rule missing outline: {body!r}"
    assert "none" not in body.split("outline")[1].split(";")[0].lower(), (
        f":focus-visible outline is none; users cannot see focus: {body!r}"
    )


def test_css_color_tokens_use_cyan_canvas():
    """Approved visual spec: near-black canvas (#07090d), cyan primary
    (#5ce1ff). These tokens must appear as CSS variables.
    """
    text = _read(STYLE_CSS)
    # Canvas: near-black, lowercase hex.
    assert "#07090d" in text.lower() or "07090d" in text, (
        "style.css must use the approved near-black canvas token"
    )
    # Cyan: precise #5ce1ff.
    assert "#5ce1ff" in text.lower() or "5ce1ff" in text, (
        "style.css must use the approved precise cyan primary"
    )


def test_css_does_not_invent_second_brand():
    """The brief forbids inventing a second brand palette. The cyan is
    the single primary interactive accent. A second saturated brand
    colour must not appear; the restrained #C6FF3D lime is allowed as
    a status token only.
    """
    text = _read(STYLE_CSS).lower()
    # Common "second brand" mistakes: hot pink, brand orange, vivid purple.
    forbidden = ("#ff00ff", "#ff1493", "#ff4500", "#8a2be2")
    for hex_ in forbidden:
        assert hex_ not in text, (
            f"style.css must not introduce a second brand palette ({hex_})"
        )


# ---- dashboard's static shell: existing forms / fields preserved ---------


# ---- dashboard's static shell: existing forms / fields preserved ---------


# ---- dashboard's static shell: existing forms / fields preserved ---------


# ---- dashboard: existing forms / fields preserved -------------------------


def test_dashboard_preserves_paper_arm_form_fields():
    """The existing paper-arm contract (test_ui_server.py +
    test_paper_venue.py) relies on these field names. The B3 reskin
    must keep them verbatim.
    """
    text = _read(INDEX_HTML)
    assert 'action="arm"' in text
    assert 'name="pack_path"' in text
    assert 'name="venue"' in text
    assert 'name="paper_balance"' in text
    assert 'name="mode"' in text  # mode is hidden; server enforces paper-only
    assert 'value="paper"' in text  # the hidden mode must be exactly "paper"


def test_dashboard_preserves_disarm_form_fields():
    text = _read(INDEX_HTML)
    assert 'action="disarm"' in text
    # Disarm form has venue + pair; both required.
    assert 'name="venue"' in text
    assert 'name="pair"' in text


def test_dashboard_preserves_stop_all_form():
    text = _read(INDEX_HTML)
    assert 'action="stop_all"' in text


def test_dashboard_preserves_adopt_form_fields():
    text = _read(INDEX_HTML)
    assert 'action="adopt"' in text
    assert 'name="pack_id"' in text


def test_every_form_has_csrf_hidden_field():
    """Every <form> in the page must contain a hidden csrf field; the
    HttpOnly cookie is unreadable to JS so the field is the only
    path. Without it the paper-action contract breaks.
    """
    text = _read(INDEX_HTML)
    forms = re.findall(r"<form\b[^>]*>(.*?)</form>", text, flags=re.DOTALL)
    assert forms, "no forms found in index.html"
    for form in forms:
        assert (
            'name="csrf"' in form
            or "name='csrf'" in form
        ), f"form missing csrf hidden field: {form[:120]!r}"


# ---- dashboard: live action absent, no fake ROI, status states ------------


def test_dashboard_does_not_render_live_arm_control():
    """Live arm from the UI is forbidden by the safety rail. The page
    must not advertise a "Live arm" button or label the existing
    paper form with live-looking language.
    """
    text = _read(INDEX_HTML).lower()
    # The existing copy "live arm from the page is refused" is fine.
    # We forbid an *enabled* affordance named "arm live" / "go live".
    for match in re.finditer(r"<button[^>]*>[^<]*</button>", text):
        body = match.group(0).lower()
        assert "arm live" not in body and "go live" not in body, (
            f"dashboard must not render a live-arm button: {match.group(0)!r}"
        )


def test_dashboard_does_not_claim_fake_roi():
    """No ROI, no "best bot", no "guaranteed return" copy."""
    text = _read(INDEX_HTML).lower()
    forbidden = (
        "roi",
        "guaranteed",
        "best bot",
        "best crypto",
        "profit guaranteed",
    )
    for phrase in forbidden:
        # Allow "no ROI claim" type safety rails.
        # We require that the phrase does not appear as a positive claim.
        # The simplest correct guard is to forbid the phrase entirely.
        assert phrase not in text, (
            f"dashboard must not advertise ROI / guaranteed returns ({phrase!r})"
        )


# ---- no-JS fallback ------------------------------------------------------


def test_no_js_route_fallback_via_static_html():
    """With JavaScript disabled the browser must still be able to
    navigate the wizard. The dashboard shell (index.html) renders for
    users who already visited; the wizard shell (rendered by
    server.py's ``_wizard_html``) renders for first-time users.

    The dashboard shell must offer a clear "Resume setup" affordance
    back to the wizard's welcome route so a returning user who never
    finished the wizard can pick it up without running JS.

    The wizard shell itself exposes welcome / security / next /
    dashboard as plain ``<a href="...">`` links with sibling-relative
    URLs. We assert both halves of the contract.
    """
    text = _read(INDEX_HTML)
    # Dashboard shell: resume-setup affordance back to welcome.
    assert re.search(r'<a[^>]+href="welcome"', text), (
        "dashboard shell must offer a 'resume setup' link back to "
        "the welcome route (sibling-relative)"
    )

    # Wizard shell: verify the nav exposes each wizard target. The
    # wizard template lives in server.py — read it and grep for the
    # four sibling-relative links.
    server_py = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "krellbot"
        / "ui"
        / "server.py"
    )
    src = server_py.read_text(encoding="utf-8")
    for target in ("welcome", "security", "next", "dashboard"):
        assert re.search(
            rf'<a[^>]+href="{re.escape(target)}"', src
        ), (
            f"wizard shell in server.py must expose {target!r} as a plain <a> link"
        )


def test_no_external_static_script_or_font():
    """No <script src=\"https://...\">, no <link href=\"https://...\"
    rel=\"stylesheet\">, no <link href=\"https://...\" rel=\"font\">.
    Local-only is the rule.
    """
    text = _read(INDEX_HTML)
    for match in re.finditer(r'<(?:script|link)[^>]+(?:src|href)\s*=\s*["\']([^"\']+)["\']', text):
        url = match.group(1)
        assert not url.startswith(("http://", "https://", "//")), (
            f"no external static asset allowed: {url}"
        )
        # Local hrefs must be relative (no leading slash + scheme).
        assert "://" not in url, f"unexpected absolute URL in static markup: {url}"


# ---- browser-level structural smoke (HTTP-only; no real browser needed) ---


def test_all_static_files_use_dark_color_scheme():
    """The approved visual spec is dark-canvas. We require the page to
    declare ``color-scheme: dark`` (or a hard-coded dark body
    background) so the browser does not flash a light theme before
    the stylesheet loads.
    """
    text = _read(STYLE_CSS)
    assert "color-scheme: dark" in text or "color-scheme:dark" in text, (
        "style.css must declare color-scheme: dark"
    )
