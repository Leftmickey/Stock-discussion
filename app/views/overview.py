"""今日總覽：異常竄升榜為主，熱度排行為輔。"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from lib import data, ui

st.header("今日總覽")

dates = data.available_dates()
if not dates:
    ui.empty_state(
        "資料庫還沒有任何熱度資料。",
        "先執行 `stockheat init` 建立標的主檔，再執行 `stockheat backfill` 回補 30 天討論資料。",
    )
    st.stop()

col_date, col_min = st.columns([1, 2])
with col_date:
    day = st.selectbox("資料日期", dates, index=0)
with col_min:
    # 只被提到一兩次的冷門股 z-score 動輒破表，會把榜單洗掉。
    min_mentions = st.slider(
        "最少提及數", 1, 20, 3, help="過濾只被提到一兩次、統計上不穩定的個股"
    )

scores = data.scores_on(day)
if scores.empty:
    ui.empty_state(f"{day} 沒有熱度資料。")
    st.stop()

market = data.market_sentiment(day)
m1, m2, m3, m4 = st.columns(4)
m1.metric("有討論的個股", f"{len(scores):,} 檔")
m2.metric("總提及數", f"{int(scores['mention_count'].sum()):,} 則")
if market["score"] is not None:
    tone = "偏多" if market["score"] > 0.1 else "偏空" if market["score"] < -0.1 else "中性"
    m3.metric("市場情緒", f"{market['score']:+.2f}", tone)
else:
    m3.metric("市場情緒", "—")

filtered = scores[scores["mention_count"] >= min_mentions].copy()
spikes = filtered[filtered["z_score"] >= 2]
m4.metric("異常竄升", f"{len(spikes)} 檔", help="異常倍數達 +2 以上")

st.divider()

st.subheader("異常竄升榜")
st.caption(
    "這是本頁最該看的表。熱度排行永遠由台積電這類大型股佔據，資訊量有限；"
    "異常倍數比較的是個股與自己過去 30 天的落差，突然被討論才會浮上來。"
)

risers = filtered.sort_values("z_score", ascending=False).head(20)
if risers.empty or risers["z_score"].isna().all():
    ui.empty_state(
        "還沒有足夠的歷史資料可以計算異常倍數。",
        "基準期至少需要 7 個交易日的資料，累積滿 30 天後判斷會更穩定。",
    )
else:
    ui.heat_table(risers)

st.divider()

left, right = st.columns(2)

with left:
    st.subheader("熱度排行")
    st.caption("當日討論量的絕對排名。")
    ui.heat_table(scores.sort_values("raw_heat", ascending=False).head(20))

with right:
    st.subheader("情緒兩端")
    st.caption("在有足夠樣本的個股裡，情緒最偏多與最偏空的各五檔。")
    graded = filtered[filtered["sentiment"].notna()]
    if graded.empty:
        ui.empty_state("樣本不足。")
    else:
        combined = pd.concat([graded.nlargest(5, "sentiment"), graded.nsmallest(5, "sentiment")])
        st.dataframe(
            pd.DataFrame(
                {
                    "代號": combined["symbol"],
                    "名稱": combined["name"],
                    "情緒": combined["sentiment"],
                    "標籤": combined["sentiment_label"],
                    "提及": combined["mention_count"],
                }
            ),
            hide_index=True,
            width="stretch",
            column_config={"情緒": st.column_config.NumberColumn("情緒", format="%+.2f")},
        )

with st.expander("匹配品質概況"):
    breakdown = data.match_type_breakdown(day)
    if breakdown.empty:
        st.caption("當日沒有比對紀錄。")
    else:
        breakdown["說明"] = breakdown["match_type"].map(ui.MATCH_TYPE_LABELS).fillna(
            breakdown["match_type"]
        )
        st.dataframe(
            breakdown[["說明", "n"]].rename(columns={"n": "筆數"}),
            hide_index=True,
            width="stretch",
        )
        st.caption(
            "已排除買賣超排行這類彙整文。信心較低的類別若佔比偏高，"
            "建議到「比對稽核」頁抽樣檢查。"
        )
