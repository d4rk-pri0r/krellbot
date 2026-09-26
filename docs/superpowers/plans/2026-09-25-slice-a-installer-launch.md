# Slice A — Verified Installer and Local UI Launch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A fresh Windows, macOS, or Linux user can install a verified, self-contained, per-user Krellbot artifact and open the existing gated loopback UI without preinstalled Python.

**Architecture:** Keep the Python engine and dashboard server. Produce pinned one-directory frozen archives on each advertised OS and have the separate `krellbot-cloud` site render short, fail-closed installers with literal artifact coordinates and digest. Add an injectable browser-opening CLI path; never change the UI's bind or live-arm rule.

**Tech Stack:** Python 3.10+, uv lockfile, PyInstaller one-dir, pytest, PowerShell 5.1+, POSIX sh, Node `node:test`, Cloudflare Pages Functions. Two repositories: `/Users/waifumachine/krellbot` and `/Users/waifumachine/krellbot-cloud` (site tree is ahead and contains untracked `brand/`; isolate execution in clean worktrees).

**Spec:** `docs/superpowers/specs/2026-09-25-first-run-slices-a-b-design.md`

## Global Constraints

- Preserve `127.0.0.1`, 32-byte token URL, session/CSRF cookies, Host/Origin checks, no-store responses, and existing paper-only actions.
- No root/Administrator, no default remote bind, no preinstalled Python, no install-time scheduler, no credential fallback to plaintext.
- `$KRELLBOT_HOME` is independent of executable installation and survives uninstall by default.
- Do not claim signing/notarization until actual signed artifacts are checked; mark unsigned builds accurately.
- The site endpoint returns 503 for missing/malformed release metadata; never emit a partially configured script.
- Never advertise an OS/architecture without its built and tested artifact. Do not overwrite the site's untracked `brand/` or its unpublished commits.

## File structure

Engine: `src/krellbot/ui/launch.py` owns URL/open lifecycle, `cli.py` parses flags and calls it, `tests/test_ui_launch.py` probes that API. `scripts/freeze.py` builds an OS-specific one-dir artifact including static/keyring resources; `scripts/release_archive.py` packages it and emits a manifest. `tests/test_release_archive.py` checks archive/manifest rules. `.github/workflows/release-frozen.yml` builds native runners. `README.md`, `SECURITY.md`, and `docs/getting-started.md` document install, uninstall and unsigned status.

Site: `functions/api/install.js` selects pinned artifact metadata and renders sh/PowerShell scripts; `tests/functions/install.test.mjs` covers failure and execution fixtures; `site/index.html` and `site/docs/getting-started.html` advertise only verified release targets. Changes to the site require a separate review/commit in its own worktree.

## Review Focus

1. A valid hash with a wrong architecture must fail before replacing a working install; assert target selection and unchanged old launcher in Task 3.
2. Archive traversal or symlink escape must fail without writing outside staging; assert member validation in Task 2 and installer tests in Task 3.
3. Browser opener fails or is absent: CLI prints the current token URL and keeps serving; assert Task 1.
4. New artifact crashes during health check: installation rolls back, retains old version and data; assert Task 3.
5. Installer run twice or interrupted midway: preserves one usable launcher and does not delete data; assert Task 3.

---

### Task 1: Injectable local UI opening

**Files:** Create `src/krellbot/ui/launch.py`, `tests/test_ui_launch.py`; modify `src/krellbot/cli.py:1482-1529`.

**Interfaces:** Consumes `DashboardServer(home: Path, port: int)` with `.start()`, `.stop()`, `.bound_port`, `.token`. Produces `open_url(server: DashboardServer, opener: Callable[[str], bool]) -> str` and `cmd_ui(args)` accepting `--open` alongside `--port`.

- [ ] **Step 1: Write failing tests.** Use an injected opener, not the real browser:

```python
def test_open_url_uses_current_server_token(tmp_path):
    from krellbot.ui.launch import open_url
    from krellbot.ui.server import DashboardServer
    server = DashboardServer(home=tmp_path, port=0)
    server.start()
    try:
        seen = []
        url = open_url(server, lambda value: seen.append(value) or True)
        assert seen == [url]
        assert url == f"http://127.0.0.1:{server.bound_port}/{server.token}/"
    finally:
        server.stop()


def test_browser_failure_preserves_url(tmp_path):
    from krellbot.ui.launch import open_url
    from krellbot.ui.server import DashboardServer
    server = DashboardServer(home=tmp_path, port=0)
    server.start()
    try:
        url = open_url(server, lambda _: False)
        assert server.token in url and server.bound_port
    finally:
        server.stop()
```

