"""模擬投資追蹤。"""

import streamlit as st
import pandas as pd
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils import load_paper_trading_history, PAPER_TRADING_DIR

st.set_page_config(page_title="模擬投資", page_icon="📅", layout="wide")
st.title("📅 模擬投資追蹤")
st.caption("策略每月建議的持股紀錄。等累積 6 個月以上才能評估策略是否有效。")

history = load_paper_trading_history()

if not history:
    st.info("尚無紀錄。每月 12 號執行一次 `scripts/paper_trade.py` 開始記錄。")
    st.stop()

# --- 摘要 ---
st.metric("已記錄", f"{len(history)} 個月", delta=f"從 {history[0].get('month_key', '')} 開始")

if len(history) < 6:
    months_left = 6 - len(history)
    st.info(f"⏳ 再累積 {months_left} 個月就可以初步評估了。目前先看策略每月選了什麼。")

st.divider()

# --- 每月卡片 ---
for record in reversed(history):
    month = record.get("month_key", "?")
    signal = record.get("market_signal", "unknown")
    emoji = {"risk_on": "🟢", "caution": "🟡", "risk_off": "🔴"}.get(signal, "⚪")
    label = {"risk_on": "積極買入", "caution": "謹慎觀望", "risk_off": "保守防禦"}.get(signal, signal)
    exposure = record.get("gross_exposure", 0)

    with st.expander(f"{emoji} {month} — {label}（投入 {exposure:.0%}）", expanded=(record == history[-1])):
        positions = record.get("positions", [])
        if positions:
            for i, p in enumerate(positions, 1):
                st.markdown(f"{i}. **{p.get('symbol', '')} {p.get('name', '')}** — 權重 {p.get('weight', 0):.0%}　({p.get('industry', '')})")

        actual = record.get("actual_return")
        if actual is not None:
            st.metric("實際月報酬", f"{actual:+.1%}")
        else:
            st.caption("⏳ 實際報酬尚未填入")
