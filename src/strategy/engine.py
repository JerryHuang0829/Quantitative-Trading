"""
分層決策引擎 v3

取代 v2 的「全部指標加權投票」，改為三層篩選：

Layer 1: Regime Filter
  → 判斷市場狀態（trending_up / trending_down / ranging）
  → 決定啟用哪一組 setup 規則

Layer 2: Setup Filter
  → 趨勢市：只看趨勢延續型條件（結構 + 方向確認）
  → 震盪市：只看均值回歸型條件（RSI 背離 + BB 極端）
  → 不成立 → 不產出信號，不管個別指標多強

Layer 3: Trigger
  → Setup 成立後，才用進場時機條件做最終觸發
  → 回調到位、MACD 動能回升、量能確認、法人同向

為什麼比加權投票好：
  - 不會重複計數（SMA/structure/pullback 不再同時投票）
  - 不會逆勢交易（震盪市不會被趨勢指標帶偏）
  - 更容易回測（每層可獨立測試通過率）
"""

import logging
import pandas as pd
from .regime import detect_regime, get_regime_display

logger = logging.getLogger(__name__)


def evaluate_signal(
    df: pd.DataFrame,
    strategy: dict,
    regime: str,
    market: str = 'crypto',
    institutional_df: pd.DataFrame | None = None,
    signal_config: dict | None = None,
    htf_regime: str | None = None,
    risk_manager=None,
) -> dict:
    """
    分層決策主入口

    Args:
        df: 含所有技術指標的 OHLCV DataFrame
        strategy: 策略參數
        regime: 市場狀態
        market: 'crypto' | 'tw_stock'
        institutional_df: 法人資料（台股）
        signal_config: 信號設定（min_composite_score, require_volume_confirm 等）
        htf_regime: 更高時間框架的 regime（用於多週期驗證）

    Returns:
        {
            'direction': 'BUY' | 'SELL' | 'NEUTRAL',
            'score': 0~100,
            'regime': str,
            'setup': str,          # 成立的 setup 名稱
            'triggers': list,      # 觸發的 trigger 條件
            'components': dict,    # 各指標詳情（相容舊格式）
            'reason': str,
        }
    """
    if signal_config is None:
        signal_config = {}

    latest = df.iloc[-1]
    prev = df.iloc[-2]
    components = {}

    # ============================================================
    # Layer 1: Regime Filter（已由外部傳入，這裡做 HTF 驗證）
    # ============================================================
    _rm = risk_manager
    _htf = htf_regime or ''
    _rmode = _rm.mode if _rm is not None else 'normal'

    if htf_regime is not None:
        htf_block = _check_htf_conflict(regime, htf_regime, strategy)
        if htf_block:
            return _neutral_result(regime, components,
                                   reason=f'HTF 衝突: {get_regime_display(htf_regime)} vs {get_regime_display(regime)}',
                                   htf_regime=_htf, risk_mode=_rmode)

    # ============================================================
    # Layer 2: Setup Filter
    # ============================================================
    if regime in ('trending_up', 'trending_down'):
        setup_result = _check_trend_setup(df, latest, prev, regime, market)
    else:
        setup_result = _check_ranging_setup(df, latest, prev, market)

    components.update(setup_result['components'])

    if not setup_result['valid']:
        return _neutral_result(regime, components, reason=setup_result.get('reason', 'Setup 不成立'),
                               htf_regime=_htf, risk_mode=_rmode)

    setup_direction = setup_result['direction']
    setup_name = setup_result['name']

    # 台股 long-only 限制
    if market == 'tw_stock' and setup_direction == 'SELL':
        # 保留信號但標記為減碼
        pass  # 語意在 telegram.py 處理

    # ============================================================
    # Layer 3: Trigger（進場時機確認）
    # ============================================================
    trigger_result = _check_triggers(
        df, latest, prev, strategy, regime, setup_direction,
        institutional_df, signal_config,
    )
    components.update(trigger_result['components'])

    if not trigger_result['any_triggered']:
        return _neutral_result(regime, components,
                               setup=setup_name,
                               reason=f'Setup 成立但無觸發: {setup_name}',
                               htf_regime=_htf, risk_mode=_rmode)

    # ============================================================
    # 計算最終分數
    # ============================================================
    # 分數 = setup 基礎分 + trigger 加分
    base_score = setup_result['strength']  # 30~60
    trigger_bonus = trigger_result['total_bonus']  # 0~40
    final_score = min(100, base_score + trigger_bonus)

    # Volume gate
    require_vol = signal_config.get('require_volume_confirm', False)
    vol_confirmed = trigger_result.get('volume_confirmed', False)
    if require_vol and not vol_confirmed and final_score > 0:
        final_score = int(final_score * 0.7)

    # Risk mode gate（AI 風控）
    if risk_manager is not None:
        final_score = risk_manager.apply_to_score(final_score, setup_direction)
        if final_score == 0 and setup_direction == 'BUY':
            return _neutral_result(regime, components, reason='Panic 模式：阻擋買入',
                                   htf_regime=_htf, risk_mode='panic')

    reason_parts = [setup_name] + trigger_result['trigger_names']
    reason = '、'.join(reason_parts)

    return {
        'direction': setup_direction,
        'score': final_score,
        'regime': regime,
        'setup': setup_name,
        'triggers': trigger_result['trigger_names'],
        'components': components,
        'reason': reason,
        'htf_regime': htf_regime or '',
        'risk_mode': risk_manager.mode if risk_manager is not None else 'normal',
    }


