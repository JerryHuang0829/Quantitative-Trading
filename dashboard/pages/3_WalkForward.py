"""策略在不同時期都有效嗎？"""

import streamlit as st
import plotly.express as px
import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils import load_walk_forward_summary

st.set_page_config(page_title="歷史驗證", page_icon="🔄", layout="wide")
st.title("🔄 策略在不同時期都有效嗎？")

st.caption("我們把 2020-2025 年切成 11 個半年，分別測試策略表現。就像考 11 次試，看看是不是每次都及格。")

wf = load_walk_forward_summary()
if wf is None:
    st.warning("尚無驗證結果。")
    st.stop()

agg = wf.get("aggregate", {})
windows = [w for w in wf.get("windows", []) if "sharpe" in w and w["sharpe"] is not None]

# --- 一句話結論 ---
win_rate = agg.get("win_rate", 0)
mean_sharpe = agg.get("mean_sharpe", 0)

if win_rate >= 0.7:
    st.success(f"✅ 11 次考試中 {win_rate:.0%} 及格 — 策略經得起考驗")
elif win_rate >= 0.5:
    st.warning(f"⚠️ 11 次考試中 {win_rate:.0%} 及格 — 策略有效但不穩定")
else:
    st.error(f"❌ 11 次考試中 {win_rate:.0%} 及格 — 策略可能有問題")

st.divider()

# --- 三個數字 ---
col1, col2, col3 = st.columns(3)
col1.metric("勝率", f"{win_rate:.0%}")
col1.caption("賺錢的半年佔幾成")
col2.metric("平均表現", f"{mean_sharpe:.2f}")
col2.caption("Sharpe > 1 很好，> 0.5 及格")
col3.metric("最慘半年", f"{agg.get('worst_mdd', 0):.0%}")
col3.caption("最差時期的最大虧損")

st.divider()

# --- 一張圖：每個半年是賺是虧 ---
st.subheader("11 個半年的成績單")

market_context = {
    1: "疫後反彈",
    2: "航運飆漲",
    3: "高檔震盪",
    4: "升息崩跌",
    5: "熊市末段",
    6: "AI 爆發",
    7: "盤整消化",
    8: "台積電領漲",
    9: "權值股獨漲",
    10: "0050 分割",
    11: "下半年反彈",
}

chart_data = []
for w in windows:
    period = f"{w['test_start'][:7]}~{w['test_end'][:7]}"
    context = market_context.get(w["window"], "")
    sharpe = w["sharpe"]
    chart_data.append({
        "時期": f"{period}\n{context}",
        "表現": sharpe,
        "結果": "✅ 賺錢" if sharpe > 0 else "❌ 虧錢",
    })

df = pd.DataFrame(chart_data)
fig = px.bar(
    df, x="時期", y="表現",
    color="結果",
    color_discrete_map={"✅ 賺錢": "#2ecc71", "❌ 虧錢": "#e74c3c"},
)
fig.add_hline(y=0, line_dash="dash", line_color="gray")
fig.update_layout(
    yaxis_title="Sharpe（越高越好，0 以上 = 賺錢）",
    height=450,
    margin=dict(t=20, b=100),
    showlegend=True,
)
st.plotly_chart(fig, use_container_width=True)

st.divider()

# --- 白話解讀 ---
st.subheader("什麼時候賺、什麼時候虧？")

st.markdown("""
**策略賺錢的環境 ✅**
- 市場有明確方向（不管漲還是跌，只要趨勢清楚）
- 例如：疫後反彈、AI 題材爆發、台積電領漲

**策略虧錢的環境 ❌**
- 市場突然反轉（昨天還在漲，今天突然崩）
- 大型股獨漲，中小型股沒跟上
- 例如：2022 上半年升息開始崩跌

**一句話總結：趨勢明確時很賺，轉折點會虧，但賺的時候賺得多、虧的時候虧得少。**
""")

# --- 明細（摺疊）---
with st.expander("📊 完整數據表（進階）"):
    rows = []
    for w in windows:
        rows.append({
            "視窗": f"W{w['window']}",
            "測試期間": f"{w['test_start'][:7]} → {w['test_end'][:7]}",
            "Sharpe": f"{w['sharpe']:+.2f}",
            "年化報酬": f"{w.get('annualized_return', 0):.1%}",
            "最大回撤": f"{w.get('max_drawdown', 0):.1%}",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