- [ ] **Step 2: Run** `uv run pytest -q tests/test_ui_launch.py`; expect an import failure.
- [ ] **Step 3: Implement** `open_url` by constructing the URL from the started server, attempting `opener(url)` inside a narrow exception handler, and returning the URL regardless. In `cmd_ui`, parse `--open` explicitly, start the server, call `open_url(server, webbrowser.open)` only for that flag, then print the current URL and retain the existing signal/shutdown loop. Do not put a reusable token on disk:

```python
def open_url(server, opener):
    url = f"http://127.0.0.1:{server.bound_port}/{server.token}/"
    try:
        opener(url)
    except (OSError, RuntimeError):
        pass
    return url
```

- [ ] **Step 4: Run** `uv run pytest -q tests/test_ui_launch.py tests/test_ui_server.py tests/test_legacy_cli.py`; expect PASS. Add a CLI flag test that rejects unknown `--host` and verifies no second browser call on `ui` without `--open`.
- [ ] **Step 5: Commit** `git add src/krellbot/ui/launch.py src/krellbot/cli.py tests/test_ui_launch.py && git commit -m "feat: open gated local UI on request"`.

### Task 2: Frozen artifact and immutable manifest

**Files:** Create `scripts/freeze.py`, `scripts/release_archive.py`, `tests/test_release_archive.py`, `.github/workflows/release-frozen.yml`; modify `pyproject.toml` dev group only if builder dependencies must be locked.

**Interfaces:** Produces `build_archive(dist: Path, output: Path, *, version: str, platform_tag: str, arch: str, url: str) -> dict[str, str | int]`, returning `{url, filename, size, os, arch, version, sha256}`. Release automation supplies the pinned URL; it is never inferred from a branch tip. Site installer consumes these exact keys.

- [ ] **Step 1: Write failing tests** for a small fake one-dir tree (`krellbot` executable + `static/index.html`), stable SHA-256 and required manifest keys; reject missing executable, unknown OS/arch, absolute/traversal member paths, symlinks that escape the artifact root, and unsupported Windows `.exe` omission:

```python
def test_manifest_includes_digest_and_platform(tmp_path):
    from scripts.release_archive import build_archive
    dist = tmp_path / "dist"; dist.mkdir()
    (dist / "krellbot").write_bytes(b"fake executable")
    (dist / "static").mkdir(); (dist / "static" / "index.html").write_text("local")
    result = build_archive(dist, tmp_path / "out.zip", version="0.9.1", platform_tag="linux", arch="x86_64", url="https://example.com/releases/0.9.1/linux-x86_64.zip")
    assert result["os"] == "linux" and result["arch"] == "x86_64"
    assert len(result["sha256"]) == 64 and result["size"] > 0
```

- [ ] **Step 2: Run** `uv run pytest -q tests/test_release_archive.py`; expect import failure.
- [ ] **Step 3: Implement** `freeze.py` as a PyInstaller one-dir build with `--collect-all keyring --add-data src/krellbot/ui/static:<platform-separator>krellbot/ui/static` and explicit cryptography/jsonschema inclusion. Use the entry point `krellbot.cli:entry` via a dedicated short `scripts/frozen_main.py` that invokes `entry()`; include this file and its test in this task. In `release_archive.py`, only archive paths relative to the validated dist root, reject escaping symlinks, write a deterministic zip, compute SHA-256 over its actual bytes, and emit the manifest. Model manifest `url` as the explicit parameter above. Pin PyInstaller in the uv dev group and regenerate `uv.lock`. The CI matrix runs builds natively on macOS/Windows/Linux, checks the packaged CLI `list` command, verifies bundled local static bytes, uploads archives/manifests as artifacts, and does **not** claim code signing.