# ============================================================
# Layer 2: Setup 實作
# ============================================================

def _check_trend_setup(df, latest, prev, regime, market) -> dict:
    """
    趨勢市 Setup：趨勢方向 + 結構確認

    上升趨勢：
      必要：多頭排列（SMA fast > slow）
      加分：上升結構（HH+HL）
    下降趨勢：
      必要：空頭排列
      加分：下降結構（LH+LL）
    """
    sma_f = latest.get('sma_fast')
    sma_s = latest.get('sma_slow')
    structure = latest.get('structure', 0)
    prev_structure = prev.get('structure', 0)

    components = {}

    if pd.isna(sma_f) or pd.isna(sma_s):
        return {'valid': False, 'components': components, 'reason': 'SMA 資料不足'}

    if regime == 'trending_up':
        # 必要條件：多頭排列
        if sma_f <= sma_s:
            components['sma'] = {'score': -50, 'detail': '空頭排列（與 regime 矛盾）', 'icon': '⚠️', 'weight': 0, 'weighted': 0}
            return {'valid': False, 'components': components, 'reason': 'SMA 與趨勢方向矛盾'}

        components['sma'] = {'score': 50, 'detail': '多頭排列', 'icon': '✅', 'weight': 0, 'weighted': 0}

        # 結構確認
        strength = 40  # 基礎分
        if prev_structure == -1 and structure == 1:
            # 結構轉折（從空轉多）— 最強信號，必須先判斷
            components['structure'] = {'score': 80, 'detail': '結構轉多', 'icon': '🔄', 'weight': 0, 'weighted': 0}
            strength = 60
        elif structure == 1:
            components['structure'] = {'score': 60, 'detail': '上升結構 HH+HL', 'icon': '📈', 'weight': 0, 'weighted': 0}
            strength = 55
        else:
            components['structure'] = {'score': 0, 'detail': '結構不明', 'icon': '➖', 'weight': 0, 'weighted': 0}

        return {
            'valid': True,
            'direction': 'BUY',
            'name': '趨勢做多',
            'strength': strength,
            'components': components,
        }

    else:  # trending_down
        if sma_f >= sma_s:
            components['sma'] = {'score': 50, 'detail': '多頭排列（與 regime 矛盾）', 'icon': '⚠️', 'weight': 0, 'weighted': 0}
            return {'valid': False, 'components': components, 'reason': 'SMA 與趨勢方向矛盾'}

        components['sma'] = {'score': -50, 'detail': '空頭排列', 'icon': '🔻', 'weight': 0, 'weighted': 0}

        strength = 40
        if prev_structure == 1 and structure == -1:
            # 結構轉折（從多轉空）— 最強信號，必須先判斷
            components['structure'] = {'score': -80, 'detail': '結構轉空', 'icon': '🔄', 'weight': 0, 'weighted': 0}
            strength = 60
        elif structure == -1:
            components['structure'] = {'score': -60, 'detail': '下降結構 LH+LL', 'icon': '📉', 'weight': 0, 'weighted': 0}
            strength = 55
        else:
            components['structure'] = {'score': 0, 'detail': '結構不明', 'icon': '➖', 'weight': 0, 'weighted': 0}

        return {
            'valid': True,
            'direction': 'SELL',
            'name': '趨勢做空' if market == 'crypto' else '趨勢減碼',
            'strength': strength,
            'components': components,
        }


