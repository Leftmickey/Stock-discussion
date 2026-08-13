"""個股查詢：支援全市場任意代號或名稱。"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from lib import data, ui

st.header("個股查詢")

keyword = st.text_input(
    "輸入股票代號或名稱", value="2330", placeholder="例如 2330、台積電、鴻勁"
)

if not keyword.strip():
    st.stop()

candidates = data.search(keyword)
if candidates.empty:
    ui.empty_state(
        f"找不到「{keyword}」。",
        "支援上市與上櫃的股票與 ETF，可輸入代號、交易所簡稱或公司名稱片段。",
    )
    st.stop()

if len(candidates) == 1:
    symbol = candidates.iloc[0]["symbol"]
else:
    options = [f"{r.symbol}　{r['name']}　{r.market}" for _, r in candidates.iterrows()]
    symbol = st.selectbox(f"找到 {len(candidates)} 檔，請選擇", options).split("　")[0]

info = data.stock_info(symbol)
market_label = {"TWSE": "上市", "TPEX": "上櫃"}.get(info["market"], info["market"])
type_label = {"stock": "股票", "etf": "ETF", "preferred": "特別股"}.get(
    info["security_type"], info["security_type"]
)

head, action = st.columns([4, 1])
with head:
    st.subheader(f"{info['symbol']}　{info['name']}")
    st.caption(f"{market_label}　{type_label}")
with action:
    if symbol in data.watchlist_symbols():
        if st.button("移出自選", width="stretch"):
            data.remove_watch(symbol)
            st.rerun()
    elif st.button("加入自選", width="stretch"):
        data.add_watch(symbol)
        st.rerun()

history = data.heat_history(symbol, days=60)
latest = data.latest_date()

if history.empty:
    ui.empty_state(
        "這檔股票在已採集的期間內沒有任何討論紀錄。",
        "全市場約 2,400 檔，但 PTT Stock 板 30 天內實際被討論的通常只有數百檔，"
        "冷門股沒有資料是正常結果，不是程式錯誤。",
    )
else:
    today = history[history["date"] == latest]
    c1, c2, c3, c4 = st.columns(4)
    if today.empty:
        c1.metric("今日熱度", "無討論")
        c2.metric("異常倍數", "—")
        c3.metric("全市場排名", "—")
        c4.metric("情緒", "—")
        st.caption(f"最近一次被討論是 {history['date'].max()}。")
    else:
        row = today.iloc[0]
        c1.metric("今日熱度", ui.fmt_pct(row["heat_score"]), help="當日全市場百分位")
        c2.metric(
            "異常倍數",
            ui.fmt_z(row["z_score"]),
            help="相對自身 30 日基準的標準差倍數，+2 以上值得注意",
        )
        # 排名數字越小越熱，delta 取「前一日排名減今日排名」，正值代表往前竄升。
        delta = int(row["prev_rank"] - row["rank"]) if pd.notna(row["prev_rank"]) else None
        c3.metric("全市場排名", int(row["rank"]), delta=delta)
        c4.metric("情緒", row["sentiment_label"], help=f"{int(row['mention_count'])} 則提及")

    st.plotly_chart(ui.heat_chart(history), width="stretch")
    st.plotly_chart(ui.sentiment_chart(history), width="stretch")

prices = data.price_history(symbol, days=90)
if prices.empty or prices["close"].isna().all():
    st.caption(
        "尚無歷史股價。每日批次只會存下當天的全市場快照，"
        f"要立刻補齊線圖可執行：`stockheat prices {symbol}`"
    )
else:
    st.plotly_chart(ui.price_chart(prices), width="stretch")

tab_posts, tab_news = st.tabs(["提及原文", "相關新聞"])

with tab_posts:
    st.caption(
        "熱度是由這些文章加總出來的。數字看起來不對時就從這裡查，"
        "能直接看到是哪幾篇、以什麼理由被算進去。"
        "買賣超排行這類彙整文不列在這裡，它們也不計入熱度。"
    )
    posts = data.mentions(symbol, limit=200)
    if posts.empty:
        ui.empty_state("沒有提及紀錄。")
    else:
        posts["命中方式"] = posts["match_type"].map(ui.MATCH_TYPE_SHORT).fillna(
            posts["match_type"]
        )
        st.dataframe(
            posts[
                ["posted_at", "title", "push_count", "boo_count", "命中方式", "confidence", "url"]
            ].rename(
                columns={
                    "posted_at": "時間",
                    "title": "標題",
                    "push_count": "推",
                    "boo_count": "噓",
                    "confidence": "信心",
                    "url": "連結",
                }
            ),
            hide_index=True,
            width="stretch",
            column_config={
                "連結": st.column_config.LinkColumn("連結", display_text="開啟"),
                "信心": st.column_config.NumberColumn("信心", format="%.2f"),
            },
        )

with tab_news:
    news = data.news_for(symbol)
    if news.empty:
        st.caption(
            "沒有新聞資料。新聞只對自選清單與當日熱度前段班採集，"
            "把這檔加入自選後，下次批次就會納入。"
        )
    else:
        st.dataframe(
            news.rename(
                columns={
                    "published_at": "時間",
                    "title": "標題",
                    "publisher": "來源",
                    "url": "連結",
                }
            ),
            hide_index=True,
            width="stretch",
            column_config={"連結": st.column_config.LinkColumn("連結", display_text="開啟")},
        )
