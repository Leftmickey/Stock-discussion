"""台股熱度儀表板入口。

    streamlit run app/dashboard.py

想先看看介面長什麼樣而不等 PTT 回補：
    python tools/seed_demo.py
    STOCKHEAT_DB=data/demo.db streamlit run app/dashboard.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "app"))

st.set_page_config(
    page_title="台股熱度追蹤器",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

from lib import data  # noqa: E402

pages = [
    st.Page("views/overview.py", title="今日總覽", icon="🔥", default=True),
    st.Page("views/stock.py", title="個股查詢", icon="🔎"),
    st.Page("views/watchlist.py", title="自選清單", icon="⭐"),
    st.Page("views/audit.py", title="比對稽核", icon="🧪"),
]

with st.sidebar:
    st.title("台股熱度追蹤器")
    latest = data.latest_date()
    if latest:
        st.caption(f"資料日期　**{latest}**")
    else:
        st.warning("尚無熱度資料")

    stats = data.coverage()
    st.caption(f"標的 {stats['stocks']:,} 檔　文章 {stats['posts']:,} 篇")
    st.caption(f"計入熱度的提及 {stats['scored_mentions']:,} 筆")
    if stats["first_post"]:
        st.caption(f"文章區間 {stats['first_post']} ~ {stats['last_post']}")

    st.divider()
    if st.button("重新載入資料", width="stretch"):
        data.clear_caches()
        st.rerun()
    st.caption(f"資料庫：`{data.db_path_label()}`")

st.navigation(pages).run()
