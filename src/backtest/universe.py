"""Point-in-time universe reconstruction for survivorship-bias-free backtesting."""

from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd

logger = logging.getLogger(__name__)


class HistoricalUniverse:
    """重建歷史可交易 universe，避免 survivorship bias。

    使用 TaiwanStockInfo（含 IPO date）、TaiwanStockDelisting、
    以及截斷至 as_of 的市值資料來決定每個月哪些股票是可交易的。
    """

    def __init__(self, source):
        self._source = source
        self._stock_info: pd.DataFrame | None = None
        self._delisting: pd.DataFrame | None = None

    def load(self) -> None:
        """預載入全部 stock info 與 delisting 資料。"""
        self._stock_info = self._source.fetch_stock_info()
        if self._stock_info is None or self._stock_info.empty:
            raise RuntimeError(
                "Cannot load stock info for historical universe; "
                "FinMind TaiwanStockInfo is unavailable in the current environment/account"
            )

        # 嘗試載入下市資料
        if hasattr(self._source, "fetch_delisting"):
            self._delisting = self._source.fetch_delisting()
        else:
            logger.warning("Source does not support fetch_delisting; delisted stocks will be missing")
            self._delisting = pd.DataFrame()

    def get_universe_at(self, as_of: datetime, portfolio_config: dict, source=None) -> list[dict]:
        """回傳在 as_of 日期時的可交易 universe。

        Parameters
        ----------
        as_of : datetime
            回測日期
        portfolio_config : dict
            投組設定（用於過濾條件）
        source : optional
            資料來源（slicer），用於取得截斷至 as_of 的市值資料。
            若為 None 則不做市值排序。

        Returns
        -------
        list[dict]
            每個元素含 symbol, name, industry, market_value 等欄位
        """
        if self._stock_info is None:
            raise RuntimeError("Must call load() before get_universe_at()")

        working = self._stock_info.copy()

        # 過濾 IPO date — 只保留在 as_of 之前已上市的股票
        if "date" in working.columns:
            working["date"] = pd.to_datetime(working["date"], errors="coerce")
            as_of_ts = pd.Timestamp(as_of).tz_localize(None)
            working = working[working["date"] <= as_of_ts]

        # 過濾已下市的股票
        if self._delisting is not None and not self._delisting.empty:
            if "stock_id" in self._delisting.columns and "date" in self._delisting.columns:
                delisted = self._delisting.copy()
                delisted["date"] = pd.to_datetime(delisted["date"], errors="coerce")
                as_of_ts = pd.Timestamp(as_of).tz_localize(None)
                # 在 as_of 之前已下市的股票
                delisted_before = set(
                    delisted[delisted["date"] <= as_of_ts]["stock_id"].astype(str)
                )
                if "stock_id" in working.columns:
                    working = working[~working["stock_id"].astype(str).isin(delisted_before)]

        # --- 基本過濾（與 _prepare_auto_universe 相同邏輯）---
        if "stock_id" not in working.columns:
            return []

        working["stock_id"] = working["stock_id"].astype(str).str.strip()
        # 保留 4 位股票代碼，以及 00xxxx 類 6 位 ETF 家族代碼。
        # 這樣 0050 不受影響，若 exclude_etf=False 時 006208 也可保留；
        # 同時仍可擋掉 71xxxx 等 6 位權證/衍生性商品代碼。
        working = working[working["stock_id"].str.fullmatch(r"(?:\d{4}|00\d{4})")]

        # ETF 過濾
        if portfolio_config.get("exclude_etf", True):
            working = working[~working["stock_id"].str.startswith("00")]

        # 市場類型過濾
        allowed_markets = {
            str(item).lower()
            for item in portfolio_config.get("auto_universe_markets", ["twse", "tpex"])
        }
        if allowed_markets and "type" in working.columns:
            working = working[
                working["type"].astype(str).str.lower().apply(
                    lambda value: any(token in value for token in allowed_markets)
                )
            ]

        # 產業排除
        excluded_industries = [
            str(item).lower()
            for item in portfolio_config.get("auto_universe_exclude_industries", [])
        ]
        if excluded_industries and "industry_category" in working.columns:
            working = working[
                ~working["industry_category"].astype(str).str.lower().apply(
                    lambda value: any(keyword in value for keyword in excluded_industries)
                )
            ]

        # 強制包含 / 排除
        include_symbols = {
            str(s) for s in portfolio_config.get("auto_universe_include_symbols", [])
        }
        exclude_symbols = {
            str(s) for s in portfolio_config.get("auto_universe_exclude_symbols", [])
        }
        if include_symbols:
            working = working[working["stock_id"].isin(include_symbols)]
        if exclude_symbols:
            working = working[~working["stock_id"].isin(exclude_symbols)]

        # --- 市值排序與 size limit ---
        size_ranked = False

        # 嘗試 1: 使用 TaiwanStockMarketValue（需付費 API）
        if source is not None and hasattr(source, "fetch_market_value"):
            mv_df = source.fetch_market_value()
            if mv_df is not None and not mv_df.empty and {"stock_id", "market_value"}.issubset(mv_df.columns):
                mv = mv_df.copy()
                if "date" in mv.columns:
                    mv["date"] = pd.to_datetime(mv["date"])
                    mv = mv.sort_values(["stock_id", "date"])
                latest_mv = (
                    mv.dropna(subset=["market_value"])
                    .groupby("stock_id", as_index=False)
                    .tail(1)[["stock_id", "market_value"]]
                )
                working = working.merge(latest_mv, on="stock_id", how="left")
                working["market_value"] = pd.to_numeric(working["market_value"], errors="coerce")
                working = working.sort_values(
                    ["market_value", "stock_id"], ascending=[False, True]
                )
                size_ranked = True

        # 嘗試 2: 用 close×volume 20日均值做 size proxy（免費 API 即可）
        if not size_ranked and source is not None and hasattr(source, "fetch_ohlcv"):
            logger.info(
                "market_value API unavailable at %s — computing size proxy from close×volume",
                as_of,
            )
            pre_filter_size = int(portfolio_config.get("auto_universe_pre_filter_size", 0) or 0)
            universe_before_prefilter = len(working)
            if pre_filter_size > 0 and len(working) > pre_filter_size:
                working = working.copy()
                working["_sid_int"] = pd.to_numeric(working["stock_id"], errors="coerce").fillna(99999)
                working = working.sort_values("_sid_int")
                if pre_filter_size == 1:
                    sample_idx = [0]
                else:
                    total = len(working)
                    sample_idx = [
                        int(i * (total - 1) / (pre_filter_size - 1))
                        for i in range(pre_filter_size)
                    ]
                working = working.iloc[sample_idx].copy().drop(columns=["_sid_int"])
                logger.info(
                    "Universe pre-filter at %s: %d → %d stocks (evenly spaced by stock_id). "
                    "Set auto_universe_pre_filter_size=0 to disable.",
                    as_of.date() if hasattr(as_of, "date") else as_of,
                    universe_before_prefilter,
                    len(working),
                )
            size_proxy: dict[str, float] = {}
            for _, row in working.iterrows():
                sym = str(row["stock_id"])
                try:
                    ohlcv = source.fetch_ohlcv(sym, "D", 30)
                    if ohlcv is not None and len(ohlcv) >= 5:
                        turnover = (ohlcv["close"] * ohlcv["volume"]).tail(20).mean()
                        size_proxy[sym] = float(turnover) if pd.notna(turnover) else 0.0
                    else:
                        size_proxy[sym] = 0.0
                except Exception:
                    size_proxy[sym] = 0.0
            working["_size_proxy"] = working["stock_id"].map(size_proxy).fillna(0.0)
            working = working.sort_values(
                ["_size_proxy", "stock_id"], ascending=[False, True]
            )
            working = working.drop(columns=["_size_proxy"])
            size_ranked = True

        if not size_ranked:
            logger.warning(
                "No size data available at %s — using stock_info order as fallback",
                as_of,
            )

        limit = int(portfolio_config.get("auto_universe_size", 80) or 0)
        if limit > 0:
            working = working.head(limit)

        result = []
        for _, row in working.iterrows():
            result.append(
                {
                    "symbol": str(row["stock_id"]),
                    "name": str(row.get("stock_name", row["stock_id"])),
                    "market": "tw_stock",
                    "source": "finmind",
                    "timeframe": "D",
                    "enabled": True,
                    "strategy": {},
                    "industry": str(row.get("industry_category", "")),
                    "type": str(row.get("type", "")),
                    "market_value": float(row["market_value"]) if pd.notna(row.get("market_value")) else None,
                }
            )
        return result
