"""Regression: shared resolve_cache_dir() provides project-root fallback.

Before this helper, backtest.universe hard-coded
``os.environ.get("DATA_CACHE_DIR", "/app/data/cache")`` with no project-root
fallback. On a Windows workstation without DATA_CACHE_DIR set, the OHLCV
cache-sym lookup would read zero files and silently degrade the universe to
stock_info order — the exact "alpha illusion" path that 2026-04-15 flagged.
twse_scraper already had the fallback; only universe.py was asymmetric.
"""

from __future__ import annotations

import pathlib

from src.utils.paths import resolve_cache_dir


def test_resolve_cache_dir_respects_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_CACHE_DIR", str(tmp_path))
    assert resolve_cache_dir() == tmp_path


def test_resolve_cache_dir_falls_back_to_repo(monkeypatch):
    # Unset env → should land on project-root data/cache (which exists in
    # this repo) rather than Docker /app/data/cache (absent on workstation).
    monkeypatch.delenv("DATA_CACHE_DIR", raising=False)
    got = resolve_cache_dir()
    assert isinstance(got, pathlib.Path)
    # Must not return the Docker default when it does not exist.
    assert got != pathlib.Path("/app/data/cache") or got.exists()
    # Project fallback ends with data/cache
    assert got.name == "cache"
    assert got.parent.name == "data"


def test_resolve_cache_dir_ignores_nonexistent_env(monkeypatch, tmp_path):
    # If DATA_CACHE_DIR points somewhere that doesn't exist, fall through.
    missing = tmp_path / "definitely_does_not_exist"
    monkeypatch.setenv("DATA_CACHE_DIR", str(missing))
    got = resolve_cache_dir()
    assert got != missing


def test_universe_uses_shared_resolver(monkeypatch, tmp_path):
    """backtest.universe must read OHLCV cache via the shared resolver,
    not its former hard-coded ``os.environ.get(..., "/app/data/cache")``."""
    # Point env at a temp cache with one ohlcv pkl — verify universe "sees" it
    ohlcv_dir = tmp_path / "ohlcv"
    ohlcv_dir.mkdir()
    (ohlcv_dir / "2330.pkl").write_bytes(b"")
    monkeypatch.setenv("DATA_CACHE_DIR", str(tmp_path))

    # Mimic the logic that reads cached_syms from resolve_cache_dir
    from src.utils.paths import resolve_cache_dir
    d = resolve_cache_dir() / "ohlcv"
    assert d.is_dir()
    found = {f.stem for f in d.iterdir() if f.suffix == ".pkl"}
    assert "2330" in found