```python
# scripts/frozen_main.py
from krellbot.cli import entry
if __name__ == "__main__":
    entry()

# Inside build_archive, before writing the archive:
for member in dist.rglob("*"):
    relative = member.relative_to(dist)
    if member.is_symlink() and not member.resolve().is_relative_to(dist.resolve()):
        raise ValueError(f"escaping symlink: {relative}")
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe archive member: {relative}")
# Hash output.read_bytes() only after the zip is closed; manifest size is output.stat().st_size.
```
- [ ] **Step 4: Run** `uv run pytest -q tests/test_release_archive.py`; then `uv run python scripts/freeze.py` and invoke the built executable's `list` command in an isolated home. Confirm included static file path resolves inside the frozen directory, not the checkout. On macOS only, this proves macOS; require matching CI runs for Windows/Linux.
- [ ] **Step 5: Commit** builder, lockfile, tests, and workflow: `git add scripts pyproject.toml uv.lock tests/test_release_archive.py .github/workflows/release-frozen.yml && git commit -m "build: package versioned frozen releases"`.

### Task 3: Fail-closed site installers and rollback

**Files:** Modify `krellbot-cloud/functions/api/install.js`, `krellbot-cloud/tests/functions/install.test.mjs`; create `krellbot-cloud/functions/_release.js` for manifest validation, `krellbot-cloud/install/posix.sh` and `krellbot-cloud/install/windows.ps1` as reviewable templates.

**Interfaces:** Consumes `env.KRELLBOT_RELEASE_MANIFEST` as JSON with Task 2 keys for **each** advertised OS/arch; produces `onRequestGet(context) -> Response` with a literal URL/hash/size/version for the requested `os` and selected machine `arch` (or a script with an explicit architecture dispatch over pinned entries). Never consume a mutable manifest URL at install time. Keep existing endpoint path and `?os=mac|linux|win` contract.

- [ ] **Step 1: Replace existing wheel-oriented tests** with tests asserting missing/malformed manifest returns 503, unsupported `os` returns 400 (not mac fallback), wrong arch exits before disk writes, bad bytes report `hash mismatch`, and valid fake archive installs/opens a fake `krellbot` program under an isolated home. Inject paths/environment into sh and PowerShell test harnesses; do not use the real user home. Add a traversal member and an interrupted/failed-health archive; assert previous launcher and `$KRELLBOT_HOME` bytes remain identical. On Windows CI run the `.ps1` fixture; POSIX CI runs `.sh`.

```js
const response = await onInstallGet({
  request: {url: "https://example.com/api/install?os=linux"},
  env: {KRELLBOT_RELEASE_MANIFEST: JSON.stringify({linux: {x86_64: fixture}})},
});
assert.equal(response.status, 200);
assert.match(await response.text(), new RegExp(fixture.sha256));
```

- [ ] **Step 2: Run** `node --test tests/functions/install.test.mjs`; expect new manifest cases to fail against wheel env path.
- [ ] **Step 3: Implement** strict `_release.js` validation: HTTPS URL in production, exact OS/arch allowlist, safe archive filename, positive bounded size, `^[a-f0-9]{64}$` digest, nonempty version. Test fixtures may use `http://127.0.0.1:<port>` only. Render readable installers with literal values. POSIX uses platform-specific staging under `~/.local/share/krellbot/versions`, checks archive bytes with available `shasum -a 256` or `sha256sum` before extraction, inspects ZIP member names for absolute/`..`/drive paths and escaping symlinks, then extracts and verifies the executable with a non-network smoke command. Windows uses `%LOCALAPPDATA%\Krellbot\versions`, `Get-FileHash`, `[IO.Compression.ZipArchive]` entry inspection, `Expand-Archive`, and equivalent smoke. Select the staged version via a stable launcher only after success, then invoke `ui --open`; replace prior launchers atomically and preserve old version/data on failure. No `pip`, `venv`, or prerequisite `python3` in scripts. Add a verified uninstall path that leaves data in place.

```js
// functions/_release.js — reject ambiguous or mutable install coordinates.
export function validate(entry) {
  if (!entry || typeof entry !== "object") throw new TypeError("missing release");
  if (!/^[a-f0-9]{64}$/.test(entry.sha256)) throw new TypeError("bad digest");
  if (!Number.isSafeInteger(entry.size) || entry.size < 1) throw new TypeError("bad size");
  if (!/^[A-Za-z0-9._-]+\\.zip$/.test(entry.filename)) throw new TypeError("bad filename");
  const url = new URL(entry.url);
  if (url.protocol !== "https:" && !(url.protocol === "http:" && url.hostname === "127.0.0.1"))
    throw new TypeError("bad artifact origin");
  if (url.pathname.split("/").at(-1) !== entry.filename) throw new TypeError("filename mismatch");
  return entry;
}
```

