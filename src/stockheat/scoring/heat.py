"""熱度聚合與計分。

刻意輸出兩個獨立指標而不是硬湊成單一分數：

  heat_score  當日全市場百分位（0-100）。回答「今天誰被討論得最多」。
              台積電幾乎永遠排第一，所以這個數字本身資訊量有限，
              主要用來排序與顯示量級。

  z_score     相對自身 30 日基準的標準差倍數。回答「它比平常熱多少」。
              真正的訊號在這裡：冷門股的 z 值飆到 2 以上才是值得注意的事件。
"""

from __future__ import annotations

import logging
import math
import sqlite3
from datetime import date, timedelta

import pandas as pd

from stockheat.config import ScoringConfig
from stockheat.scoring import sentiment as sent
from stockheat.storage import repo

logger = logging.getLogger(__name__)


def to_session_date(dates: pd.Series) -> pd.Series:
    """把日期對應到它所屬的交易日：週末發的文歸到下週一。

    週末的討論量只有平日的六分之一。若當成獨立日期計入 30 日基準，
    會把基準整體拉低約三成，於是每個平日看起來都異常熱、每個週末都異常冷。
    週末貼文談的本來就是下一個交易日，歸過去也比較符合語意。

    只處理週六與週日。國定假日需要交易日曆，影響天數少，暫不處理。
    """
    parsed = pd.to_datetime(dates)
    shift = parsed.dt.dayofweek.map({5: 2, 6: 1}).fillna(0).astype(int)
    return (parsed + pd.to_timedelta(shift, unit="D")).dt.strftime("%Y-%m-%d")


def _load_mentions(conn: sqlite3.Connection) -> pd.DataFrame:
    rows = conn.execute(
        """
        SELECT DATE(p.posted_at) AS date, m.symbol, m.confidence, m.in_title,
               p.id AS post_id, p.push_count, p.boo_count, p.neutral_count, p.sentiment
        FROM mentions m JOIN posts p ON p.id = m.post_id
        WHERE p.posted_at IS NOT NULL
        """
    ).fetchall()
    df = pd.DataFrame([dict(r) for r in rows])
    if not df.empty:
        df["date"] = to_session_date(df["date"])
    return df


def _load_news_counts(conn: sqlite3.Connection) -> pd.DataFrame:
    rows = conn.execute(
        """
        SELECT DATE(published_at) AS date, symbol, COUNT(*) AS news_count
        FROM news WHERE published_at IS NOT NULL
        GROUP BY DATE(published_at), symbol
        """
    ).fetchall()
    df = pd.DataFrame([dict(r) for r in rows], columns=["date", "symbol", "news_count"])
    if not df.empty:
        df["date"] = to_session_date(df["date"])
        df = df.groupby(["date", "symbol"], as_index=False)["news_count"].sum()
    return df


def _load_trends(conn: sqlite3.Connection) -> pd.DataFrame:
    rows = conn.execute("SELECT date, symbol, value AS trends_value FROM trends_values").fetchall()
    return pd.DataFrame([dict(r) for r in rows], columns=["date", "symbol", "trends_value"])


def refresh_post_sentiment(conn: sqlite3.Connection, only_missing: bool = True) -> int:
    """計算每篇文章的情緒並寫回 posts。"""
    sql = "SELECT id, title, content, push_count, boo_count FROM posts"
    if only_missing:
        sql += " WHERE sentiment IS NULL"
    posts = conn.execute(sql).fetchall()
    if not posts:
        return 0

    wanted = {p["id"] for p in posts}
    comments_by_post: dict[int, list[dict[str, str]]] = {}
    for row in conn.execute("SELECT post_id, tag, text FROM comments"):
        if row["post_id"] in wanted:
            comments_by_post.setdefault(row["post_id"], []).append(
                {"tag": row["tag"], "text": row["text"] or ""}
            )

    updates = []
    for p in posts:
        breakdown = sent.post_sentiment(
            p["title"],
            p["content"],
            comments=comments_by_post.get(p["id"], []),
            push_count=p["push_count"],
            boo_count=p["boo_count"],
        )
        updates.append((breakdown.score, p["id"]))
    conn.executemany("UPDATE posts SET sentiment = ? WHERE id = ?", updates)
    conn.commit()
    return len(updates)


