"""台股關注熱度掃榜 — Streamlit 本機小工具。"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.db import ensure_ready, get_stock_by_id, list_stocks
from src.services.heat_query import build_board_rows, get_stock_detail, sort_board_rows
from src.services.updater import update_stock, update_stocks

st.set_page_config(
    page_title="台股關注熱度掃榜",
    page_icon="📈",
    layout="wide",
)

CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;600;700&family=IBM+Plex+Sans:wght@500;650&display=swap');
html, body, [class*="css"] {
  font-family: "Noto Sans TC", "IBM Plex Sans", sans-serif;
}
.block-container { padding-top: 1.4rem; }
.hero {
  background: linear-gradient(120deg, #0b3d2e 0%, #1f6f5b 45%, #d9f2e8 100%);
  color: #f4fff9;
  border-radius: 18px;
  padding: 1.4rem 1.6rem;
  margin-bottom: 1rem;
  box-shadow: 0 10px 30px rgba(11, 61, 46, 0.18);
}
.hero h1 {
  margin: 0;
  font-size: 1.8rem;
  letter-spacing: 0.04em;
}
.hero p {
  margin: 0.35rem 0 0 0;
  opacity: 0.92;
}
.metric-note { color: #5b6b66; font-size: 0.9rem; }
</style>
"""


def get_conn():
    if "db_conn" not in st.session_state:
        st.session_state.db_conn = ensure_ready()
    return st.session_state.db_conn


