"""Static serving for the built frontend shell.

The Vite build emits absolute ``/assets/...`` URLs into ``index.html``
and the JS bundle. The FastAPI app mounts two routes that satisfy those
URLs without round-tripping through the token-gated dashboard server:

* ``GET /`` returns ``frontend/dist/index.html`` with
  ``Content-Type: text/html`` and ``Cache-Control: no-store``. The
  shell never caches so a freshly-built bundle is picked up on the
  next reload.

* ``GET /assets/<file>`` returns ``frontend/dist/assets/<file>`` with a
  content type derived from the extension. Path traversal (``..``),
  absolute paths, and missing files are 404 with no read outside
  ``frontend/dist``.

A missing ``index.html`` returns 404 with a closed JSON shape
``{"code": "shell_not_built"}``. The static layer never synthesises
the file: the user runs ``npm --prefix frontend run build``.

The static mount does not intercept ``/api/*``; the loopback API
itself owns those routes.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, Response

SHELL_NOT_BUILT_CODE = "shell_not_built"


def _index_path(dist_dir: Path) -> Path:
    return dist_dir / "index.html"


def _assets_dir(dist_dir: Path) -> Path:
    return dist_dir / "assets"


def serve_index(dist_dir: Path) -> Response:
    """Return the built ``index.html`` or a ``shell_not_built`` 404.

    Caching is disabled (``Cache-Control: no-store``) so a freshly
    built bundle replaces the previous one on the next reload.
    """

    path = _index_path(dist_dir)
    if not path.is_file():
        return JSONResponse({"code": SHELL_NOT_BUILT_CODE}, status_code=404)
    return FileResponse(
        path,
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


def register(app: FastAPI, dist_dir: Path) -> None:
    """Mount ``GET /`` and ``GET /assets/{file_name}`` on ``app``."""

    @app.get("/")
    def _index() -> Response:
        return serve_index(dist_dir)

    @app.get("/assets/{file_name}")
    def _asset(file_name: str) -> Response:
        return serve_asset(dist_dir, file_name)
