"""Filesystem path helpers (shared cache-dir resolution).

Consolidates the DATA_CACHE_DIR resolution used by finmind.py, twse_scraper.py
and backtest.universe. Previously each call site duplicated the env-lookup and
Docker-path default (``/app/data/cache``); only twse_scraper had a project-root
fallback for local (Windows) development. That asymmetry caused
``HistoricalUniverse`` to silently see 0 cached OHLCV files when ``DATA_CACHE_DIR``
was unset on a workstation — the universe then fell back to stock_info order
and produced garbage rankings without any error.
"""

from __future__ import annotations

import os
import pathlib


def resolve_cache_dir() -> pathlib.Path:
    """Return the canonical data cache directory.

    Resolution order:
      1. ``$DATA_CACHE_DIR`` env var, if the path exists.
      2. Docker mount default ``/app/data/cache`` if it exists.
      3. Project-root fallback ``<repo>/data/cache`` (for local dev).

    Unlike the previous ``os.environ.get("DATA_CACHE_DIR", "/app/data/cache")``
    pattern, this never silently returns a non-existent path that then reads as
    "0 cached files". The caller gets a path that actually exists, or the
    project-root fallback that the repo creates on first run.
    """
    env = os.environ.get("DATA_CACHE_DIR")
    if env:
        p = pathlib.Path(env)
        if p.exists():
            return p
    docker_default = pathlib.Path("/app/data/cache")
    if docker_default.exists():
        return docker_default
    # Project-root fallback: this file is src/utils/paths.py → parents[2] = repo root
    return pathlib.Path(__file__).resolve().parents[2] / "data" / "cache"