def fmt_score(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{float(v):.1f}"


def fmt_delta(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    sign = "↑" if v > 0 else ("↓" if v < 0 else "→")
    return f"{sign} {v:+.1f}"


def page_board(conn):
    st.markdown(
        """
        <div class="hero">
          <h1>台股關注熱度掃榜</h1>
          <p>Google Trends 搜尋熱度 × PTT Stock 討論熱度｜手動更新｜本機資料</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4 = st.columns([2.2, 1.2, 1.2, 1.4])
    with c1:
        query = st.text_input("搜尋名稱 / 代號 / 別名", placeholder="例如：國巨、2327、臻鼎")
    with c2:
        sort_by = st.selectbox("排序", ["綜合熱度", "Trends", "PTT", "變化", "代號"])
    with c3:
        fetch_trends = st.checkbox("更新 Trends", value=True)
    with c4:
        fetch_ptt = st.checkbox("更新 PTT", value=True)

    b1, b2, b3 = st.columns([1, 1, 2])
    update_all = b1.button("立即更新全部", type="primary", use_container_width=True)
    update_filtered = b2.button("更新目前篩選", use_container_width=True)

    rows = build_board_rows(conn, query=query)
    rows = sort_board_rows(rows, sort_by=sort_by)

    if update_all or update_filtered:
        targets = list_stocks(conn) if update_all else [
            {"id": r["id"], "code": r["code"], "name": r["name"], "aliases": r["aliases"]}
            for r in rows
        ]
        if not targets:
            st.warning("沒有可更新的標的。")
        else:
            progress = st.progress(0.0, text="準備更新…")
            log_box = st.empty()
            logs: list[str] = []

            def on_progress(msg: str):
                logs.append(msg)
                # 粗估進度
                done = sum(1 for x in logs if x.startswith("完成："))
                progress.progress(min(done / max(len(targets), 1), 1.0), text=msg)
                log_box.code("\n".join(logs[-12:]), language="text")

            with st.spinner("正在手動更新熱度，請稍候…"):
                update_stocks(
                    conn,
                    targets,
                    fetch_trends=fetch_trends,
                    fetch_ptt=fetch_ptt,
                    progress=on_progress,
                )
            progress.progress(1.0, text="更新完成")
            st.success(f"已更新 {len(targets)} 檔標的。")
            rows = sort_board_rows(build_board_rows(conn, query=query), sort_by=sort_by)

    if not rows:
        st.info("沒有符合的標的，請調整搜尋字詞。")
        return

    df = pd.DataFrame(
        [
            {
                "標的": r["name"],
                "代號": r["code"],
                "Trends": r["trends"],
                "PTT": r["ptt"],
                "綜合熱度": r["composite"],
                "較上次變化": r["delta"],
                "更新時間": r["updated_at"] or "尚未更新",
                "_id": r["id"],
            }
            for r in rows
        ]
    )

    st.caption("點選下方表格列可進入單檔深挖。分數為 0–100；綜合 = Trends 與 PTT 各半。")
    event = st.dataframe(
        df.drop(columns=["_id"]),
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Trends": st.column_config.NumberColumn(format="%.1f"),
            "PTT": st.column_config.NumberColumn(format="%.1f"),
            "綜合熱度": st.column_config.NumberColumn(format="%.1f"),
            "較上次變化": st.column_config.NumberColumn(format="%+.1f"),
        },
    )

    selected = event.selection.rows if event and event.selection else []
    if selected:
        stock_id = int(df.iloc[selected[0]]["_id"])
        st.session_state["selected_stock_id"] = stock_id
        st.session_state["nav"] = "單檔深挖"
        st.rerun()

    # 變化摘要
    hot = [r for r in rows if r["delta"] is not None]
    if hot:
        top = sorted(hot, key=lambda r: r["delta"], reverse=True)[:3]
        st.markdown("##### 變化較大（相對上次手動更新）")
        st.write(
            "、".join(
                f"{r['name']}（{fmt_delta(r['delta'])}）" for r in top
            )
        )


def page_detail(conn):
    stocks = list_stocks(conn)
    labels = {f"{s['name']}（{s['code']}）": s["id"] for s in stocks}
    default_id = st.session_state.get("selected_stock_id")
    default_label = None
    for label, sid in labels.items():
        if sid == default_id:
            default_label = label
            break
    options = list(labels.keys())
    idx = options.index(default_label) if default_label in options else 0

    st.markdown(
        """
        <div class="hero">
          <h1>單檔深挖</h1>
          <p>歷史曲線、PTT Stock 近文與別名資訊</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        chosen = st.selectbox("選擇標的", options, index=idx)
    with c2:
        days = st.selectbox("曲線區間", [7, 30], index=0)
    with c3:
        st.write("")
        st.write("")
        do_update = st.button("更新此標的", type="primary", use_container_width=True)

    stock_id = labels[chosen]
    st.session_state["selected_stock_id"] = stock_id
    stock = get_stock_by_id(conn, stock_id)

    if do_update and stock:
        log_box = st.empty()
        logs: list[str] = []

        def on_progress(msg: str):
            logs.append(msg)
            log_box.code("\n".join(logs), language="text")

        with st.spinner(f"更新 {stock['name']}…"):
            update_stock(conn, stock, progress=on_progress)
        st.success("此標的已更新。")

    detail = get_stock_detail(conn, stock_id, history_days=int(days))
    if not detail:
        st.error("找不到標的。")
        return

    latest = detail["latest"]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("綜合熱度", fmt_score(latest["composite_score"] if latest else None))
    m2.metric("Trends", fmt_score(latest["trends_score"] if latest else None))
    m3.metric("PTT", fmt_score(latest["ptt_score"] if latest else None))
    m4.metric("更新時間", (latest["ts"] if latest else "尚未更新"))

    aliases = [a for a in (stock["aliases"] if stock else []) if a not in {stock["name"], stock["code"]}]
    st.caption("別名：" + ("、".join(aliases) if aliases else "（無額外別名）"))

    if latest and (latest.get("trends_error") or latest.get("ptt_error")):
        if latest.get("trends_error"):
            st.warning(f"Trends：{latest['trends_error']}")
        if latest.get("ptt_error"):
            st.warning(f"PTT：{latest['ptt_error']}")

    history = detail["history"]
    if not history:
        st.info("尚無歷史，更新後開始累積曲線。")
    else:
        hdf = pd.DataFrame(history)
        hdf["ts"] = pd.to_datetime(hdf["ts"])
        long_df = hdf.melt(
            id_vars=["ts"],
            value_vars=["trends_score", "ptt_score", "composite_score"],
            var_name="指標",
            value_name="分數",
        )
        long_df["指標"] = long_df["指標"].map(
            {
                "trends_score": "Trends",
                "ptt_score": "PTT",
                "composite_score": "綜合",
            }
        )
        fig = px.line(
            long_df,
            x="ts",
            y="分數",
            color="指標",
            markers=True,
            title=f"{stock['name']}（{stock['code']}）熱度曲線",
        )
        fig.update_layout(
            template="plotly_white",
            height=380,
            margin=dict(l=20, r=20, t=50, b=20),
            legend_title_text="",
        )
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("##### PTT Stock 近文")
    posts = detail["posts"]
    if not posts:
        st.write("尚無文章資料，請先更新此標的。")
    else:
        pdf = pd.DataFrame(
            [
                {
                    "推文": p["push_count"],
                    "標題": p["title"],
                    "時間": p.get("posted_at") or "",
                    "連結": p["url"],
                }
                for p in posts
            ]
        )
        st.dataframe(
            pdf,
            use_container_width=True,
            hide_index=True,
            column_config={
                "連結": st.column_config.LinkColumn("連結"),
                "推文": st.column_config.NumberColumn(format="%d"),
            },
        )


def main():
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    conn = get_conn()

    if "nav" not in st.session_state:
        st.session_state["nav"] = "晨檢掃榜"

    with st.sidebar:
        st.markdown("### 導覽")
        nav = st.radio(
            "頁面",
            ["晨檢掃榜", "單檔深挖"],
            index=0 if st.session_state["nav"] == "晨檢掃榜" else 1,
            label_visibility="collapsed",
        )
        st.session_state["nav"] = nav
        st.markdown("---")
        st.markdown(
            """
            **資料來源**
            - Google Trends（台灣）
            - PTT `Stock`（官方站／pttweb）

            **更新方式**
            - 僅手動更新
            - 資料存於本機 SQLite
            - Trends 易被限流，可先只更新 PTT
            """
        )
        st.caption("本工具僅供關注熱度參考，非投資建議。")

    if st.session_state["nav"] == "晨檢掃榜":
        page_board(conn)
    else:
        page_detail(conn)


if __name__ == "__main__":
    main()
