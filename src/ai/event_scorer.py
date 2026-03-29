"""
事件評分器（Stub 實作）

目前為空殼，永遠回傳中性結果。
後續接入 OpenAI API 後，會：
1. 抓取新聞/公告（RSS、API、爬蟲）
2. 送入 LLM 做結構化分類
3. 回傳 EventScore

建議接入順序（參考 優化建議.md）：
1. 先用 OpenAI API 做 event_score（驗證是否降低誤判）
2. 低價值文本初篩移到本地 gpt-oss-20b
3. 穩定後再加入 fundamental_score
"""

import logging
from .base import AIProvider, EventScore, FundamentalScore

logger = logging.getLogger(__name__)


class StubEventScorer(AIProvider):
    """
    Stub 實作：永遠回傳中性事件評分
    用於開發階段，讓風控模組可以正常運行
    """

    def analyze_event(self, text: str, symbol: str = '') -> EventScore:
        return EventScore(
            sentiment='neutral',
            severity=1,
            confidence=0.0,
            source='stub',
            summary='No AI provider configured',
        )

    def analyze_fundamental(self, data: dict, symbol: str = '') -> FundamentalScore:
        return FundamentalScore(
            symbol=symbol,
            overall_score=0,
        )
