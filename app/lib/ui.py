"""共用的顯示元件與格式化。"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# 台股習慣紅漲綠跌，與歐美相反。
UP_COLOR = "#c62828"
DOWN_COLOR = "#2e7d32"

MATCH_TYPE_LABELS = {
    "title_tag": "標題為 [標的] 且含代號（信心最高）",
    "code_with_name": "同篇出現代號與名稱",
    "name": "專有名稱命中",
    "code_context": "代號加鄰近金融語境",
    "name_context": "簡稱加鄰近金融語境（信心最低）",
}

MATCH_TYPE_SHORT = {
    "title_tag": "標的文標題",
    "code_with_name": "代號＋名稱",
    "name": "專有名稱",
    "code_context": "代號＋語境",
    "name_context": "簡稱＋語境",
}


def fmt_z(value) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{value:+.2f}"


def fmt_pct(value) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{value:.0f}"


def heat_table(df: pd.DataFrame, show_rank_change: bool = True) -> None:
    """熱度表格。刻意把異常倍數排在熱度分數前面，因為它才是訊號。"""
    if df.empty:
        st.info("這個區間沒有資料。")
        return

    view = pd.DataFrame(
        {
            "代號": df["symbol"],
            "名稱": df["name"],
            "異常倍數": df["z_score"],
            "熱度": df["heat_score"],
            "排名": df["rank"],
            "情緒": df["sentiment_label"],
            "提及": df["mention_count"],
        }
    )
    if show_rank_change and "rank_change" in df:
        view.insert(5, "排名變化", df["rank_change"])

    st.dataframe(
        view,
        hide_index=True,
        width="stretch",
        column_config={
            "異常倍數": st.column_config.NumberColumn(
                "異常倍數",
                help="相對自身 30 日基準的標準差倍數。+2 以上代表明顯高於平常。",
                format="%+.2f",
            ),
            "熱度": st.column_config.ProgressColumn(
                "熱度", help="當日全市場百分位", min_value=0, max_value=100, format="%.0f"
            ),
            "排名變化": st.column_config.NumberColumn("排名變化", format="%+d"),
            "提及": st.column_config.NumberColumn("提及", help="當日被提及的文章數"),
        },
    )


def heat_chart(history: pd.DataFrame, title: str = "熱度與情緒走勢") -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=history["date"],
            y=history["mention_count"],
            name="提及數",
            marker_color="#b0bec5",
            yaxis="y2",
            hovertemplate="%{x}<br>提及 %{y} 則<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=history["date"],
            y=history["z_score"],
            name="異常倍數",
            mode="lines+markers",
            line=dict(color="#1565c0", width=2),
            hovertemplate="%{x}<br>異常倍數 %{y:+.2f}<extra></extra>",
        )
    )
    # 兩倍標準差是常用的「值得注意」門檻。
    fig.add_hline(y=2, line_dash="dot", line_color=UP_COLOR, annotation_text="異常門檻 +2")
    fig.update_layout(
        title=title,
        height=340,
        margin=dict(l=10, r=10, t=40, b=10),
        yaxis=dict(title="異常倍數"),
        yaxis2=dict(title="提及數", overlaying="y", side="right", showgrid=False),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        hovermode="x unified",
    )
    return fig


def sentiment_chart(history: pd.DataFrame) -> go.Figure:
    colors = [UP_COLOR if (v or 0) >= 0 else DOWN_COLOR for v in history["sentiment"]]
    fig = go.Figure(
        go.Bar(
            x=history["date"],
            y=history["sentiment"],
            marker_color=colors,
            hovertemplate="%{x}<br>情緒 %{y:+.2f}<extra></extra>",
        )
    )
    fig.update_layout(
        title="每日情緒（正為看多、負為看空）",
        height=260,
        margin=dict(l=10, r=10, t=40, b=10),
        yaxis=dict(range=[-1, 1], title="情緒"),
    )
    return fig


def price_chart(prices: pd.DataFrame) -> go.Figure:
    fig = go.Figure(
        go.Candlestick(
            x=prices["date"],
            open=prices["open"],
            high=prices["high"],
            low=prices["low"],
            close=prices["close"],
            increasing_line_color=UP_COLOR,
            decreasing_line_color=DOWN_COLOR,
            name="股價",
        )
    )
    fig.update_layout(
        title="股價",
        height=320,
        margin=dict(l=10, r=10, t=40, b=10),
        xaxis_rangeslider_visible=False,
    )
    return fig


def empty_state(message: str, hint: str | None = None) -> None:
    st.info(message)
    if hint:
        st.caption(hint)
