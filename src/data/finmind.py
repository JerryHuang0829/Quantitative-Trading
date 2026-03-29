"""FinMind data source wrapper for Taiwan stocks."""

from __future__ import annotations

import logging
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


class _SimpleCache:
    """當日有效的簡易記憶體 cache，避免重複 API 呼叫。"""

    def __init__(self):
        self._store: dict[str, tuple[str, object]] = {}

    def get(self, key: str) -> object | None:
        today = datetime.now(TW_TZ).strftime("%Y-%m-%d")
        entry = self._store.get(key)
        if entry and entry[0] == today:
            return entry[1]
        return None

    def set(self, key: str, value: object) -> None:
        today = datetime.now(TW_TZ).strftime("%Y-%m-%d")
        self._store[key] = (today, value)


class FinMindSource(DataSource):
    """Fetch Taiwan stock datasets from FinMind with rate limiting and caching."""

    def __init__(self, token: str | None = None, request_interval: float = 0.5, use_adjusted: bool = True):
        from FinMind.data import DataLoader

        self.loader = DataLoader()
        self._request_interval = request_interval
        self._last_request_time: float = 0.0
        self._cache = _SimpleCache()
        self._use_adjusted = use_adjusted

        if token:
            self.loader.login_by_token(api_token=token)
            logger.info("FinMind token login completed")
        else:
            logger.info("FinMind token not provided; continuing with default client state")

    def _rate_limit(self) -> None:
        """確保兩次 API 呼叫之間至少間隔 request_interval 秒。"""
        elapsed = _time.monotonic() - self._last_request_time
        if elapsed < self._request_interval:
            _time.sleep(self._request_interval - elapsed)
        self._last_request_time = _time.monotonic()

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 100) -> pd.DataFrame | None:
        if timeframe != "D":
            logger.warning("FinMind only supports daily data here; requested timeframe=%s", timeframe)

        cache_key = f"ohlcv:{symbol}:{timeframe}:{limit}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        end_date = datetime.now()
        start_date = end_date - timedelta(days=int(limit * 1.8))
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")

        df = None

        # P0-2: 優先使用還原後股價（處理除權息、減資、分割）
        if self._use_adjusted:
            df = self._fetch_adjusted_daily(symbol, start_str, end_str)

        # Fallback: 若還原價不可用，使用一般日線並警告
        if df is None or df.empty:
            if self._use_adjusted:
                logger.warning(
                    "Adjusted price unavailable for %s; falling back to unadjusted daily",
                    symbol,
                )
            self._rate_limit()
            try:
                df = self.loader.taiwan_stock_daily(
                    stock_id=symbol,
                    start_date=start_str,
                    end_date=end_str,
                )
            except Exception as exc:
                logger.error("Failed to fetch daily data for %s: %s", symbol, exc)
                return None

        if df is None or df.empty:
            return None

        df = self._normalize_ohlcv(df)
        result = df[["open", "high", "low", "close", "volume"]].dropna().tail(limit)
        self._cache.set(cache_key, result)
        return result

    def _fetch_adjusted_daily(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame | None:
        """嘗試取得還原後股價（TaiwanStockPriceAdj）。"""
        self._rate_limit()
        try:
            df = self.loader.taiwan_stock_daily_adj(
                stock_id=symbol,
                start_date=start_date,
                end_date=end_date,
            )
            if df is not None and not df.empty:
                logger.debug("Using adjusted price for %s", symbol)
                return df
        except (AttributeError, TypeError):
            # FinMind 版本不支援此方法
            logger.info("FinMind does not support taiwan_stock_daily_adj; adjusted prices disabled")
            self._use_adjusted = False
        except Exception as exc:
            logger.warning("Failed to fetch adjusted daily for %s: %s", symbol, exc)
            # 若為 KeyError('data') 代表此 dataset 需付費，停止後續嘗試
            if isinstance(exc, KeyError) and str(exc) == "'data'":
                logger.info("TaiwanStockPriceAdj requires paid access; adjusted prices disabled")
                self._use_adjusted = False
        return None

    @staticmethod
    def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
        """將 FinMind 日線 DataFrame 統一為標準 OHLCV 格式。"""
        df = df.rename(
            columns={
                "date": "timestamp",
                "max": "high",
                "min": "low",
                "Trading_Volume": "volume",
            }
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.set_index("timestamp").sort_index()

        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        return df

    def fetch_institutional(self, symbol: str, days: int = 30) -> pd.DataFrame | None:
        cache_key = f"inst:{symbol}:{days}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        end_date = datetime.now()
        start_date = end_date - timedelta(days=int(days * 1.5))

        self._rate_limit()
        try:
            df = self.loader.taiwan_stock_institutional_investors(
                stock_id=symbol,
                start_date=start_date.strftime("%Y-%m-%d"),
                end_date=end_date.strftime("%Y-%m-%d"),
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
        for col in ["buy", "sell"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

        # FinMind 每個交易日會有多個法人別列（如外資、投信、自營商），
        # 這裡若用 .tail(days) 會按「列數」而不是「交易日數」截斷，
        # 造成實際覆蓋期間大幅短於預期。直接保留 API 視窗內的完整資料，
        # 由上游依 as_of/unique date 再做截斷。
        result = df.sort_values("date")
        self._cache.set(cache_key, result)
        return result

    def fetch_month_revenue(self, symbol: str, months: int = 15) -> pd.DataFrame | None:
        cache_key = f"rev:{symbol}:{months}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        end_date = datetime.now()
        start_date = end_date - timedelta(days=int(months * 35))

        self._rate_limit()
        try:
            df = self.loader.taiwan_stock_month_revenue(
                stock_id=symbol,
                start_date=start_date.strftime("%Y-%m-%d"),
                end_date=end_date.strftime("%Y-%m-%d"),
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

        # 月營收通常每月一列，但仍保留 API 視窗內完整資料，
        # 由上游依 as_of/unique date 截斷，避免資料層與回測層重複裁切。
        result = df
        self._cache.set(cache_key, result)
        return result

    def fetch_stock_info(self) -> pd.DataFrame | None:
        cached = self._cache.get("stock_info")
        if cached is not None:
            return cached

        self._rate_limit()
        try:
            df = self.loader.taiwan_stock_info()
        except KeyError as exc:
            if str(exc) == "'data'":
                logger.warning(
                    "Stock info dataset unavailable with current FinMind access; "
                    "historical auto-universe cannot be reconstructed"
                )
                return None
            logger.warning("Failed to fetch stock info: %s", exc)
            return None
        except Exception as exc:
            logger.warning("Failed to fetch stock info: %s", exc)
            return None

        if df is None or df.empty:
            return None

        result = df.copy()
        self._cache.set("stock_info", result)
        return result

    def fetch_market_value(self, days: int = 10) -> pd.DataFrame | None:
        cached = self._cache.get("market_value")
        if cached is not None:
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
                logger.warning(
                    "Market value dataset unavailable with current FinMind access; "
                    "falling back to size proxy or manual ordering where supported"
                )
                return None
            logger.warning("Failed to fetch market value data: %s", exc)
            return None
        except Exception as exc:
            logger.warning("Failed to fetch market value data: %s", exc)
            return None

        if df is None or df.empty:
            return None

        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        if "market_value" in df.columns:
            df["market_value"] = pd.to_numeric(df["market_value"], errors="coerce")

        result = df.sort_values(["stock_id", "date"]).dropna(subset=["stock_id"])
        self._cache.set("market_value", result)
        return result

    def fetch_delisting(self) -> pd.DataFrame | None:
        """取得台股下市/下櫃資料（TaiwanStockDelisting）。"""
        cached = self._cache.get("delisting")
        if cached is not None:
            return cached

        self._rate_limit()
        try:
            df = self.loader.taiwan_stock_delisting()
            if df is not None and not df.empty:
                self._cache.set("delisting", df)
                return df
        except (AttributeError, TypeError):
            logger.info("FinMind does not support taiwan_stock_delisting")
        except Exception as exc:
            logger.warning("Failed to fetch delisting data: %s", exc)
        return None

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
        """透過實際市場資料判斷今天是否為交易日，無需維護假日曆。

        查詢 0050 近期日線資料，若今天有交易紀錄則為交易日。
        結果會快取一整天（僅快取 True；False 會在下個週期重試，
        以免盤後資料尚未更新時誤判）。
        """
        now = datetime.now(TW_TZ)
        if now.weekday() >= 5:
            return False

        cache_key = "is_trading_day"
        cached = self._cache.get(cache_key)
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
                # 只快取 True；False 可能是資料尚未更新，下次再試
                if is_today_trading:
                    self._cache.set(cache_key, True)
                return is_today_trading
        except Exception as exc:
            logger.warning("Failed to check trading day via market data: %s", exc)

        # Fail closed: 若資料檢查失敗，先視為非交易日，等待下個週期重試
        return False