def _check_ranging_setup(df, latest, prev, market) -> dict:
    """
    震盪市 Setup：均值回歸型條件

    必要（二選一）：
      1. RSI 背離（領先信號）
      2. BB 極端（價格在通道外或接近邊界）+ RSI 配合

    不同於趨勢市，這裡看的是反轉信號
    """
    rsi = latest.get('rsi')
    divergence = latest.get('rsi_divergence', 0)
    bb_percent = latest.get('bb_percent')
    bb_lower = latest.get('bb_lower')
    bb_upper = latest.get('bb_upper')
    price = latest['close']

    components = {}

    if pd.isna(rsi):
        return {'valid': False, 'components': components, 'reason': 'RSI 資料不足'}

    # 條件 1：RSI 背離（最強的震盪市信號）
    if divergence == 1:
        components['rsi'] = {'score': 90, 'detail': f'底部背離 RSI={rsi:.1f}', 'icon': '🔥', 'weight': 0, 'weighted': 0}
        return {
            'valid': True,
            'direction': 'BUY',
            'name': '底部背離',
            'strength': 55,
            'components': components,
        }
    if divergence == -1:
        components['rsi'] = {'score': -90, 'detail': f'頂部背離 RSI={rsi:.1f}', 'icon': '🔥', 'weight': 0, 'weighted': 0}
        return {
            'valid': True,
            'direction': 'SELL',
            'name': '頂部背離' if market == 'crypto' else '頂部背離減碼',
            'strength': 55,
            'components': components,
        }

    # 條件 2：BB 極端 + RSI 配合
    if pd.notna(bb_lower) and pd.notna(bb_upper):
        if price < bb_lower and rsi < 40:
            components['bb'] = {'score': 80, 'detail': '跌破下軌', 'icon': '✅', 'weight': 0, 'weighted': 0}
            components['rsi'] = {'score': 50, 'detail': f'RSI={rsi:.1f} 偏低', 'icon': '📉', 'weight': 0, 'weighted': 0}
            return {
                'valid': True,
                'direction': 'BUY',
                'name': 'BB 超賣反彈',
                'strength': 45,
                'components': components,
            }
        if price > bb_upper and rsi > 60:
            components['bb'] = {'score': -80, 'detail': '突破上軌', 'icon': '🔻', 'weight': 0, 'weighted': 0}
            components['rsi'] = {'score': -50, 'detail': f'RSI={rsi:.1f} 偏高', 'icon': '📈', 'weight': 0, 'weighted': 0}
            return {
                'valid': True,
                'direction': 'SELL',
                'name': 'BB 超買回落' if market == 'crypto' else 'BB 超買減碼',
                'strength': 45,
                'components': components,
            }

        # %B 接近極端 + RSI 超賣/超買
        if pd.notna(bb_percent):
            if bb_percent < 0.15 and rsi < 35:
                components['bb'] = {'score': 50, 'detail': f'接近下軌 %B={bb_percent:.2f}', 'icon': '📉', 'weight': 0, 'weighted': 0}
                components['rsi'] = {'score': 60, 'detail': f'超賣 RSI={rsi:.1f}', 'icon': '✅', 'weight': 0, 'weighted': 0}
                return {
                    'valid': True,
                    'direction': 'BUY',
                    'name': 'RSI 超賣 + BB 低位',
                    'strength': 40,
                    'components': components,
                }
            if bb_percent > 0.85 and rsi > 65:
                components['bb'] = {'score': -50, 'detail': f'接近上軌 %B={bb_percent:.2f}', 'icon': '📈', 'weight': 0, 'weighted': 0}
                components['rsi'] = {'score': -60, 'detail': f'超買 RSI={rsi:.1f}', 'icon': '🔻', 'weight': 0, 'weighted': 0}
                return {
                    'valid': True,
                    'direction': 'SELL',
                    'name': 'RSI 超買 + BB 高位' if market == 'crypto' else 'RSI 超買減碼',
                    'strength': 40,
                    'components': components,
                }

    # 無有效 setup
    components['rsi'] = {'score': 0, 'detail': f'RSI={rsi:.1f} 中性', 'icon': '➖', 'weight': 0, 'weighted': 0}
    components['bb'] = {'score': 0, 'detail': '通道內', 'icon': '➖', 'weight': 0, 'weighted': 0}
    return {'valid': False, 'components': components, 'reason': '震盪市無明確反轉信號'}


# ============================================================
# Layer 3: Trigger 實作
# ============================================================

