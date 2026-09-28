"""Static serving for the built frontend shell.

The Vite build emits absolute ``/assets/...`` URLs into ``index.html``
and the JS bundle. The FastAPI app mounts two routes that satisfy those
URLs without round-tripping through the token-gated dashboard server:

* ``GET /`` returns ``frontend/dist/index.html`` with
  ``Content-Type: text/html`` and ``Cache-Control: no-store``. The
  shell never caches so a freshly-built bundle is picked up on the
  next reload. The response body is annotated with
  ``<meta name="krellbot-bootstrap" content="...">`` carrying the
  one-time bootstrap token the JS bundle exchanges at
  ``/api/v1/session/bootstrap``. The token is injected at response
  time and never written to ``frontend/dist/index.html``.

* ``GET /assets/<file>`` returns ``frontend/dist/assets/<file>`` with a
  content type derived from the extension. Path traversal (``..``),
  absolute paths, and missing files are 404 with no read outside
  ``frontend/dist``.

A missing ``index.html`` returns 404 with a closed JSON shape
``{"code": "shell_not_built"}``. The static layer never synthesises
the file: the user runs ``npm --prefix frontend run build``. When the
build is missing the bootstrap token is not leaked into the response
body either; the 404 body is the closed JSON shape only.

The static mount does not intercept ``/api/*``; the loopback API
itself owns those routes.
"""

from __future__ import annotations

import html
import mimetypes
import re
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, Response

SHELL_NOT_BUILT_CODE = "shell_not_built"

# Match the opening ``<head>`` tag, with or without attributes. The
# Vite-emitted index.html uses the no-attribute form; the attribute
# match keeps us safe against future build changes.
_HEAD_OPEN_RE = re.compile(r"<head(\s[^>]*)?>", re.IGNORECASE)


def _index_path(dist_dir: Path) -> Path:
    return dist_dir / "index.html"


def _assets_dir(dist_dir: Path) -> Path:
    return dist_dir / "assets"


def _inject_bootstrap_meta(content: str, bootstrap_token: str) -> str:
    """Return ``content`` plus the bootstrap meta tag inside ``<head>``.

    The meta tag is the only injection. No ``<script>``, no inline
    JavaScript, no ``localStorage`` mention — the JS bundle handles
    redemption. The token is HTML-escaped before it lands in the
    attribute, so a malicious ``bootstrap_token`` cannot break out
    of the quoted attribute and inject markup.
    """

    escaped = html.escape(bootstrap_token, quote=True)
    meta_tag = f'<meta name="krellbot-bootstrap" content="{escaped}">'
    match = _HEAD_OPEN_RE.search(content)
    if match is None:
        # No <head>: prepend the meta tag. The bundle will still render
        # because the <body> is intact, and the JS looks up the tag by
        # ``name`` attribute, not by position.
        return meta_tag + content
    insert_at = match.end()
    return content[:insert_at] + meta_tag + content[insert_at:]


def serve_index(dist_dir: Path, bootstrap_token: str | None = None) -> Response:
    """Return the built ``index.html`` or a ``shell_not_built`` 404.

    Caching is disabled (``Cache-Control: no-store``) so a freshly
    built bundle replaces the previous one on the next reload. When
    ``bootstrap_token`` is supplied, the served HTML is annotated
    with the bootstrap meta tag; the on-disk file is never modified.
    """

    path = _index_path(dist_dir)
    if not path.is_file():
        return JSONResponse({"code": SHELL_NOT_BUILT_CODE}, status_code=404)
    if bootstrap_token is None:
        return FileResponse(
            path,
            media_type="text/html; charset=utf-8",
            headers={"Cache-Control": "no-store"},
        )
    content = path.read_text(encoding="utf-8")
    injected = _inject_bootstrap_meta(content, bootstrap_token)
    return Response(
        content=injected,
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


def _resolve_asset(dist_dir: Path, file_name: str) -> Path | None:
    """Return a safe resolved asset path, or ``None`` if it is unsafe.

    Rejects:

    * empty file names;
    * absolute paths (``/etc/passwd`` or ``C:\\Windows\\…``);
    * any segment equal to ``..`` (``../foo``, ``foo/..``, ``..``);
    * files that do not exist on disk;
    * files that resolve outside ``dist_dir/assets`` even after the
      ``..`` check (defence in depth).
    """

    if not file_name:
        return None
    if Path(file_name).is_absolute():
        return None
    parts = Path(file_name).parts
    if any(segment == ".." for segment in parts):
        return None
    assets_root = _assets_dir(dist_dir).resolve()
    candidate = (assets_root / file_name).resolve()
    try:
        candidate.relative_to(assets_root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


def serve_asset(dist_dir: Path, file_name: str) -> Response:
    """Serve a single file from ``frontend/dist/assets``.

    Any unsafe file name (``..``, absolute, missing, outside the
    assets directory) is a 404 with an empty body.
    """

    path = _resolve_asset(dist_dir, file_name)
    if path is None:
        return Response(status_code=404)
    media_type, _ = mimetypes.guess_type(str(path))
    return FileResponse(path, media_type=media_type or "application/octet-stream")


def register(
    app: FastAPI,
    dist_dir: Path,
    *,
    bootstrap_token: str | None = None,
) -> None:
    """Mount ``GET /`` and ``GET /assets/{file_name}`` on ``app``.

    When ``bootstrap_token`` is supplied, ``GET /`` annotates the
    served HTML with the bootstrap meta tag. The token is never
    written to disk; it is captured by closure so every response
    reads the current process token.
    """

    @app.get("/")
    def _index() -> Response:
        return serve_index(dist_dir, bootstrap_token)

    @app.get("/assets/{file_name}")
    def _asset(file_name: str) -> Response:
        return serve_asset(dist_dir, file_name)
