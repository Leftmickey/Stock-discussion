"""儀表板的資料存取。

UI 只透過這一層讀資料，核心邏輯完全不依賴 Streamlit，
之後要換成 FastAPI 加前端不必動到資料層。
"""

from __future__ import annotations

import sqlite3
import threading

import pandas as pd
import streamlit as st

from stockheat.config import DB_PATH
from stockheat.storage import db, repo
from stockheat.storage.repo import DEFAULT_LISTING_THRESHOLD

# Streamlit 每次重跑腳本可能落在不同的工作執行緒，而 SQLite 連線物件綁定
# 建立它的執行緒。用 st.cache_resource 共用單一連線會在使用者第一次操作元件時
# 就丟出 ProgrammingError，所以改成每個執行緒各持有一條連線。
# WAL 模式下多連線讀寫是安全的。
_local = threading.local()


def get_conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = db.init_db()
        _local.conn = conn
    return conn


def db_path_label() -> str:
    return str(DB_PATH)


def _frame(rows) -> pd.DataFrame:
    return pd.DataFrame([dict(r) for r in rows])


@st.cache_data(ttl=120)
def latest_date() -> str | None:
    return repo.latest_score_date(get_conn())


@st.cache_data(ttl=120)
def available_dates(limit: int = 60) -> list[str]:
    return [
        r[0]
        for r in get_conn().execute(
            "SELECT DISTINCT date FROM heat_scores ORDER BY date DESC LIMIT ?", (limit,)
        )
    ]


@st.cache_data(ttl=120)
def scores_on(day: str) -> pd.DataFrame:
    df = _frame(repo.scores_on(get_conn(), day))
    if not df.empty:
        df["rank_change"] = df["prev_rank"] - df["rank"]
    return df


@st.cache_data(ttl=120)
def watchlist_symbols() -> list[str]:
    return [r["symbol"] for r in repo.get_watchlist(get_conn())]


@st.cache_data(ttl=120)
def watchlist_view(day: str) -> pd.DataFrame:
    return _frame(
        get_conn().execute(
            """
            SELECT w.symbol, s.name, s.market,
                   h.heat_score, h.z_score, h.rank, h.prev_rank,
                   h.sentiment, h.sentiment_label, h.mention_count,
                   p.close, p.change
            FROM watchlist w
            LEFT JOIN stocks s ON s.symbol = w.symbol
            LEFT JOIN heat_scores h ON h.symbol = w.symbol AND h.date = ?
            LEFT JOIN prices p ON p.symbol = w.symbol
                 AND p.date = (SELECT MAX(date) FROM prices WHERE symbol = w.symbol)
            ORDER BY w.sort_order
            """,
            (day,),
        )
    )


@st.cache_data(ttl=120)
def search(keyword: str) -> pd.DataFrame:
    return _frame(repo.search_stocks(get_conn(), keyword.strip()))


@st.cache_data(ttl=120)
def stock_info(symbol: str) -> dict | None:
    row = repo.get_stock(get_conn(), symbol)
    return dict(row) if row else None


@st.cache_data(ttl=120)
def heat_history(symbol: str, days: int = 60) -> pd.DataFrame:
    df = _frame(repo.score_history(get_conn(), symbol, days))
    return df.sort_values("date") if not df.empty else df


@st.cache_data(ttl=120)
def price_history(symbol: str, days: int = 90) -> pd.DataFrame:
    df = _frame(repo.price_history(get_conn(), symbol, days))
    return df.sort_values("date") if not df.empty else df


@st.cache_data(ttl=120)
def mentions(symbol: str, limit: int = 200) -> pd.DataFrame:
    return _frame(repo.mentions_for_symbol(get_conn(), symbol, limit))


@st.cache_data(ttl=120)
def news_for(symbol: str, limit: int = 30) -> pd.DataFrame:
    return _frame(
        get_conn().execute(
            """
            SELECT title, url, publisher, published_at FROM news
            WHERE symbol = ? ORDER BY published_at DESC LIMIT ?
            """,
            (symbol, limit),
        )
    )


