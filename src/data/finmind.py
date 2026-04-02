"""FinMind data source wrapper for Taiwan stocks with persistent disk caching.

Historical market data is immutable — yesterday's close never changes.
A disk-based cache (pickle files under ``data/cache/``) stores all fetched
DataFrames so that repeated backtests incur zero API calls after the first
successful run.  Only truly new data (the gap between the cached max-date
and today) is fetched from the API.
"""

from __future__ import annotations

import logging
import os
import pathlib
import time as _time
from datetime import datetime, timedelta

import pandas as pd

from .base import DataSource
from ..utils.constants import TW_TZ

logger = logging.getLogger(__name__)

MARKET_OPEN_HOUR = 9
MARKET_OPEN_MIN = 0
MARKET_CLOSE_HOUR = 13
MARKET_CLOSE_MIN = 30

# First fetch covers ~11 years — the slicer requests limit=2000 (×1.8 = 3600 days).
_WIDE_LOOKBACK_DAYS = 4000


# ---------------------------------------------------------------------------
# Persistent disk cache
# ---------------------------------------------------------------------------

class _DiskCache:
    """Append-only persistent cache using pickle files.

    Layout::

        cache_dir/
          ohlcv/2330.pkl          # per-symbol time-series
          institutional/2330.pkl
          revenue/2330.pkl
          stock_info/_global.pkl  # snapshot datasets
          stock_info/_global.meta # date string for TTL expiry
    """

    def __init__(self, cache_dir: str | pathlib.Path):
        self._dir = pathlib.Path(cache_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._mem: dict[str, pd.DataFrame] = {}

    def _path(self, dataset: str, symbol: str = "_global") -> pathlib.Path:
        subdir = self._dir / dataset
        subdir.mkdir(exist_ok=True)
        safe = symbol.replace("/", "_").replace("\\", "_")
        return subdir / f"{safe}.pkl"

    def load(self, dataset: str, symbol: str = "_global") -> pd.DataFrame | None:
        key = f"{dataset}:{symbol}"
        if key in self._mem:
            return self._mem[key]
        path = self._path(dataset, symbol)
        if not path.exists():
            return None
        try:
            df = pd.read_pickle(path)
            self._mem[key] = df
            return df
        except Exception:
            path.unlink(missing_ok=True)
            return None

    def save(self, dataset: str, df: pd.DataFrame, symbol: str = "_global") -> None:
        key = f"{dataset}:{symbol}"
        self._mem[key] = df
        try:
            df.to_pickle(self._path(dataset, symbol))
        except Exception as exc:
            logger.warning("Disk cache write failed: %s", exc)

    # Lightweight metadata sidecar for TTL-based datasets.
    def meta(self, dataset: str, symbol: str = "_global") -> str | None:
        p = self._path(dataset, symbol).with_suffix(".meta")
        return p.read_text().strip() if p.exists() else None

    def save_meta(self, dataset: str, date_str: str, symbol: str = "_global") -> None:
        try:
            self._path(dataset, symbol).with_suffix(".meta").write_text(date_str)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# In-memory cache for ephemeral non-DataFrame values
# ---------------------------------------------------------------------------

class _SimpleCache:
    """Same-day in-memory cache (booleans, scalars)."""

    def __init__(self):
        self._store: dict[str, tuple[str, object]] = {}

    def get(self, key: str) -> object | None:
        today = datetime.now(TW_TZ).strftime("%Y-%m-%d")
        e = self._store.get(key)
        return e[1] if e and e[0] == today else None

    def set(self, key: str, value: object) -> None:
        self._store[key] = (datetime.now(TW_TZ).strftime("%Y-%m-%d"), value)


# ---------------------------------------------------------------------------
# FinMind data source
# ---------------------------------------------------------------------------

class FinMindSource(DataSource):
    """Fetch Taiwan stock datasets from FinMind with rate limiting and
    persistent disk caching.

    Parameters
    ----------
    cache_dir : str, optional
        Override the cache directory.  Defaults to ``DATA_CACHE_DIR`` env var
        or ``/app/data/cache`` (the Docker volume mount).
    """

    def __init__(
        self,
        token: str | None = None,
        request_interval: float = 0.5,
        use_adjusted: bool = True,
        cache_dir: str | None = None,
    ):
        from FinMind.data import DataLoader

        self.loader = DataLoader()
        self._request_interval = request_interval
        self._last_request_time: float = 0.0
        self._simple_cache = _SimpleCache()
        self._use_adjusted = use_adjusted

        if cache_dir is None:
            cache_dir = os.environ.get("DATA_CACHE_DIR", "/app/data/cache")
        self._disk = _DiskCache(cache_dir)

        if token:
            self.loader.login_by_token(api_token=token)
            logger.info("FinMind token login completed")
        else:
            logger.info("FinMind token not provided; continuing with default client state")

    # ---------------------------------------------------------------- helpers

    def _rate_limit(self) -> None:
        """Ensure at least ``request_interval`` seconds between API calls."""
        elapsed = _time.monotonic() - self._last_request_time
        if elapsed < self._request_interval:
            _time.sleep(self._request_interval - elapsed)
        self._last_request_time = _time.monotonic()

    @staticmethod
    def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
        """Standardize FinMind daily DataFrame into OHLCV format."""
        df = df.rename(columns={
            "date": "timestamp", "max": "high", "min": "low",
            "Trading_Volume": "volume",
        })
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.set_index("timestamp").sort_index()
        for col in ("open", "high", "low", "close", "volume"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df

    @staticmethod
    def _ts_naive(ts: pd.Timestamp) -> pd.Timestamp:
        return ts.tz_localize(None) if ts.tzinfo else ts

    # ----------------------------------------------------------------- OHLCV

    def _api_fetch_ohlcv(self, symbol: str, start: str, end: str) -> pd.DataFrame | None:
        """Raw API call — tries adjusted price then falls back to unadjusted."""
        df = None
        if self._use_adjusted:
            df = self._fetch_adjusted_daily(symbol, start, end)
        if df is None or df.empty:
            self._rate_limit()
            try:
                df = self.loader.taiwan_stock_daily(
                    stock_id=symbol, start_date=start, end_date=end,
                )
            except Exception as exc:
                logger.error("Failed to fetch daily data for %s: %s", symbol, exc)
                return None
        if df is None or df.empty:
            return None
        return self._normalize_ohlcv(df)

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 100) -> pd.DataFrame | None:
        if timeframe != "D":
            logger.warning("FinMind only supports daily data; requested timeframe=%s", timeframe)

        now = datetime.now()
        end_str = now.strftime("%Y-%m-%d")
        want_start = now - timedelta(days=int(limit * 1.8))
        # 容忍 3 天間隔（週五快取 → 週日不觸發向前延伸）
        stale_boundary = pd.Timestamp(now.date()) - pd.Timedelta(days=3)

        cached = self._disk.load("ohlcv", symbol)
        changed = False

        if cached is not None and not cached.empty:
            c_min = self._ts_naive(cached.index.min())
            c_max = self._ts_naive(cached.index.max())
            req_start = pd.Timestamp(want_start.date())

            # Extend backward only if cache is very sparse (< 252 rows ≈ 1 year of trading days).
            # With _WIDE_LOOKBACK_DAYS=4000, any first fetch already covers 11 years.
            # For existing symbols cached before this setting, 1000+ rows is sufficient
            # for any 3Y+ backtest — the slicer truncates to the actual backtest window.
            cached_in_range = cached[cached.index >= pd.Timestamp(want_start, tz="UTC")]
            if len(cached) < 252 and c_min > req_start + pd.Timedelta(days=1):
                old = self._api_fetch_ohlcv(
                    symbol,
                    want_start.strftime("%Y-%m-%d"),
                    (c_min - pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                )
                if old is not None and not old.empty:
                    cached = pd.concat([old, cached]).sort_index()
                    cached = cached[~cached.index.duplicated(keep="last")]
                    changed = True

            # Extend forward if cache is stale (3-day tolerance for weekends/holidays).
            # Skip if data is > 1 year old — stock is likely delisted or API unavailable.
            one_year_ago = pd.Timestamp(now.date()) - pd.Timedelta(days=365)
            if c_max < stale_boundary and c_max >= one_year_ago:
                new = self._api_fetch_ohlcv(
                    symbol,
                    (c_max + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                    end_str,
                )
                if new is not None and not new.empty:
                    cached = pd.concat([cached, new]).sort_index()
                    cached = cached[~cached.index.duplicated(keep="last")]
                    changed = True
        else:
            # First fetch — use wide lookback to cover any backtest period
            wide_start = now - timedelta(days=max(int(limit * 1.8), _WIDE_LOOKBACK_DAYS))
            cached = self._api_fetch_ohlcv(symbol, wide_start.strftime("%Y-%m-%d"), end_str)
            if cached is None or cached.empty:
                return None
            changed = True

        if changed:
            self._disk.save("ohlcv", cached, symbol)

        # Slice to the requested range
        start_ts = pd.Timestamp(want_start, tz="UTC")
        result = cached[cached.index >= start_ts]
        result = result[["open", "high", "low", "close", "volume"]].dropna().tail(limit)
        return result if not result.empty else None

    def _fetch_adjusted_daily(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame | None:
        """Try to fetch adjusted prices (handles ex-dividend, capital reduction)."""
        self._rate_limit()
        try:
            df = self.loader.taiwan_stock_daily_adj(
                stock_id=symbol, start_date=start_date, end_date=end_date,
            )
            if df is not None and not df.empty:
                logger.debug("Using adjusted price for %s", symbol)
                return df
        except (AttributeError, TypeError):
            logger.info("FinMind does not support taiwan_stock_daily_adj; adjusted prices disabled")
            self._use_adjusted = False
        except Exception as exc:
            logger.warning("Failed to fetch adjusted daily for %s: %s", symbol, exc)
            if isinstance(exc, KeyError) and str(exc) == "'data'":
                logger.info("TaiwanStockPriceAdj requires paid access; adjusted prices disabled")
                self._use_adjusted = False
        return None

    # ---------------------------------------------------------- Institutional

    def fetch_institutional(self, symbol: str, days: int = 30) -> pd.DataFrame | None:
        now = datetime.now()
        end_str = now.strftime("%Y-%m-%d")
        stale_boundary = pd.Timestamp(now.date()) - pd.Timedelta(days=3)

        cached = self._disk.load("institutional", symbol)
        changed = False

        if cached is not None:
            # 空 DataFrame = 哨兵（此 symbol 無法人資料），不重複呼叫 API
            if cached.empty:
                return None
            if "date" in cached.columns:
                c_max = pd.Timestamp(cached["date"].max())
                # 7-day tolerance (handles weekends + institutional report lag)
                inst_stale_boundary = pd.Timestamp(now.date()) - pd.Timedelta(days=7)
                one_year_ago = pd.Timestamp(now.date()) - pd.Timedelta(days=365)
                if c_max < inst_stale_boundary and c_max >= one_year_ago:
                    new_df = self._api_fetch_institutional(
                        symbol,
                        (c_max + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                        end_str,
                    )
                    if new_df is not None and not new_df.empty:
                        cached = self._merge_institutional(cached, new_df)
                        changed = True
        else:
            wide_start = now - timedelta(days=max(int(days * 1.5), _WIDE_LOOKBACK_DAYS))
            cached = self._api_fetch_institutional(
                symbol, wide_start.strftime("%Y-%m-%d"), end_str,
            )
            if cached is None or cached.empty:
                # 存入空 DataFrame 作為哨兵，避免下次再呼叫 API
                self._disk.save("institutional", pd.DataFrame(), symbol)
                return None
            changed = True

        if changed:
            self._disk.save("institutional", cached, symbol)

        return cached.sort_values("date") if (cached is not None and "date" in cached.columns) else cached

    def _api_fetch_institutional(self, symbol: str, start: str, end: str) -> pd.DataFrame | None:
        self._rate_limit()
        try:
            df = self.loader.taiwan_stock_institutional_investors(
                stock_id=symbol, start_date=start, end_date=end,
            )
        except KeyError as exc:
            if str(exc) == "'data'":
                logger.warning(
                    "Institutional dataset unavailable for %s with current FinMind access; "
                    "factor will be empty for this symbol",
                    symbol,
                )
                return None
            logger.warning("Failed to fetch institutional data for %s: %s", symbol, exc)
            return None
        except Exception as exc:
            logger.warning("Failed to fetch institutional data for %s: %s", symbol, exc)
            return None

        if df is None or df.empty:
            return None

        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        for col in ("buy", "sell"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        return df.sort_values("date")

    @staticmethod
    def _merge_institutional(old: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
        merged = pd.concat([old, new])
        dedup_cols = ["date", "name"] if "name" in merged.columns else ["date"]
        return merged.drop_duplicates(subset=dedup_cols, keep="last").sort_values("date")

    # --------------------------------------------------------- Month Revenue

    def fetch_month_revenue(self, symbol: str, months: int = 15) -> pd.DataFrame | None:
        now = datetime.now()
        end_str = now.strftime("%Y-%m-%d")

        cached = self._disk.load("revenue", symbol)
        changed = False

        if cached is not None:
            # 空 DataFrame = 哨兵（此 symbol 無營收資料）
            if cached.empty:
                return None
            if "date" in cached.columns:
                c_max = pd.Timestamp(cached["date"].max())
                # Revenue is monthly; stale if older than 45 days.
                # Skip if > 1 year old — stock likely delisted or API unavailable.
                stale_threshold = pd.Timestamp(now.date()) - pd.Timedelta(days=45)
                one_year_ago = pd.Timestamp(now.date()) - pd.Timedelta(days=365)
                if c_max < stale_threshold and c_max >= one_year_ago:
                    fetch_start = (c_max - pd.Timedelta(days=35)).strftime("%Y-%m-%d")
                    new_df = self._api_fetch_revenue(symbol, fetch_start, end_str)
                    if new_df is not None and not new_df.empty:
                        cached = pd.concat([cached, new_df]).drop_duplicates(
                            subset=["date"], keep="last",
                        ).sort_values("date")
                        changed = True
        else:
            wide_start = now - timedelta(days=max(int(months * 35), _WIDE_LOOKBACK_DAYS))
            cached = self._api_fetch_revenue(
                symbol, wide_start.strftime("%Y-%m-%d"), end_str,
            )
            if cached is None or cached.empty:
                # 存入空 DataFrame 作為哨兵
                self._disk.save("revenue", pd.DataFrame(), symbol)
                return None
            changed = True

        if changed:
            self._disk.save("revenue", cached, symbol)

        return cached

    def _api_fetch_revenue(self, symbol: str, start: str, end: str) -> pd.DataFrame | None:
        self._rate_limit()
        try:
            df = self.loader.taiwan_stock_month_revenue(
                stock_id=symbol, start_date=start, end_date=end,
            )
        except Exception as exc:
            logger.warning("Failed to fetch month revenue for %s: %s", symbol, exc)
            return None

        if df is None or df.empty:
            return None

        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date")
        if "revenue" in df.columns:
            df["revenue"] = pd.to_numeric(df["revenue"], errors="coerce")
        return df

    # ----------------------------------------------------------- Stock Info

    def fetch_stock_info(self) -> pd.DataFrame | None:
        # Snapshot dataset — cache with 7-day TTL
        cached = self._disk.load("stock_info")
        meta = self._disk.meta("stock_info")
        if cached is not None and meta:
            if (datetime.now() - datetime.strptime(meta, "%Y-%m-%d")).days < 7:
                # pickle cache 有效 — 確保 CSV 備援也存在
                self._ensure_stock_info_csv(cached)
                return cached

        self._rate_limit()
        try:
            df = self.loader.taiwan_stock_info()
        except KeyError as exc:
            if str(exc) == "'data'":
                logger.warning("Stock info dataset unavailable with current FinMind access")
            else:
                logger.warning("Failed to fetch stock info: %s", exc)
            return cached if (cached is not None and not cached.empty) else self._load_stock_info_csv_fallback()
        except Exception as exc:
            logger.warning("Failed to fetch stock info: %s", exc)
            return cached if (cached is not None and not cached.empty) else self._load_stock_info_csv_fallback()

        if df is None or df.empty:
            return cached if (cached is not None and not cached.empty) else self._load_stock_info_csv_fallback()

        result = df.copy()
        self._disk.save("stock_info", result)
        self._disk.save_meta("stock_info", datetime.now().strftime("%Y-%m-%d"))
        # 每次 API 成功後同步更新 CSV 快照，供 pickle 損壞時作為最終備援
        self._save_stock_info_csv_snapshot(result)
        return result

    def _load_stock_info_csv_fallback(self) -> pd.DataFrame | None:
        """最終備援：從本地 CSV 快照讀取 stock_info。"""
        csv_path = self._disk._dir / "stock_info" / "stock_info_snapshot.csv"
        if not csv_path.exists():
            logger.warning("No CSV fallback for stock_info at %s", csv_path)
            return None
        try:
            df = pd.read_csv(csv_path, dtype=str)
            logger.info("Loaded stock_info from CSV fallback (%d rows)", len(df))
            return df
        except Exception as exc:
            logger.warning("Failed to read stock_info CSV fallback: %s", exc)
            return None

    def _save_stock_info_csv_snapshot(self, df: pd.DataFrame) -> None:
        """將 stock_info 存為 CSV 快照（UTF-8），供 pickle 備援。"""
        try:
            csv_path = self._disk._dir / "stock_info" / "stock_info_snapshot.csv"
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(csv_path, index=False, encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to save stock_info CSV snapshot: %s", exc)

    def _ensure_stock_info_csv(self, df: pd.DataFrame) -> None:
        """確保 CSV 備援存在；已存在則跳過，避免每次 cache hit 都寫磁碟。"""
        csv_path = self._disk._dir / "stock_info" / "stock_info_snapshot.csv"
        if not csv_path.exists():
            logger.info("CSV snapshot missing — creating from pickle cache")
            self._save_stock_info_csv_snapshot(df)

    # --------------------------------------------------------- Market Value

    def fetch_market_value(self, days: int = 10) -> pd.DataFrame | None:
        # Snapshot dataset — cache with 1-day TTL
        cached = self._disk.load("market_value")
        meta = self._disk.meta("market_value")
        if cached is not None and meta:
            if (datetime.now() - datetime.strptime(meta, "%Y-%m-%d")).days < 1:
                return cached

        end_date = datetime.now()
        start_date = end_date - timedelta(days=max(days, 5))

        self._rate_limit()
        try:
            df = self.loader.taiwan_stock_market_value(
                start_date=start_date.strftime("%Y-%m-%d"),
                end_date=end_date.strftime("%Y-%m-%d"),
            )
        except KeyError as exc:
            if str(exc) == "'data'":
                logger.warning("Market value dataset unavailable with current FinMind access")
            else:
                logger.warning("Failed to fetch market value: %s", exc)
            return cached
        except Exception as exc:
            logger.warning("Failed to fetch market value: %s", exc)
            return cached

        if df is None or df.empty:
            return cached

        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        if "market_value" in df.columns:
            df["market_value"] = pd.to_numeric(df["market_value"], errors="coerce")

        result = df.sort_values(["stock_id", "date"]).dropna(subset=["stock_id"])
        self._disk.save("market_value", result)
        self._disk.save_meta("market_value", datetime.now().strftime("%Y-%m-%d"))
        return result

    # -------------------------------------------------------------- Delisting

    def fetch_delisting(self) -> pd.DataFrame | None:
        cached = self._disk.load("delisting")
        meta = self._disk.meta("delisting")
        if cached is not None and meta:
            if (datetime.now() - datetime.strptime(meta, "%Y-%m-%d")).days < 7:
                return cached

        self._rate_limit()
        try:
            df = self.loader.taiwan_stock_delisting()
            if df is not None and not df.empty:
                self._disk.save("delisting", df)
                self._disk.save_meta("delisting", datetime.now().strftime("%Y-%m-%d"))
                return df
        except (AttributeError, TypeError):
            logger.info("FinMind does not support taiwan_stock_delisting")
        except Exception as exc:
            logger.warning("Failed to fetch delisting data: %s", exc)
        return cached

    # -------------------------------------------------------- Financial quality

    def fetch_financial_quality(self, symbol: str) -> dict | None:
        """取得最新一季的品質指標（ROE、毛利率）。

        使用 FinMind TaiwanStockFinancialStatements + TaiwanStockBalanceSheet。
        快取 90 天（季報每季才更新）。
        """
        cache_key = f"quality:{symbol}"
        cached = self._disk.load("quality", symbol)
        meta = self._disk.meta("quality", symbol)
        if cached is not None and meta:
            try:
                if (datetime.now() - datetime.strptime(meta, "%Y-%m-%d")).days < 90:
                    # cached is a pickle of dict
                    return cached.to_dict("records")[0] if hasattr(cached, "to_dict") else cached
            except Exception:
                pass

        self._rate_limit()
        try:
            start = (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d")
            fs = self.loader.taiwan_stock_financial_statement(stock_id=symbol, start_date=start)
            if fs is None or fs.empty:
                return None

            self._rate_limit()
            bs = self.loader.taiwan_stock_balance_sheet(stock_id=symbol, start_date=start)
            if bs is None or bs.empty:
                return None

            # 取最新一季
            latest_date = fs["date"].max()
            fs_latest = fs[fs["date"] == latest_date]
            bs_latest = bs[bs["date"] == latest_date]

            def _get(df, type_key):
                rows = df[df["type"] == type_key]
                if rows.empty:
                    return None
                return float(rows.iloc[-1]["value"])

            revenue = _get(fs_latest, "Revenue")
            gross_profit = _get(fs_latest, "GrossProfit")
            net_income = _get(fs_latest, "IncomeAfterTaxes")
            equity = _get(bs_latest, "Equity")

            result = {
                "date": str(latest_date),
                "roe": (net_income / equity * 4) if equity and net_income and equity > 0 else None,
                "gross_margin": (gross_profit / revenue) if revenue and gross_profit and revenue > 0 else None,
            }

            # 存快取（用 DataFrame 包裝以相容 _DiskCache）
            import pandas as _pd
            self._disk.save("quality", _pd.DataFrame([result]), symbol)
            self._disk.save_meta("quality", datetime.now().strftime("%Y-%m-%d"), symbol)
            return result

        except Exception as exc:
            logger.debug("Failed to fetch financial quality for %s: %s", symbol, exc)
            return None

    # --------------------------------------------------------- Market status

    def is_market_open(self) -> bool:
        now = datetime.now(TW_TZ)
        if now.weekday() >= 5:
            return False
        if not self.is_trading_day():
            return False
        market_open = now.replace(hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MIN, second=0, microsecond=0)
        market_close = now.replace(hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MIN, second=0, microsecond=0)
        return market_open <= now <= market_close

    def is_trading_day(self) -> bool:
        """Check if today is a trading day by querying 0050 recent data.

        Only caches True; False is retried each cycle in case data hasn't
        been published yet.
        """
        now = datetime.now(TW_TZ)
        if now.weekday() >= 5:
            return False

        cache_key = "is_trading_day"
        cached = self._simple_cache.get(cache_key)
        if cached is not None:
            return cached

        today_str = now.strftime("%Y-%m-%d")
        start_date = (now - timedelta(days=10)).strftime("%Y-%m-%d")
        try:
            self._rate_limit()
            df = self.loader.taiwan_stock_daily(
                stock_id="0050",
                start_date=start_date,
                end_date=today_str,
            )
            if df is not None and not df.empty and "date" in df.columns:
                trading_dates = set(str(d)[:10] for d in df["date"])
                is_today_trading = today_str in trading_dates
                if is_today_trading:
                    self._simple_cache.set(cache_key, True)
                return is_today_trading
        except Exception as exc:
            logger.warning("Failed to check trading day via market data: %s", exc)

        return False