def _check_triggers(df, latest, prev, strategy, regime, direction,
                    institutional_df, signal_config) -> dict:
    """
    觸發條件檢查（Setup 成立後才執行）

    每個 trigger 獨立判斷，給予加分（0~15 分）
    至少一個 trigger 成立才發出信號
    """
    triggers = []
    components = {}
    total_bonus = 0
    volume_confirmed = False

    # --- Trigger 1: 回調到位 ---
    pullback = latest.get('pullback_score')
    if pd.notna(pullback):
        if regime.startswith('trending'):
            if pullback > 0.7:
                bonus = 15
                near_sup = latest.get('near_support')
                near_res = latest.get('near_resistance')
                if direction == 'BUY' and pd.notna(near_sup) and near_sup < 1.5:
                    bonus = 20
                    components['pullback'] = {'score': 90, 'detail': f'回調到位 + 近支撐', 'icon': '🎯', 'weight': 0, 'weighted': 0}
                elif direction == 'SELL' and pd.notna(near_res) and near_res < 1.5:
                    bonus = 20
                    components['pullback'] = {'score': -90, 'detail': f'反彈到位 + 近壓力', 'icon': '🎯', 'weight': 0, 'weighted': 0}
                else:
                    components['pullback'] = {'score': 70 if direction == 'BUY' else -70, 'detail': f'回調到位 {pullback:.2f}', 'icon': '📍', 'weight': 0, 'weighted': 0}
                triggers.append('回調到位')
                total_bonus += bonus
            else:
                components['pullback'] = {'score': 0, 'detail': f'未到位 {pullback:.2f}', 'icon': '➖', 'weight': 0, 'weighted': 0}
        else:
            components['pullback'] = {'score': 0, 'detail': '震盪市不適用', 'icon': '➖', 'weight': 0, 'weighted': 0}
    else:
        components['pullback'] = {'score': 0, 'detail': '資料不足', 'icon': '➖', 'weight': 0, 'weighted': 0}

    # --- Trigger 2: MACD 動能回升/減弱 ---
    hist = latest.get('macd_histogram')
    prev_hist = prev.get('macd_histogram')
    macd_line = latest.get('macd_line')
    macd_signal = latest.get('macd_signal')
    prev_macd = prev.get('macd_line')
    prev_signal = prev.get('macd_signal')

    if pd.notna(hist) and pd.notna(prev_hist):
        if direction == 'BUY':
            # 買入時看：柱狀圖由負轉正 或 金叉 或 動能回升
            if pd.notna(macd_line) and pd.notna(macd_signal) and pd.notna(prev_macd) and pd.notna(prev_signal):
                if prev_macd <= prev_signal and macd_line > macd_signal:
                    triggers.append('MACD 金叉')
                    total_bonus += 15
                    components['macd'] = {'score': 70, 'detail': '金叉', 'icon': '✅', 'weight': 0, 'weighted': 0}
                elif prev_hist < 0 and hist > prev_hist:
                    triggers.append('動能回升')
                    total_bonus += 10
                    components['macd'] = {'score': 50, 'detail': '動能回升中', 'icon': '📈', 'weight': 0, 'weighted': 0}
                elif hist > 0:
                    components['macd'] = {'score': 25, 'detail': '柱狀圖正', 'icon': '✅', 'weight': 0, 'weighted': 0}
                else:
                    components['macd'] = {'score': -25, 'detail': '柱狀圖負', 'icon': '🔻', 'weight': 0, 'weighted': 0}
            else:
                components['macd'] = {'score': 0, 'detail': '資料不足', 'icon': '➖', 'weight': 0, 'weighted': 0}
        else:  # SELL
            if pd.notna(macd_line) and pd.notna(macd_signal) and pd.notna(prev_macd) and pd.notna(prev_signal):
                if prev_macd >= prev_signal and macd_line < macd_signal:
                    triggers.append('MACD 死叉')
                    total_bonus += 15
                    components['macd'] = {'score': -70, 'detail': '死叉', 'icon': '🔻', 'weight': 0, 'weighted': 0}
                elif prev_hist > 0 and hist < prev_hist:
                    triggers.append('動能減弱')
                    total_bonus += 10
                    components['macd'] = {'score': -50, 'detail': '動能減弱中', 'icon': '📉', 'weight': 0, 'weighted': 0}
                elif hist < 0:
                    components['macd'] = {'score': -25, 'detail': '柱狀圖負', 'icon': '🔻', 'weight': 0, 'weighted': 0}
                else:
                    components['macd'] = {'score': 25, 'detail': '柱狀圖正', 'icon': '✅', 'weight': 0, 'weighted': 0}
            else:
                components['macd'] = {'score': 0, 'detail': '資料不足', 'icon': '➖', 'weight': 0, 'weighted': 0}
    else:
        components['macd'] = {'score': 0, 'detail': '資料不足', 'icon': '➖', 'weight': 0, 'weighted': 0}

    # --- Trigger 3: 成交量確認 ---
    vol_ratio = latest.get('volume_ratio')
    if pd.notna(vol_ratio):
        breakout = strategy.get('volume_breakout_ratio', 1.5)
        price_change = latest['close'] - prev['close']

        if vol_ratio >= breakout:
            if (direction == 'BUY' and price_change > 0) or (direction == 'SELL' and price_change < 0):
                triggers.append(f'放量確認 {vol_ratio:.1f}x')
                total_bonus += 10
                volume_confirmed = True
                score = 80 if direction == 'BUY' else -80
                components['volume'] = {'score': score, 'detail': f'放量 {vol_ratio:.1f}x', 'icon': '✅', 'weight': 0, 'weighted': 0}
            else:
                # 放量但方向相反 → 警告
                score = -40 if direction == 'BUY' else 40
                components['volume'] = {'score': score, 'detail': f'放量反向 {vol_ratio:.1f}x', 'icon': '⚠️', 'weight': 0, 'weighted': 0}
        elif vol_ratio >= strategy.get('volume_confirm_ratio', 1.0):
            volume_confirmed = True  # 達到確認門檻
            components['volume'] = {'score': 0, 'detail': f'正常量 {vol_ratio:.1f}x', 'icon': '➖', 'weight': 0, 'weighted': 0}
        else:
            components['volume'] = {'score': 0, 'detail': f'縮量 {vol_ratio:.1f}x', 'icon': '⚠️', 'weight': 0, 'weighted': 0}
    else:
        components['volume'] = {'score': 0, 'detail': '資料不足', 'icon': '➖', 'weight': 0, 'weighted': 0}

    # --- Trigger 4: 法人同向（台股專用）---
    if institutional_df is not None and not institutional_df.empty:
        from ..features.institutional import score_institutional
        inst_result = score_institutional(institutional_df)
        components['institutional'] = {**inst_result, 'weight': 0, 'weighted': 0}

        if (direction == 'BUY' and inst_result['score'] > 50) or \
           (direction == 'SELL' and inst_result['score'] < -50):
            triggers.append(inst_result['detail'])
            total_bonus += 10
    else:
        components['institutional'] = {'score': 0, 'detail': '無法人資料', 'icon': '➖', 'weight': 0, 'weighted': 0}

    return {
        'any_triggered': len(triggers) > 0,
        'trigger_names': triggers,
        'total_bonus': total_bonus,
        'volume_confirmed': volume_confirmed,
        'components': components,
    }


