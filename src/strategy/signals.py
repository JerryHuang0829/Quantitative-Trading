"""
複合信號評分系統 v2

核心改進：從「追交叉」→「在好價位進場」
- 舊版：SMA 黃金交叉 → 買（已經漲上去了）
- 新版：上升結構 + 回調到均線附近 + RSI 未超買 → 買（買在回調低點）

新增三個維度：
1. RSI 背離（領先指標，比交叉早發現轉折）
2. 回調進場（在趨勢中等回調，不追高）
3. 市場結構（Higher High/Higher Low 比均線更即時）
"""

import logging
import pandas as pd
from .regime import get_regime_weights_v2
from ..features.institutional import score_institutional

logger = logging.getLogger(__name__)


# ============================================================
# 原有指標評分（保留但調整邏輯）
# ============================================================

def _score_sma(df: pd.DataFrame, strategy: dict) -> dict:
    """
    SMA 均線評分 v2

    改進：不再給交叉高分（因為交叉 = 已經漲/跌一段了）
    改為判斷「趨勢方向」，搭配其他指標決定進場時機

    - 多頭排列 → 方向看多 +50（不是進場信號，是方向確認）
    - 空頭排列 → 方向看空 -50
    - 黃金交叉 → +60（略高於排列，但不再是 +100）
    - 死亡交叉 → -60
    """
    latest = df.iloc[-1]
    prev = df.iloc[-2]

    sma_f = latest.get('sma_fast')
    sma_s = latest.get('sma_slow')
    prev_f = prev.get('sma_fast')
    prev_s = prev.get('sma_slow')

    if pd.isna(sma_f) or pd.isna(sma_s) or pd.isna(prev_f) or pd.isna(prev_s):
        return {'score': 0, 'detail': '資料不足', 'icon': '➖'}

    # 黃金交叉（降低分數，交叉是確認不是進場點）
    if prev_f <= prev_s and sma_f > sma_s:
        return {'score': 60, 'detail': '黃金交叉', 'icon': '✅'}
    # 死亡交叉
    if prev_f >= prev_s and sma_f < sma_s:
        return {'score': -60, 'detail': '死亡交叉', 'icon': '🔻'}
    # 多頭排列
    if sma_f > sma_s:
        return {'score': 50, 'detail': '多頭排列', 'icon': '✅'}
    # 空頭排列
    return {'score': -50, 'detail': '空頭排列', 'icon': '🔻'}


def _score_rsi(df: pd.DataFrame, strategy: dict) -> dict:
    """
    RSI 評分 v2

    改進：加入背離偵測（領先指標）
    - 底部背離（價格新低但 RSI 沒有）→ 強力買入信號
    - 頂部背離（價格新高但 RSI 沒有）→ 強力賣出信號
    - 超賣/超買 → 保留但降低權重
    """
    latest = df.iloc[-1]
    rsi = latest.get('rsi')
    divergence = latest.get('rsi_divergence', 0)

    if pd.isna(rsi):
        return {'score': 0, 'detail': '資料不足', 'icon': '➖'}

    oversold = strategy.get('rsi_oversold', 30)
    overbought = strategy.get('rsi_overbought', 70)

    # 背離是最強信號（領先指標）
    if divergence == 1:  # 底部背離
        return {'score': 90, 'detail': f'底部背離 RSI={rsi:.1f}', 'icon': '🔥'}
    if divergence == -1:  # 頂部背離
        return {'score': -90, 'detail': f'頂部背離 RSI={rsi:.1f}', 'icon': '🔥'}

    # 傳統超賣/超買
    if rsi < oversold:
        intensity = min(80, (oversold - rsi) / oversold * 100 * 2.5)
        return {'score': intensity, 'detail': f'超賣 {rsi:.1f}', 'icon': '✅'}
    elif rsi > overbought:
        intensity = min(80, (rsi - overbought) / (100 - overbought) * 100 * 2.5)
        return {'score': -intensity, 'detail': f'超買 {rsi:.1f}', 'icon': '🔻'}
    else:
        return {'score': 0, 'detail': f'{rsi:.1f} 中性', 'icon': '➖'}


