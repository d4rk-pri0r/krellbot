# Slice B — Local First-Run Wizard and Trust UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The token-gated local UI presents a polished, honest first-run welcome and security posture, with safe navigation to the existing working dashboard and clear next steps.

**Architecture:** Evolve the existing stdlib server and local HTML/CSS/JS. A presentation-only trust snapshot reads local health metadata, never raw keys; a visited-dashboard preference controls launch route without claiming onboarding completion. Keep the existing POST routes and disk-backed dashboard semantics.

**Tech Stack:** Python 3.10+, stdlib `http.server`, vanilla JS/CSS, pytest; no frontend build or runtime CDN.

**Spec:** `docs/superpowers/specs/2026-09-25-first-run-slices-a-b-design.md`

## Global Constraints

- `DashboardServer` stays bound to `127.0.0.1`; token, cookies, Host/Origin allowlists, CSRF, no-store and UI live-arm refusal remain intact.
- No key entry, license redemption, purchase, scheduler install, or simulated connected/armed success in this slice.
- No raw exchange key, secret, activation key, license token, balance from keyring, or journal fill in the trust view.
- No CDN, external static assets, third-party analytics, or automatic remote network requests. Only fixed, user-initiated docs/source exits.
- Preserve the site's near-black and cyan brand, restrained status accent, keyboard access, readable contrast and reduced motion.
- A persisted `visited_dashboard` means visited only; missing/corrupt preference means first-run, not connected or complete.

## File structure

`src/krellbot/ui/trust.py` owns presentation-only local trust data. `src/krellbot/ui/first_run.py` owns atomic preference persistence under the data home. `src/krellbot/ui/server.py` gains token-scoped GET routes, fixed external exits and response security headers; no new sensitive POST. `src/krellbot/ui/static/index.html` becomes a small shell, with `app.js` route/navigation and existing dashboard action rendering, `style.css` tokens/layout/responsive states. `tests/test_ui_first_run.py` verifies navigation, trust, secrets, external exits, and state. Update `docs/dashboard.md`, `docs/getting-started.md`, `SECURITY.md`; stage published site-doc copy with the related release, not in a mismatched deployment.

## Review Focus

1. Corrupt or unreadable preference file: show first-run, never a 500 or false completion (Task 1 test).
2. Fake/null keyring backend: show warning, never green or a key value (Task 1 test).
3. Journal or pack label containing `</script>`: no executable HTML or secret leakage (Task 2 test).
4. Crafted Host, Origin, unrecognized redirect target, or missing token: 403/404 and no cookie or external redirect (Task 2 test).
5. Keyboard/reduced-motion/offline/empty states: primary action remains visible and no information is color-only (Task 3 UI test).

---

### Task 1: Persist only visit state and render true local security posture

**Files:** Create `src/krellbot/ui/first_run.py`, `src/krellbot/ui/trust.py`, `tests/test_ui_first_run.py`; reuse `krellbot.paths.atomic_write` and `krellbot.doctor._keychain_backend` after checking backend behavior.

**Interfaces:** Produces `has_visited_dashboard(home: Path) -> bool`, `mark_visited_dashboard(home: Path) -> None`, `trust_snapshot(home: Path) -> dict[str, object]`. Snapshot keys: `home`, `home_mode`, `keychain_backend`, `keychain_ok`, `bind`, `live_arm_ui_allowed`, `trade_only_required`. Never returns actual credential strings.

- [ ] **Step 1: Write failing tests** with a fake backend and a temporary data home:

```python
def test_fresh_and_corrupt_preference_are_not_complete(tmp_path):
    from krellbot.ui.first_run import has_visited_dashboard, mark_visited_dashboard
    assert has_visited_dashboard(tmp_path) is False
    mark_visited_dashboard(tmp_path)
    assert has_visited_dashboard(tmp_path) is True
    (tmp_path / "ui-preferences.json").write_text("{")
    assert has_visited_dashboard(tmp_path) is False


def test_trust_snapshot_never_reads_secret(tmp_path, monkeypatch):
    from krellbot.ui import trust
    monkeypatch.setattr(trust, "_keychain_backend", lambda: ("keyring.backends.null.Keyring", "unavailable"))
    result = trust.trust_snapshot(tmp_path)
    assert result["keychain_ok"] is False
    assert result["bind"] == "127.0.0.1"
    assert "secret" not in repr(result).lower()
```

