"""比對稽核。

熱度數字只有在比對可信時才有意義。這一頁把信心最低的命中排在最前面，
讓誤判能被看見、被標記，並直接回饋到消歧規則。
"""

from __future__ import annotations

import streamlit as st

from lib import data, ui
from stockheat.resources import add_user_generic_name, load_user_generic_names, user_generic_path

st.header("比對稽核")
st.caption(
    "全市場 2,400 檔標的的名稱空間必然重疊，任何自動比對都會有誤判。"
    "與其假裝沒有，不如讓它容易被查到、容易被修正。"
)

stats = data.coverage()
c1, c2, c3, c4 = st.columns(4)
c1.metric("文章總數", f"{stats['posts']:,}")
c2.metric("提及總數", f"{stats['mentions']:,}")
c3.metric(
    "計入熱度",
    f"{stats['scored_mentions']:,}",
    help="排除彙整文之後實際用於計分的提及數",
)
c4.metric(
    "彙整文",
    f"{stats['listing_posts']:,} 篇",
    help="買賣超排行這類一次列出大量個股的貼文，不計入熱度",
)

if stats["mentions"]:
    excluded = stats["mentions"] - stats["scored_mentions"]
    st.caption(
        f"彙整文貢獻了 {excluded:,} 筆提及（佔 {excluded / stats['mentions'] * 100:.0f}%）。"
        "這類貼文每個交易日都有、機械式列出上百檔股票，"
        "計入的話熱度會有大半是它們，連基準都會被墊高。"
    )

st.divider()

st.subheader("整體命中方式分佈")
st.caption("已排除彙整文，反映實際用於計分的部分。")
breakdown = data.match_type_breakdown()
if breakdown.empty:
    ui.empty_state("尚無比對紀錄。")
else:
    breakdown["說明"] = breakdown["match_type"].map(ui.MATCH_TYPE_LABELS).fillna(
        breakdown["match_type"]
    )
    total = breakdown["n"].sum()
    breakdown["佔比"] = breakdown["n"] / total * 100
    st.dataframe(
        breakdown[["說明", "n", "佔比"]].rename(columns={"n": "筆數"}),
        hide_index=True,
        width="stretch",
        column_config={"佔比": st.column_config.NumberColumn("佔比", format="%.1f%%")},
    )

st.divider()

st.subheader("低信心命中抽查")
st.caption("依信心由低到高排序。發現不該算的，標記為誤判並把該別名加進通用詞清單。")

rows = data.low_confidence_mentions()
if rows.empty:
    ui.empty_state("沒有可稽核的紀錄。")
    st.stop()

if st.checkbox("只看尚未標記的", value=True):
    rows = rows[rows["verdict"].isna()]

if rows.empty:
    st.success("低信心的命中都已經檢查過了。")
else:
    for _, row in rows.head(25).iterrows():
        with st.container(border=True):
            top, actions = st.columns([5, 2])
            with top:
                st.markdown(
                    f"**{row['symbol']}　{row['name']}**　"
                    f"`{ui.MATCH_TYPE_SHORT.get(row['match_type'], row['match_type'])}`　"
                    f"信心 {row['confidence']:.2f}"
                )
                st.markdown(f"[{row['title']}]({row['url']})")
                st.caption(f"{row['posted_at']}　{row['evidence'] or ''}")
            with actions:
                key = f"{row['post_id']}_{row['symbol']}"
                ok, bad = st.columns(2)
                if ok.button("正確", key=f"ok_{key}", width="stretch"):
                    data.record_feedback(int(row["post_id"]), row["symbol"], "correct")
                    st.rerun()
                if bad.button("誤判", key=f"bad_{key}", width="stretch"):
                    data.record_feedback(int(row["post_id"]), row["symbol"], "wrong")
                    st.rerun()

st.divider()

st.subheader("通用詞清單")
st.caption(
    "被加入這份清單的名稱，必須在同篇文章看到股票代號才會被採計。"
    "適合用來處理「數字」「時報」「系統」這類與日常用語重疊的簡稱——"
    "它們常常是被更長的詞包住而誤中（「營收數字」「工商時報」「作業系統」）。"
)

user_terms = load_user_generic_names()
st.caption(f"使用者清單：`{user_generic_path()}`（目前 {len(user_terms)} 個詞）")
if user_terms:
    st.write("　".join(f"`{t}`" for t in user_terms))

new_term = st.text_input("新增通用詞", placeholder="例如 數字")
if st.button("加入清單") and new_term.strip():
    if add_user_generic_name(new_term.strip()):
        st.success(
            f"已加入「{new_term.strip()}」。"
            "執行 `stockheat init` 重建別名層級後，再執行 `stockheat rematch` 讓它生效。"
        )
    else:
        st.info("這個詞已經在清單裡了。")