def _score_macd(df: pd.DataFrame, strategy: dict) -> dict:
    """
    MACD 評分 v2

    改進：重視柱狀圖趨勢（動能變化），降低交叉權重
    - 柱狀圖由負轉正（動能回升）比金叉更早
    - 柱狀圖連續收斂 = 動能減弱，可能要反轉
    """
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    prev2 = df.iloc[-3] if len(df) > 2 else prev

    macd = latest.get('macd_line')
    signal = latest.get('macd_signal')
    hist = latest.get('macd_histogram')
    prev_hist = prev.get('macd_histogram')
    prev2_hist = prev2.get('macd_histogram')

    if pd.isna(macd) or pd.isna(signal) or pd.isna(hist) or pd.isna(prev_hist):
        return {'score': 0, 'detail': '資料不足', 'icon': '➖'}

    prev_macd = prev.get('macd_line')
    prev_signal = prev.get('macd_signal')

    # 金叉（降低到 70，交叉是落後指標）
    if pd.notna(prev_macd) and pd.notna(prev_signal):
        if prev_macd <= prev_signal and macd > signal:
            return {'score': 70, 'detail': '金叉', 'icon': '✅'}
        if prev_macd >= prev_signal and macd < signal:
            return {'score': -70, 'detail': '死叉', 'icon': '🔻'}

    # 柱狀圖趨勢（更敏感的動能指標）
    if pd.notna(prev2_hist):
        # 柱狀圖連續 2 根收斂（負→較不負 或 正→較不正）= 動能轉變中
        if prev2_hist < prev_hist < 0 and hist > prev_hist:
            # 負值在縮小 = 空頭動能減弱，可能要反轉向上
            return {'score': 50, 'detail': '動能回升中', 'icon': '📈'}
        if prev2_hist > prev_hist > 0 and hist < prev_hist:
            # 正值在縮小 = 多頭動能減弱
            return {'score': -50, 'detail': '動能減弱中', 'icon': '📉'}

    # 一般柱狀圖方向
    if hist > 0:
        return {'score': 25, 'detail': '柱狀圖正', 'icon': '✅'}
    else:
        return {'score': -25, 'detail': '柱狀圖負', 'icon': '🔻'}


def _score_bb(df: pd.DataFrame, strategy: dict) -> dict:
    """
    布林通道評分 v2

    改進：加入 %B 位置判斷，不只看突破
    - 跌破下軌 + 趨勢向上 = 好的回調買點
    - 突破上軌 = 超延伸，注意風險
    - 在中軌附近 = 回歸均值區域
    """
    latest = df.iloc[-1]
    price = latest['close']
    bb_lower = latest.get('bb_lower')
    bb_upper = latest.get('bb_upper')
    bb_mid = latest.get('bb_mid')
    bb_percent = latest.get('bb_percent')

    if pd.isna(bb_lower) or pd.isna(bb_upper):
        return {'score': 0, 'detail': '資料不足', 'icon': '➖'}

    if price < bb_lower:
        return {'score': 80, 'detail': '跌破下軌', 'icon': '✅'}
    elif price > bb_upper:
        return {'score': -80, 'detail': '突破上軌', 'icon': '🔻'}
    elif pd.notna(bb_percent):
        # %B < 0.2 = 接近下軌（潛在買點）
        if bb_percent < 0.2:
            return {'score': 40, 'detail': f'接近下軌 %B={bb_percent:.2f}', 'icon': '📉'}
        # %B > 0.8 = 接近上軌（注意風險）
        elif bb_percent > 0.8:
            return {'score': -40, 'detail': f'接近上軌 %B={bb_percent:.2f}', 'icon': '📈'}

    return {'score': 0, 'detail': '通道內', 'icon': '➖'}