- [ ] **Step 2: Run** `uv run pytest -q tests/test_ui_first_run.py`; expect import failure.
- [ ] **Step 3: Implement** bounded JSON preference and safe snapshot. Use `kb_paths.atomic_write(path, b'{"visited_dashboard":true}\n', mode=0o600)` and catch only `OSError`/`JSONDecodeError` on read. Compute mode from `stat.S_IMODE(home.stat().st_mode)` on POSIX; report `None` if missing or unreadable. Query backend identity only and expose an explicit `keychain_ok` boolean:

```python
def trust_snapshot(home: Path) -> dict[str, object]:
    backend, warning = _keychain_backend()
    return {"home": str(home), "home_mode": _mode_or_none(home),
            "keychain_backend": backend, "keychain_ok": warning is None,
            "bind": "127.0.0.1", "live_arm_ui_allowed": False,
            "trade_only_required": True}
```

- [ ] **Step 4: Run** `uv run pytest -q tests/test_ui_first_run.py tests/test_service_doctor.py`; expect PASS. Ensure writing the preference does not create a world-readable data home on POSIX.
- [ ] **Step 5: Commit** `git add src/krellbot/ui/first_run.py src/krellbot/ui/trust.py tests/test_ui_first_run.py && git commit -m "feat: expose local first-run security posture"`.

### Task 2: Token-scoped wizard routes and fixed exits

**Files:** Modify `src/krellbot/ui/server.py`, `tests/test_ui_first_run.py`, `tests/test_ui_server.py` only where the new route contract adds assertions.

**Interfaces:** Consumes `has_visited_dashboard`, `mark_visited_dashboard`, `trust_snapshot`. Produces GET `/<token>/welcome`, `/<token>/security`, `/<token>/next`, `/<token>/dashboard`; GET `/<token>/out/docs` and `/<token>/out/source` fixed redirects. The index route chooses welcome or dashboard based on visited preference, but never redirects to a URL missing the token. POST `/<token>/visit-dashboard` requires the existing cookie+CSRF+Origin check; no other new POST.

- [ ] **Step 1: Write failing HTTP tests** using `DashboardServer(home=tmp_path, port=0)` and `http.client`, with `try/finally: server.stop()` and no sleep. Assert fresh root renders Welcome, security route contains backend/path but no credential, visit POST changes later root to dashboard, Back still reaches Welcome, and unexpected `/out/evil` is 404. Assert missing token and foreign Host get 403, no `Set-Cookie`. Inject a journal string `</script><script>...` and assert it remains escaped as `\\u003c` in server HTML.

```python
def test_fixed_exit_does_not_reflect_untrusted_target(tmp_path):
    server = DashboardServer(home=tmp_path, port=0); server.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.bound_port)
        conn.request("GET", f"/{server.token}/out/evil?target=https://attacker.invalid")
        response = conn.getresponse()
        assert response.status == 404
        assert response.getheader("Location") is None
        response.read(); conn.close()
    finally:
        server.stop()
```

- [ ] **Step 2: Run** `uv run pytest -q tests/test_ui_first_run.py`; expect 404/route assertion failures.
- [ ] **Step 3: Implement** an exact route table after existing token/Host validation; do not use `startswith("out/")` with a caller-controlled target. Render the selected shell with escaped inline JSON (`_embed_json`) and scoped relative links. Record visit only through the existing POST validation. Set `Content-Security-Policy: default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self'; img-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'` initially (replace inline bootstrap with a nonce or JSON script before tightening), `Referrer-Policy: no-referrer`, `X-Content-Type-Options: nosniff`, and `Cache-Control: no-store` on all HTML and redirects. Fixed exits include docs at `https://krellbot.dev/docs/` and source at `https://github.com/d4rk-pri0r/krellbot` only; browser initiates navigation, server never fetches these domains.