@st.cache_data(ttl=120)
def market_sentiment(day: str) -> dict:
    """當日全市場情緒溫度：以提及數為權重的加權平均。"""
    row = get_conn().execute(
        """
        SELECT SUM(sentiment * mention_count) AS weighted,
               SUM(mention_count) AS total,
               COUNT(*) AS symbols
        FROM heat_scores WHERE date = ? AND sentiment IS NOT NULL
        """,
        (day,),
    ).fetchone()
    total = row["total"] or 0
    return {
        "score": (row["weighted"] / total) if total else None,
        "mentions": int(total),
        "symbols": int(row["symbols"] or 0),
    }


@st.cache_data(ttl=120)
def coverage() -> dict:
    conn = get_conn()

    def scalar(sql: str):
        return conn.execute(sql).fetchone()[0]

    return {
        "stocks": scalar("SELECT COUNT(*) FROM stocks WHERE is_active = 1"),
        "posts": scalar("SELECT COUNT(*) FROM posts"),
        "mentions": scalar("SELECT COUNT(*) FROM mentions"),
        "scored_mentions": scalar(
            "SELECT COUNT(*) FROM mentions m WHERE"
            " (SELECT COUNT(*) FROM mentions m2 WHERE m2.post_id = m.post_id) <= "
            f"{DEFAULT_LISTING_THRESHOLD}"
        ),
        "listing_posts": scalar(
            "SELECT COUNT(*) FROM (SELECT post_id FROM mentions GROUP BY post_id"
            f" HAVING COUNT(*) > {DEFAULT_LISTING_THRESHOLD})"
        ),
        "news": scalar("SELECT COUNT(*) FROM news"),
        "first_post": scalar("SELECT MIN(DATE(posted_at)) FROM posts"),
        "last_post": scalar("SELECT MAX(DATE(posted_at)) FROM posts"),
    }


@st.cache_data(ttl=120)
def match_type_breakdown(day: str | None = None, exclude_listing: bool = True) -> pd.DataFrame:
    sql = """
        SELECT m.match_type, COUNT(*) AS n
        FROM mentions m JOIN posts p ON p.id = m.post_id
        WHERE 1 = 1
    """
    params: list = []
    if exclude_listing:
        sql += (
            " AND (SELECT COUNT(*) FROM mentions m2 WHERE m2.post_id = m.post_id) <= "
            f"{DEFAULT_LISTING_THRESHOLD}"
        )
    if day:
        sql += " AND DATE(p.posted_at) = ?"
        params.append(day)
    sql += " GROUP BY m.match_type ORDER BY n DESC"
    return _frame(get_conn().execute(sql, params))


@st.cache_data(ttl=120)
def low_confidence_mentions(limit: int = 120) -> pd.DataFrame:
    """信心最低的命中，稽核時優先看這些。彙整文不列入，它們不影響熱度。"""
    return _frame(
        get_conn().execute(
            """
            SELECT m.post_id, m.symbol, s.name, m.match_type, m.confidence, m.evidence,
                   p.title, p.url, p.posted_at, f.verdict
            FROM mentions m
            JOIN posts p ON p.id = m.post_id
            JOIN stocks s ON s.symbol = m.symbol
            LEFT JOIN match_feedback f ON f.post_id = m.post_id AND f.symbol = m.symbol
            WHERE (SELECT COUNT(*) FROM mentions m2 WHERE m2.post_id = m.post_id) <= ?
            ORDER BY m.confidence ASC, p.posted_at DESC
            LIMIT ?
            """,
            (DEFAULT_LISTING_THRESHOLD, limit),
        )
    )


def clear_caches() -> None:
    st.cache_data.clear()


def record_feedback(post_id: int, symbol: str, verdict: str, note: str | None = None) -> None:
    conn = get_conn()
    repo.record_feedback(conn, post_id, symbol, verdict, note)
    conn.commit()
    clear_caches()


def add_watch(symbol: str) -> None:
    conn = get_conn()
    repo.add_to_watchlist(conn, symbol)
    conn.commit()
    clear_caches()


def remove_watch(symbol: str) -> None:
    conn = get_conn()
    repo.remove_from_watchlist(conn, symbol)
    conn.commit()
    clear_caches()