def _score_volume(df: pd.DataFrame, strategy: dict) -> dict:
    """
    成交量評分（不變）
    """
    latest = df.iloc[-1]
    vol_ratio = latest.get('volume_ratio')
    breakout_ratio = strategy.get('volume_breakout_ratio', 1.5)

    if pd.isna(vol_ratio):
        return {'score': 0, 'detail': '資料不足', 'icon': '➖'}

    price_change = latest['close'] - df.iloc[-2]['close']

    if vol_ratio >= breakout_ratio:
        if price_change > 0:
            return {'score': 80, 'detail': f'放量 {vol_ratio:.1f}x', 'icon': '✅'}
        else:
            return {'score': -80, 'detail': f'放量下跌 {vol_ratio:.1f}x', 'icon': '🔻'}
    elif vol_ratio < 0.5:
        return {'score': 0, 'detail': f'縮量 {vol_ratio:.1f}x', 'icon': '⚠️'}
    else:
        return {'score': 0, 'detail': f'正常量 {vol_ratio:.1f}x', 'icon': '➖'}


# Implementation moved to src/features/institutional.py
_score_institutional = score_institutional


# ============================================================
# v2 新增指標評分
# ============================================================

def _score_pullback(df: pd.DataFrame, strategy: dict, regime: str) -> dict:
    """
    回調進場評分（v2 核心新增）

    邏輯：在趨勢中，等價格回調到均線附近才買
    - 上升趨勢 + 價格回調到 SMA 附近 → 好買點（+80）
    - 下降趨勢 + 價格反彈到 SMA 附近 → 好賣點（-80）
    - 震盪市 → 不適用（0）

    這解決了「追高」的問題：
    舊版在黃金交叉時買（價格已遠離均線）
    新版等回調到均線時買（價格在好位置）
    """
    latest = df.iloc[-1]
    pullback = latest.get('pullback_score')
    bias_fast = latest.get('bias_fast')
    near_support = latest.get('near_support')

    if pd.isna(pullback):
        return {'score': 0, 'detail': '資料不足', 'icon': '➖'}

    # 只在趨勢市有用
    if regime == 'ranging':
        return {'score': 0, 'detail': '震盪市不適用', 'icon': '➖'}

    if regime == 'trending_up':
        # 上升趨勢中回調到均線附近 = 好買點
        if pullback > 0.7:  # 離均線 1 ATR 以內
            detail = f'回調到位 {pullback:.2f}'
            # 如果同時接近支撐位，加分
            if pd.notna(near_support) and near_support < 1.5:
                return {'score': 90, 'detail': f'{detail} + 近支撐', 'icon': '🎯'}
            return {'score': 70, 'detail': detail, 'icon': '📍'}
        elif pullback > 0.4:
            return {'score': 30, 'detail': f'接近均線 {pullback:.2f}', 'icon': '📉'}
        else:
            return {'score': 0, 'detail': f'離均線遠 {pullback:.2f}', 'icon': '➖'}

    if regime == 'trending_down':
        # 下降趨勢中反彈到均線附近 = 好賣點
        if pullback > 0.7:
            detail = f'反彈到位 {pullback:.2f}'
            if pd.notna(near_support):
                near_res = latest.get('near_resistance')
                if pd.notna(near_res) and near_res < 1.5:
                    return {'score': -90, 'detail': f'{detail} + 近壓力', 'icon': '🎯'}
            return {'score': -70, 'detail': detail, 'icon': '📍'}
        elif pullback > 0.4:
            return {'score': -30, 'detail': f'接近均線 {pullback:.2f}', 'icon': '📈'}

    return {'score': 0, 'detail': f'回調中 {pullback:.2f}', 'icon': '➖'}


