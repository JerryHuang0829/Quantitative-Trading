"""
AI Provider 抽象介面

定義 AI 模組的標準輸出格式，讓策略層可以用統一方式接收 AI 判斷。
不管底層是 OpenAI API、本地模型、還是 stub，策略層都用同一個介面。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class EventScore:
    """
    事件評分（AI 產出的結構化特徵）

    用途：讓策略層知道是否有重大事件影響標的
    不直接產出 BUY/SELL，只提供輔助特徵

    欄位說明：
    - event_type: 事件類別
        財報 | 法說 | 監管 | 地緣政治 | 駭客 | 交易所 | 供應鏈 | 產品 | 訴訟
    - sentiment: 情緒方向
        positive | negative | neutral
    - severity: 嚴重度 1~5
        1=輕微  2=小幅  3=中等  4=重大  5=極端
    - impact_scope: 影響範圍
        symbol=個股  sector=產業  market=全市場
    - horizon: 影響時間尺度
        intraday | swing | multi_week
    - confidence: 模型信心 0~1
    - affected_symbols: 受影響標的
    """
    event_type: str = ''
    sentiment: str = 'neutral'
    severity: int = 1
    impact_scope: str = 'symbol'
    horizon: str = 'swing'
    confidence: float = 0.5
    affected_symbols: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.utcnow())
    source: str = ''
    summary: str = ''


@dataclass
class FundamentalScore:
    """
    基本面評分（AI 讀財報後產出）

    低頻更新：每週/每月/每季
    用途：判斷技術面信號是否有基本面支撐
    """
    symbol: str = ''
    revenue_yoy: float | None = None       # 營收年增率
    margin_delta: float | None = None       # 毛利率變化
    eps_delta: float | None = None          # EPS 變化
    guidance_sentiment: str = 'neutral'     # 管理層指引情緒
    balance_sheet_risk: str = 'low'         # 資產負債表風險 low/medium/high
    overall_score: int = 0                  # -100 ~ +100
    timestamp: datetime = field(default_factory=lambda: datetime.utcnow())


class AIProvider(ABC):
    """AI Provider 抽象基類"""

    @abstractmethod
    def analyze_event(self, text: str, symbol: str = '') -> EventScore:
        """分析一則新聞/公告，回傳結構化事件評分"""
        ...

    @abstractmethod
    def analyze_fundamental(self, data: dict, symbol: str = '') -> FundamentalScore:
        """分析財報資料，回傳基本面評分"""
        ...
