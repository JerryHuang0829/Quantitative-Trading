"""你的實際投資紀錄。"""

import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils import PROJECT_ROOT

REAL_TRADING_DIR = PROJECT_ROOT / "reports" / "real_trading"
PORTFOLIO_FILE = REAL_TRADING_DIR / "portfolio.json"
TRADES_FILE = REAL_TRADING_DIR / "trades.json"
PERFORMANCE_FILE = REAL_TRADING_DIR / "performance.json"

st.set_page_config(page_title="實盤追蹤", page_icon="💰", layout="wide")
st.title("💰 你的實際投資")


def _load(path):
    if not path.exists():
        return [] if "trades" in path.name or "performance" in path.name else {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


portfolio = _load(PORTFOLIO_FILE)
trades = _load(TRADES_FILE)
performance = _load(PERFORMANCE_FILE)

if not portfolio and not trades:
    st.info("尚未開始投資。4/13（週一）開始的話，按照以下步驟：")
    st.markdown("""
    ```bash
    # 1. 取得本月建議
    docker compose run --rm --entrypoint python portfolio-bot scripts/paper_trade.py

    # 2. 在券商 APP 用零股交易買入（盤後 13:40-14:30）

    # 3. 記錄你買了什麼
    python scripts/real_trade.py buy 2360 12 158.5

    # 4. 查看持股
    python scripts/real_trade.py status
    ```
    """)
    st.stop()

# --- 目前持股 ---
if portfolio:
    st.subheader("目前持股")
    total_cost = 0
    for symbol, info in sorted(portfolio.items()):
        total_cost += info["total_cost"]
        st.markdown(f"**{symbol}** — {info['shares']} 股，均價 {info['avg_cost']:.1f} 元，成本 {info['total_cost']:,.0f} 元")

    st.metric("總投入", f"{total_cost:,.0f} 元")

st.divider()

# --- 交易紀錄 ---
if trades:
    st.subheader("交易紀錄")
    for t in reversed(trades[-10:]):
        if t["action"] == "BUY":
            st.markdown(f"🟢 {t['date']} 買入 **{t['symbol']}** {t['shares']}股 @ {t['price']}元 = {t['total']:,.0f}元")
        else:
            emoji = "📈" if t.get("profit", 0) >= 0 else "📉"
            st.markdown(f"🔴 {t['date']} 賣出 **{t['symbol']}** {t['shares']}股 @ {t['price']}元 {emoji} {t.get('profit', 0):+,.0f}元")

    total_fees = sum(t.get("fee", 0) for t in trades)
    total_tax = sum(t.get("tax", 0) for t in trades)
    st.caption(f"累計手續費 {total_fees:,.0f} 元 + 證交稅 {total_tax:,.0f} 元")

st.divider()

# --- 月績效 ---
if performance:
    st.subheader("每月成績")
    for p in reversed(performance):
        emoji = "📈" if p.get("total_return", 0) >= 0 else "📉"
        st.markdown(f"{emoji} **{p['month_key']}** — 報酬 {p.get('total_return', 0):+.1%}，損益 {p.get('total_profit', 0):+,.0f} 元")