def _score_structure(df: pd.DataFrame, strategy: dict) -> dict:
    """
    市場結構評分（v2 核心新增）

    判斷 Higher High + Higher Low（上升）或 Lower High + Lower Low（下降）
    比均線更即時，能更早發現趨勢改變

    - 上升結構 → +60（趨勢健康）
    - 下降結構 → -60（趨勢惡化）
    - 結構破壞 → 強信號（趨勢可能反轉）
    """
    latest = df.iloc[-1]
    prev = df.iloc[-2]

    structure = latest.get('structure', 0)
    prev_structure = prev.get('structure', 0)

    if structure == 0 and prev_structure == 0:
        return {'score': 0, 'detail': '結構不明', 'icon': '➖'}

    # 結構轉變（最重要的信號）
    if prev_structure == -1 and structure == 1:
        return {'score': 80, 'detail': '結構轉多', 'icon': '🔄'}
    if prev_structure == 1 and structure == -1:
        return {'score': -80, 'detail': '結構轉空', 'icon': '🔄'}

    # 持續結構
    if structure == 1:
        return {'score': 60, 'detail': '上升結構 HH+HL', 'icon': '📈'}
    if structure == -1:
        return {'score': -60, 'detail': '下降結構 LH+LL', 'icon': '📉'}

    return {'score': 0, 'detail': '結構不明', 'icon': '➖'}


# ============================================================
# 複合評分（v2）
# ============================================================

def calculate_composite_score(
    df: pd.DataFrame,
    strategy: dict,
    regime: str,
    institutional_df: pd.DataFrame | None = None,
    signal_config: dict | None = None,
) -> dict:
    """
    複合信號評分 v2

    改進：
    1. 新增 pullback（回調）和 structure（結構）兩個維度
    2. 趨勢市中回調指標權重最高（解決追高問題）
    3. 震盪市中 RSI/BB 權重最高（抓反轉）
    4. 結構指標在所有市場狀態中都有權重（最即時的趨勢判斷）
    5. require_volume_confirm 作為 gate（量能不足時降低分數）
    """
    if signal_config is None:
        signal_config = {}

    weights = get_regime_weights_v2(regime)

    use_institutional = strategy.get('use_institutional', False)
    raw_scores = {
        'sma': _score_sma(df, strategy),
        'rsi': _score_rsi(df, strategy),
        'macd': _score_macd(df, strategy),
        'bb': _score_bb(df, strategy),
        'volume': _score_volume(df, strategy),
        'pullback': _score_pullback(df, strategy, regime),
        'structure': _score_structure(df, strategy),
    }
    if use_institutional:
        raw_scores['institutional'] = _score_institutional(institutional_df)
    else:
        inst_weight = weights.pop('institutional', 0)
        remaining = sum(weights.values())
        if remaining > 0:
            for k in weights:
                weights[k] = weights[k] / remaining

    # 加權計算
    weighted_sum = 0
    total_weight = 0
    components = {}

    for indicator, raw in raw_scores.items():
        w = weights.get(indicator, 0)
        weighted = raw['score'] * w
        weighted_sum += weighted
        total_weight += w
        components[indicator] = {
            'score': raw['score'],
            'detail': raw['detail'],
            'icon': raw['icon'],
            'weight': w,
            'weighted': weighted,
        }

    # 正規化
    if total_weight > 0:
        normalized = weighted_sum / total_weight
    else:
        normalized = 0

    final_score = int(abs(normalized))
    final_score = min(100, max(0, final_score))

    # Volume gate：量能不確認時打折（require_volume_confirm）
    require_vol = signal_config.get('require_volume_confirm', False)
    vol_score = raw_scores.get('volume', {}).get('score', 0)
    if require_vol and vol_score == 0 and final_score > 0:
        # 量能中性（無放量確認）→ 分數打 7 折
        final_score = int(final_score * 0.7)
        logger.debug(f"Volume gate: 無量能確認，分數降至 {final_score}")

    # 判斷方向
    if normalized > 10:
        direction = 'BUY'
    elif normalized < -10:
        direction = 'SELL'
    else:
        direction = 'NEUTRAL'

    # 生成原因摘要
    active_signals = []
    for name, comp in components.items():
        if abs(comp['score']) > 20:
            active_signals.append(comp['detail'])

    reason = '、'.join(active_signals) if active_signals else '無明確信號'

    return {
        'direction': direction,
        'score': final_score,
        'regime': regime,
        'components': components,
        'reason': reason,
    }