def drop_listing_posts(mentions: pd.DataFrame, cfg: ScoringConfig) -> tuple[pd.DataFrame, int]:
    """濾掉一次列出大量個股的彙整文。

    「上市外資買賣超排行」這類貼文每個交易日都有，機械式地列出 100 檔股票的
    代號與名稱。它們在比對上是高信心命中，在語意上卻毫無討論成分。
    保留的話熱度會有七成以上是這種雜訊，而且因為天天出現，
    連 z-score 的基準都會被墊高，反而更難看出真正的異常。

    這些提及仍留在資料庫裡供稽核與查閱，只是不計入熱度。
    """
    if mentions.empty:
        return mentions, 0
    per_post = mentions.groupby("post_id")["symbol"].transform("nunique")
    keep = per_post <= cfg.listing_post_threshold
    dropped = int(mentions.loc[~keep, "post_id"].nunique())
    filtered = mentions[keep].copy()
    filtered["symbols_in_post"] = per_post[keep]
    return filtered, dropped


def _raw_heat(row: pd.Series, cfg: ScoringConfig) -> float:
    """取對數是為了壓抑量級差距。

    台積電的討論量是冷門股的數百倍，不壓縮的話任何加權都只是在排序台積電。
    """
    return (
        cfg.weight_posts * math.log1p(row["weighted_posts"])
        + cfg.weight_engagement * math.log1p(row["engagement"])
        + cfg.weight_news * math.log1p(row["news_count"])
    )


def compute_daily_metrics(
    conn: sqlite3.Connection, cfg: ScoringConfig | None = None
) -> pd.DataFrame:
    cfg = cfg or ScoringConfig()
    mentions = _load_mentions(conn)
    if mentions.empty:
        return pd.DataFrame()

    mentions, dropped = drop_listing_posts(mentions, cfg)
    if dropped:
        logger.info("排除 %d 篇彙整文", dropped)
    if mentions.empty:
        return pd.DataFrame()

    mentions["engagement"] = (
        mentions["push_count"] + mentions["boo_count"] + mentions["neutral_count"]
    )
    # 標題命中代表整篇在談這檔，比內文順帶一提更有份量；
    # 同時談多檔則按注意力分攤。
    mentions["weight"] = (
        mentions["confidence"]
        * (1.0 + cfg.title_hit_bonus * mentions["in_title"])
        / mentions["symbols_in_post"] ** cfg.attention_exponent
    )

    grouped = (
        mentions.groupby(["date", "symbol"])
        .agg(
            post_count=("post_id", "nunique"),
            title_post_count=("in_title", "sum"),
            weighted_posts=("weight", "sum"),
            push_sum=("push_count", "sum"),
            boo_sum=("boo_count", "sum"),
            comment_sum=("engagement", "sum"),
            engagement=("engagement", "sum"),
            sentiment=("sentiment", "mean"),
            mention_count=("post_id", "count"),
        )
        .reset_index()
    )

    trends = _load_trends(conn)
    grouped = (
        grouped.merge(trends, on=["date", "symbol"], how="left")
        if not trends.empty
        else grouped.assign(trends_value=None)
    )

    news = _load_news_counts(conn)
    if news.empty:
        grouped["news_count"] = 0
    else:
        grouped = grouped.merge(news, on=["date", "symbol"], how="outer")
        fill = {
            c: 0
            for c in grouped.columns
            if c not in {"date", "symbol", "sentiment", "trends_value"}
        }
        grouped = grouped.fillna(fill)

    grouped["raw_heat"] = grouped.apply(lambda r: _raw_heat(r, cfg), axis=1)
    return grouped


