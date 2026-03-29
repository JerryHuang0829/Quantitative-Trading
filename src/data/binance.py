"""Binance 公開 API 資料源（加密貨幣）"""

import logging
import requests
import pandas as pd
from .base import DataSource
from ..utils.retry import api_retry

logger = logging.getLogger(__name__)

BINANCE_KLINES_URL = 'https://api.binance.com/api/v3/klines'


class BinanceSource(DataSource):
    """
    Binance 公開 API 資料源
    不需要 API Key，抓取公開 K 線資料
    支援 24/7 全時段（加密貨幣）
    """

    @api_retry
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 100) -> pd.DataFrame | None:
        """
        從 Binance 抓取 OHLCV K 線

        Args:
            symbol: 交易對，如 'BTCUSDT'
            timeframe: K 線週期，如 '1m','5m','15m','1h','4h','1d'
            limit: 最多 1000
        """
        params = {
            'symbol': symbol,
            'interval': timeframe,
            'limit': min(limit, 1000),
        }

        try:
            response = requests.get(BINANCE_KLINES_URL, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            logger.error(f"Binance API 請求失敗 ({symbol}): {e}")
            return None

        if not data:
            logger.warning(f"Binance 回傳空資料: {symbol}")
            return None

        df = pd.DataFrame(data, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume', 'trades',
            'taker_buy_base', 'taker_buy_quote', 'ignore',
        ])

        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        df.set_index('timestamp', inplace=True)

        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)

        df = df[['open', 'high', 'low', 'close', 'volume']]

        # 排除最後一根未收盤 K 棒：Binance 回傳的最後一筆可能仍在形成中，
        # 用 close_time 欄位判斷 — 若 close_time 大於當前時間，代表該 K 棒尚未收盤
        import time as _time
        now_ms = int(_time.time() * 1000)
        raw_close_times = [int(row[6]) for row in data]  # close_time 在第 7 欄
        if raw_close_times and raw_close_times[-1] > now_ms:
            df = df.iloc[:-1]
            logger.debug(f"{symbol}: 排除未收盤 K 棒")

        return df

    def is_market_open(self) -> bool:
        """加密貨幣 24/7 全時段"""
        return True
