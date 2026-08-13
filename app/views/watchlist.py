"""自選清單：預設為使用者提供的 30 檔，可增刪。"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from lib import data, ui

st.header("自選清單")

latest = data.latest_date()
if not latest:
    ui.empty_state("尚無熱度資料。", "先執行 `stockheat backfill` 回補討論資料。")
    st.stop()

view = data.watchlist_view(latest)
if view.empty:
    ui.empty_state("自選清單是空的。", "到「個股查詢」頁搜尋標的後即可加入。")
    st.stop()

st.caption(f"資料日期 {latest}。未列出熱度的個股代表當天沒有被討論。")

c1, c2, c3 = st.columns(3)
c1.metric("自選檔數", f"{len(view)} 檔")
c2.metric("當日有討論", f"{int(view['mention_count'].fillna(0).gt(0).sum())} 檔")
c3.metric("異常竄升", f"{int((view['z_score'].fillna(0) >= 2).sum())} 檔")

st.dataframe(
    pd.DataFrame(
        {
            "代號": view["symbol"],
            "名稱": view["name"],
            "收盤": view["close"],
            "漲跌": view["change"],
            "異常倍數": view["z_score"],
            "熱度": view["heat_score"].fillna(0),
            "排名": view["rank"],
            "情緒": view["sentiment_label"].fillna("無討論"),
            "提及": view["mention_count"].fillna(0).astype(int),
        }
    ),
    hide_index=True,
    width="stretch",
    column_config={
        "收盤": st.column_config.NumberColumn("收盤", format="%.2f"),
        "漲跌": st.column_config.NumberColumn("漲跌", format="%+.2f"),
        "異常倍數": st.column_config.NumberColumn(
            "異常倍數", format="%+.2f", help="相對自身 30 日基準的標準差倍數"
        ),
        "熱度": st.column_config.ProgressColumn("熱度", min_value=0, max_value=100, format="%.0f"),
    },
)

st.divider()

col_add, col_remove = st.columns(2)

with col_add:
    st.subheader("加入標的")
    keyword = st.text_input("代號或名稱", key="wl_add", placeholder="例如 6669 或 緯穎")
    if keyword.strip():
        found = data.search(keyword)
        if found.empty:
            st.caption(f"找不到「{keyword}」。")
        else:
            options = [f"{r.symbol}　{r['name']}" for _, r in found.iterrows()]
            picked = st.selectbox("選擇", options, key="wl_add_pick")
            if st.button("加入自選"):
                data.add_watch(picked.split("　")[0])
                st.rerun()

with col_remove:
    st.subheader("移除標的")
    current = [f"{r.symbol}　{r['name']}" for _, r in view.iterrows()]
    to_remove = st.selectbox("選擇要移除的標的", current, key="wl_remove")
    if st.button("移出自選"):
        data.remove_watch(to_remove.split("　")[0])
        st.rerun()
