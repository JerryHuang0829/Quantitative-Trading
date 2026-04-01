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

        # --- stock_id 欄位 guard（必須在 dedup 之前，否則 sort_values 會 KeyError）---
        if "stock_id" not in working.columns:
            logger.warning("stock_info has no 'stock_id' column — returning empty universe")
            return []

        # 注意：TaiwanStockInfo.date 是 FinMind 的「記錄更新時間戳記」，
        # 不是 IPO 日期。用 date <= as_of 過濾會把絕大多數合法上市股票排除
        # （實測：2022-01-12 只剩 95 支，2024-12-12 才有 460 支）。
        # 真正的 IPO 日期保護由 _analyze_symbol 的 274-bar OHLCV 要求提供：
        # 一支在 as_of 之前沒有足夠日線歷史的股票，自然會被篩掉。
        #
        # 去重：同一 stock_id 因產業重分類或轉市（上市↔上櫃）會有多筆記錄，
        # 取日期最新那筆（最新的產業/市場分類），避免同一股票被分析兩次。
        if "date" in working.columns:
            working["date"] = pd.to_datetime(working["date"], errors="coerce")
            working = (
                working
                .sort_values(["stock_id", "date"])
                .drop_duplicates("stock_id", keep="last")
            )
        else:
            working = working.drop_duplicates("stock_id", keep="last")
        logger.info(
            "TaiwanStockInfo: %d unique stocks after dedup (total rows before dedup: %d)",
            len(working),
            len(self._stock_info),
        )

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
                working = working[~working["stock_id"].astype(str).isin(delisted_before)]

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

        # --- TWSE 成交金額預篩 + 備用排序（auto_universe_pre_filter_size）---
        # 一次抓取 TWSE 公開日交易資料（免費），同時用於：
        #   1. 預篩：把 ~2900 支縮減到流動性前 N 名
        #   2. 排序備援：若付費 market_value API 不可用，直接以成交金額排序
        # 確保台積電等大型股不因 OHLCV 快取缺失而被排除在候選名單之外。
        _twse_turnover: dict[str, float] = {}  # 保留供後續排序使用
        pre_filter_size = int(portfolio_config.get("auto_universe_pre_filter_size", 0) or 0)
        if pre_filter_size > 0:
            try:
                from src.data.twse_scraper import fetch_combined_turnover
                _twse_turnover = fetch_combined_turnover(as_of)
            except Exception as _exc:
                logger.warning("TWSE scraper import/call failed: %s", _exc)

            if _twse_turnover and len(working) > pre_filter_size:
                _before_pre = len(working)
                working["_twse_turnover"] = (
                    working["stock_id"].map(_twse_turnover).fillna(0.0)
                )
                working = (
                    working
                    .sort_values(["_twse_turnover", "stock_id"], ascending=[False, True])
                    .head(pre_filter_size)
                    .drop(columns=["_twse_turnover"])
                    .reset_index(drop=True)
                )
                logger.info(
                    "Pre-filter: %d → %d stocks using TWSE turnover at %s",
                    _before_pre, len(working),
                    as_of.date() if hasattr(as_of, "date") else as_of,
                )
            elif not _twse_turnover:
                logger.warning(
                    "TWSE turnover unavailable at %s — skipping pre-filter, using all %d stocks",
                    as_of.date() if hasattr(as_of, "date") else as_of,
                    len(working),
                )

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

        # 嘗試 1.5: 使用已取得的 TWSE 成交金額排序（免費、無需 OHLCV 快取）
        # 成交金額 = 當日全市場實際流動性，台積電等大型股必然排前列。
        if not size_ranked and _twse_turnover:
            working["_twse_turnover"] = (
                working["stock_id"].map(_twse_turnover).fillna(0.0)
            )
            working = working.sort_values(
                ["_twse_turnover", "stock_id"], ascending=[False, True]
            )
            working = working.drop(columns=["_twse_turnover"])
            size_ranked = True
            logger.info(
                "Size ranking: using TWSE turnover at %s (%d stocks covered)",
                as_of.date() if hasattr(as_of, "date") else as_of,
                sum(1 for sid in working["stock_id"] if str(sid) in _twse_turnover),
            )

        # 嘗試 2: 用 close×volume 20日均值做 size proxy（免費 API 即可）
        if not size_ranked and source is not None and hasattr(source, "fetch_ohlcv"):
            logger.info(
                "market_value API unavailable at %s — computing size proxy from close×volume (cache-only)",
                as_of,
            )
            # 僅使用已有磁碟快取的股票：避免對 2000+ 支股票發出 API 呼叫
            # 耗盡每小時 600 次配額，且導致 TSMC 等未快取大型股被排除在外。
            # 未在快取中的股票 size_proxy=0，自然排到尾端不入選 top_n。
            # 後續回測會逐漸填充快取，universe 品質隨時間提升。
            import os as _os
            _cache_env = _os.environ.get("DATA_CACHE_DIR", "/app/data/cache")
            _ohlcv_cache_dir = _os.path.join(_cache_env, "ohlcv")
            cached_syms: set[str] = set()
            if _os.path.isdir(_ohlcv_cache_dir):
                cached_syms = {
                    f[:-4]  # strip .pkl
                    for f in _os.listdir(_ohlcv_cache_dir)
                    if f.endswith(".pkl")
                }
            n_cached = sum(1 for sid in working["stock_id"] if str(sid) in cached_syms)
            logger.info(
                "Size proxy: %d/%d universe stocks have cached OHLCV at %s",
                n_cached, len(working),
                as_of.date() if hasattr(as_of, "date") else as_of,
            )
            size_proxy: dict[str, float] = {}
            for _, row in working.iterrows():
                sym = str(row["stock_id"])
                if sym not in cached_syms:
                    size_proxy[sym] = 0.0  # 未快取，不發 API 呼叫
                    continue
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

        logger.info(
            "Universe at %s: %d stocks (limit=%d, size_ranked=%s)",
            as_of.date() if hasattr(as_of, "date") else as_of,
            len(working), limit, size_ranked,
        )

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