```python
_EXITS = {"out/docs": "https://krellbot.dev/docs/",
          "out/source": "https://github.com/d4rk-pri0r/krellbot"}
# After token + Host checks:
if rest in _EXITS:
    self.send_response(302)
    self.send_header("Location", _EXITS[rest])
    self.send_header("Referrer-Policy", "no-referrer")
    self.send_header("Cache-Control", "no-store")
    self.end_headers()
    return
```

- [ ] **Step 4: Run** `uv run pytest -q tests/test_ui_first_run.py tests/test_ui_server.py`; expect PASS, including all seven original UI contract cases. Check no new network call in server module.
- [ ] **Step 5: Commit** `git add src/krellbot/ui/server.py tests/test_ui_first_run.py tests/test_ui_server.py && git commit -m "feat: serve gated first-run routes"`.

### Task 3: Accessible local visual shell and existing dashboard

**Files:** Modify `src/krellbot/ui/static/index.html`, `src/krellbot/ui/static/app.js`, `src/krellbot/ui/static/style.css`; create `tests/test_ui_static.py`; update `docs/dashboard.md`, `docs/getting-started.md`, `SECURITY.md`.

**Interfaces:** Consumes server-rendered `window.__KB_VIEW__` plus a `window.__KB_ROUTE__` string and trust snapshot, all escaped by `_embed_json`. Existing forms continue to POST relative actions under the token prefix; wizard visit POST includes CSRF field. Fixed docs/source exits remain server relative routes.

- [ ] **Step 1: Write failing static/UI tests** asserting local asset references, no `http://`, `https://`, or protocol-relative `//` in shipped static files, presence of Welcome/Security/Next actions, labelled paper-only controls, `prefers-reduced-motion`, visible focus style, and a no-JS route fallback. Add a browser-level keyboard smoke test where available; a DOM text test alone is insufficient for focus and responsive layout. Assert paper arm/disarm/stop-all/adopt forms keep their names/fields and CSRF hidden field.

```python
def test_static_has_no_remote_assets():
    from pathlib import Path
    root = Path("src/krellbot/ui/static")
    for path in root.rglob("*"):
        if path.is_file() and path.suffix in {".html", ".js", ".css"}:
            text = path.read_text()
            assert "http://" not in text and "https://" not in text
    assert "prefers-reduced-motion" in (root / "style.css").read_text()
```

- [ ] **Step 2: Run** `uv run pytest -q tests/test_ui_static.py`; expect missing wizard/reduced-motion assertions to fail.
- [ ] **Step 3: Implement** tokens and states without new dependencies. `index.html` has semantic `header`, `nav`, `main`, and accessible route headings; local docs/source links use relative `out/docs` and `out/source`. `app.js` uses `textContent` for journal/pack labels and never interpolates untrusted view values into `innerHTML`; preserve form field names and CSRF. Style the near-black canvas, cyan primary action, mono/table numeric figures, responsive cards/table, `:focus-visible`, high-contrast status text, and reduced-motion:

```css
:root { color-scheme: dark; --canvas: #07090d; --ink: #e7f4f8; --signal: #5ce1ff; }
:focus-visible { outline: 2px solid var(--signal); outline-offset: 3px; }
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: .01ms !important; transition-duration: .01ms !important; }
}
```

Keep empty, offline, error, paper, and live-armed read-only statuses legible without color. Dashboard's live action remains absent; do not alter server POST behavior. Update docs to describe first-run truthfully and explicitly separate future C/D flows; link published site docs only when the matching build is deployed.
- [ ] **Step 4: Run** `uv run pytest -q`, inspect a real local server on port 0, navigate welcome/security/next/dashboard with keyboard and narrow viewport in a browser, and verify reduced-motion in browser settings. Check static outbound references and no accidental secrets in DOM; preserve the paper action contract suite.
- [ ] **Step 5: Commit** `git add src/krellbot/ui/static tests/test_ui_static.py docs/dashboard.md docs/getting-started.md SECURITY.md && git commit -m "feat: finish local first-run interface"`.