# ============================================================
# HTF (Higher Timeframe) 驗證
# ============================================================

def _check_htf_conflict(regime: str, htf_regime: str, strategy: dict = None) -> bool:
    """
    檢查低時間框架信號是否與高時間框架方向衝突

    衝突情況（阻擋信號）：
    - HTF 下降 + LTF 上升 → 衝突
    - HTF 上升 + LTF 下降 → 衝突

    不衝突（預設模式）：
    - 同方向趨勢
    - HTF 或 LTF 為 ranging（不確定不算衝突）

    嚴格模式（htf_strict: true）：
    - HTF 為 ranging 時也阻擋 LTF 趨勢信號（只有 HTF 同向才放行）
    """
    if strategy is None:
        strategy = {}

    htf_strict = strategy.get('htf_strict', False)

    if regime == 'ranging':
        return False  # LTF 無趨勢，不需要 HTF 驗證

    if htf_regime == 'ranging':
        # 嚴格模式：HTF 不確定也阻擋
        return htf_strict

    if htf_regime == 'trending_up' and regime == 'trending_down':
        return True
    if htf_regime == 'trending_down' and regime == 'trending_up':
        return True

    return False


# ============================================================
# 輔助函式
# ============================================================

def _neutral_result(regime, components, setup='', reason='無信號',
                    htf_regime='', risk_mode='normal') -> dict:
    """產出 NEUTRAL 結果"""
    return {
        'direction': 'NEUTRAL',
        'score': 0,
        'regime': regime,
        'setup': setup,
        'triggers': [],
        'components': components,
        'reason': reason,
        'htf_regime': htf_regime,
        'risk_mode': risk_mode,
    }