def _expand_zero_days(metrics: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    """把每檔股票在時間窗內沒有討論的日子補成 0。

    這是 z-score 正確與否的關鍵：沒有這一步，基準期只由「有討論的日子」組成，
    平常無人聞問的股票會顯得一直很熱，異常竄升就偵測不出來。

    只補交易日。週末的討論已在前面歸到下一個交易日，這裡再補上零值週末
    等於憑空製造大量低值樣本，會把基準壓低。
    """
    all_dates = pd.bdate_range(start, end).strftime("%Y-%m-%d")
    symbols = metrics["symbol"].unique()
    grid = pd.MultiIndex.from_product(
        [all_dates, symbols], names=["date", "symbol"]
    ).to_frame(index=False)
    merged = grid.merge(metrics, on=["date", "symbol"], how="left")
    numeric = [c for c in merged.columns if c not in {"date", "symbol", "sentiment", "trends_value"}]
    merged[numeric] = merged[numeric].fillna(0)
    return merged


def compute_scores(
    conn: sqlite3.Connection,
    cfg: ScoringConfig | None = None,
    window_days: int | None = None,
) -> dict[str, int]:
    cfg = cfg or ScoringConfig()
    refresh_post_sentiment(conn)

    metrics = compute_daily_metrics(conn, cfg)
    if metrics.empty:
        logger.warning("沒有任何可聚合的提及資料")
        return {"dates": 0, "rows": 0}

    # 聚合層整批重建。只做 UPSERT 會留下上一次計算的孤兒列，
    # 例如日期歸屬規則改變後，舊日期的資料仍會留在表裡。
    conn.execute("DELETE FROM daily_metrics")
    conn.execute("DELETE FROM heat_scores")
    repo.upsert_daily_metrics(conn, metrics.to_dict("records"))

    end = date.fromisoformat(metrics["date"].max())
    span = window_days or (cfg.baseline_days * 2)
    start = max(date.fromisoformat(metrics["date"].min()), end - timedelta(days=span))
    full = _expand_zero_days(metrics[metrics["date"] >= start.isoformat()], start, end)
    full = full.sort_values(["symbol", "date"])

    # 基準只看「今天以前」，否則當天的爆量會被算進自己的基準而稀釋掉。
    shifted = full.groupby("symbol")["raw_heat"].shift(1)
    roll = shifted.groupby(full["symbol"]).rolling(
        cfg.baseline_days, min_periods=cfg.min_baseline_days
    )
    full["baseline_mean"] = roll.mean().reset_index(level=0, drop=True)
    full["baseline_std"] = roll.std().reset_index(level=0, drop=True)
    full["z_score"] = (full["raw_heat"] - full["baseline_mean"]) / (
        full["baseline_std"] + cfg.zscore_epsilon
    )

    # 沒有任何討論的日子不需要輸出評分列。
    active = full[full["raw_heat"] > 0].copy()
    active["heat_score"] = active.groupby("date")["raw_heat"].rank(pct=True) * 100
    active["rank"] = (
        active.groupby("date")["raw_heat"].rank(ascending=False, method="min").astype(int)
    )
    active["prev_rank"] = active.groupby("symbol")["rank"].shift(1)
    active["sentiment_label"] = [
        sent.label(s if pd.notna(s) else None, int(n), cfg)
        for s, n in zip(active["sentiment"], active["mention_count"], strict=False)
    ]

    payload = [
        {
            "date": r["date"],
            "symbol": r["symbol"],
            "raw_heat": float(r["raw_heat"]),
            "heat_score": float(r["heat_score"]),
            "z_score": None if pd.isna(r["z_score"]) else float(r["z_score"]),
            "rank": int(r["rank"]),
            "prev_rank": None if pd.isna(r["prev_rank"]) else int(r["prev_rank"]),
            "sentiment": None if pd.isna(r["sentiment"]) else float(r["sentiment"]),
            "sentiment_label": r["sentiment_label"],
            "mention_count": int(r["mention_count"]),
        }
        for _, r in active.iterrows()
    ]
    repo.upsert_heat_scores(conn, payload)
    conn.commit()

    return {"dates": active["date"].nunique(), "rows": len(payload)}
