"""
風控狀態管理器

三段風控模式：
- normal:  正常運行，信號照常發送
- alert:   風險升高，提高進場門檻（分數 x 0.7）
- panic:   極端風險，禁止新買入，只允許減碼

狀態切換由 AI 事件層驅動：
- severity >= 4 且 impact_scope = market → panic
- severity >= 3 且 affected_symbol 匹配 → alert
- 無高嚴重度事件持續 N 小時 → 回歸 normal

目前為 stub 實作：永遠回傳 normal
後續接入 AI 後會動態切換
"""

import logging
from datetime import datetime, timezone
from .base import EventScore

logger = logging.getLogger(__name__)


class RiskManager:
    """風控狀態機"""

    MODES = ('normal', 'alert', 'panic')

    def __init__(self):
        self._mode = 'normal'
        self._last_updated = datetime.now(timezone.utc)
        self._reason = ''

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def reason(self) -> str:
        return self._reason

    def update_from_event(self, event: EventScore) -> str:
        """
        根據事件更新風控模式

        Returns:
            更新後的 mode
        """
        old_mode = self._mode

        if event.severity >= 4 and event.impact_scope == 'market':
            self._mode = 'panic'
            self._reason = f'{event.event_type}: {event.summary}'
        elif event.severity >= 3 and event.sentiment == 'negative':
            self._mode = 'alert'
            self._reason = f'{event.event_type}: {event.summary}'
        # severity < 3 不主動降級，需要 reset

        if self._mode != old_mode:
            self._last_updated = datetime.now(timezone.utc)
            logger.warning(f"風控模式變更: {old_mode} -> {self._mode} | {self._reason}")

        return self._mode

    def reset_to_normal(self):
        """手動或自動回歸正常模式"""
        if self._mode != 'normal':
            logger.info(f"風控模式回歸: {self._mode} -> normal")
            self._mode = 'normal'
            self._reason = ''
            self._last_updated = datetime.now(timezone.utc)

    def apply_to_score(self, score: int, direction: str) -> int:
        """
        對信號分數施加風控調整

        - normal: 不調整
        - alert:  分數打 7 折
        - panic:  BUY 信號歸零，SELL 信號保留
        """
        if self._mode == 'normal':
            return score

        if self._mode == 'alert':
            adjusted = int(score * 0.7)
            logger.info(f"Alert 模式: 分數 {score} -> {adjusted}")
            return adjusted

        if self._mode == 'panic':
            if direction == 'BUY':
                logger.warning(f"Panic 模式: 阻擋 BUY 信號 (分數 {score} -> 0)")
                return 0
            return score

        return score

    def to_dict(self) -> dict:
        return {
            'mode': self._mode,
            'reason': self._reason,
            'last_updated': self._last_updated.isoformat(),
        }