```sh
# Installer core: no extraction, launcher replacement, or executable invocation before verification.
if command -v shasum >/dev/null 2>&1; then got=$(shasum -a 256 "$archive" | cut -d ' ' -f 1)
else got=$(sha256sum "$archive" | cut -d ' ' -f 1); fi
[ "$got" = "$expected_sha256" ] || { printf '%s\\n' 'hash mismatch' >&2; exit 1; }
# Reject every member path outside the staging root, including symlinks; only then extract.
```

```powershell
$got = (Get-FileHash -Algorithm SHA256 -Path $archive).Hash.ToLowerInvariant()
if ($got -ne $expectedSha256) { throw 'hash mismatch' }
# Inspect ZipArchive.Entries for rooted paths, dot-dot segments and reparse/symlink flags;
# Expand-Archive only into a fresh staging directory after this check.
```
- [ ] **Step 4: Run** `node --test tests/functions/install.test.mjs` on macOS and the full `node --test tests/functions/*.test.mjs`; confirm Windows fixture in Windows CI. Read the generated script once and ensure values are shell-escaped, no untrusted download executes before hash comparison, and no user data path is deleted.
- [ ] **Step 5: Commit only the isolated site worktree** with `git add functions/api/install.js functions/_release.js install/posix.sh install/windows.ps1 tests/functions/install.test.mjs && git commit -m "feat: verify and install frozen local releases"`.

### Task 4: Docs, readiness, deployment gate

**Files:** Modify engine `README.md`, `SECURITY.md`, `docs/getting-started.md`, `docs/dashboard.md`, `docs/service.md`, `src/krellbot/doctor.py`, `tests/test_service_doctor.py`; site `site/index.html`, `site/docs/getting-started.html`, `site/docs/security.html`.

**Interfaces:** Consumes existing `doctor.run(...) -> tuple[int, str]`; produces separate `install_ready` and `trading_ready` fields in JSON without suppressing current warnings or changing `ok` without a documented compatibility decision.

- [ ] **Step 1: Write a failing doctor test** showing fresh home with a usable keyring and bind is `install_ready=True` but `trading_ready=False` because keys/tick are absent; ensure null/fail keyring is never `install_ready=True`. Add site text test verifying no unsupported one-liner is advertised and unsigned status is stated. Run `uv run pytest -q tests/test_service_doctor.py` and site `node --test tests/functions/install.test.mjs`; expect failures.
- [ ] **Step 2: Implement the readiness fields** in `doctor.run` using existing `_home_mode_ok`, `_keychain_backend`, scheduler availability and a local bind probe (bind port 0, close in `finally`) without contacting any venue. `trading_ready` depends on venue permission and tick condition; retain existing warning semantics. Do not use `service_installed` as the test of mere availability.

```python
# In doctor.run after backend and key statuses are known. Implement _ui_bind_available
# with socket.socket(), bind(("127.0.0.1", 0)), and close() in finally.
install_ready = home_mode_ok is not False and backend_warn is None and _ui_bind_available()
trading_ready = install_ready and not last_tick_stale and any(
    info.get("present") and info.get("trade") is True and info.get("withdraw") is False
    for info in keys.values()
)
report["install_ready"] = install_ready
report["trading_ready"] = trading_ready
```

`_keys_status` reports `trade` and `withdraw` only when a permission probe runs. Unknown permissions must not make `trading_ready` true.
- [ ] **Step 3: Update docs and site copy** to distinguish the frozen, checksummed transport from platform signing; list binary location, PATH check, uninstall, retained data, release update policy, and manual code-signing status. Published pages must match actual delivered artifacts and CDN endpoint; gate publication by CI artifact matrix and the site's configured pinned metadata. Never mark the primary domain working merely because `pages.dev` returns 200.
- [ ] **Step 4: Run** `uv run pytest -q`, `node --test tests/functions/*.test.mjs`, engine frozen smoke and live endpoint request for each advertised OS after deployment. Read back exact endpoint scripts and verify embedded version/hash matches the uploaded artifact manifest; smoke install on clean Mac/Windows/Linux machines before claiming three-platform completion. Report unavailable machines/artifacts explicitly.
- [ ] **Step 5: Commit** engine and site docs/tests separately in their worktrees; publish only after release artifacts and review are verified. Do not merge site ahead-of-origin work implicitly.
