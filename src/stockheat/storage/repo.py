"""資料表讀寫。全部走 UPSERT，讓 pipeline 可以任意重跑而不產生重複資料。"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any

from stockheat.config import TAIPEI

# 提及超過這個檔數的文章是彙整文（買賣超排行之類），預設不呈現也不計分。
DEFAULT_LISTING_THRESHOLD = 12


def _now() -> str:
    return datetime.now(TAIPEI).isoformat(timespec="seconds")


# ------------------------------------------------------------------ 標的主檔


def upsert_stocks(conn: sqlite3.Connection, rows: Iterable[dict[str, Any]]) -> int:
    payload = [
        (
            r["symbol"],
            r["name"],
            r["clean_name"],
            r["market"],
            r.get("security_type", "stock"),
            int(r.get("is_active", 1)),
            _now(),
        )
        for r in rows
    ]
    conn.executemany(
        """
        INSERT INTO stocks (symbol, name, clean_name, market, security_type, is_active, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol) DO UPDATE SET
            name = excluded.name,
            clean_name = excluded.clean_name,
            market = excluded.market,
            security_type = excluded.security_type,
            is_active = excluded.is_active,
            updated_at = excluded.updated_at
        """,
        payload,
    )
    return len(payload)


def replace_aliases(conn: sqlite3.Connection, rows: Iterable[dict[str, Any]]) -> int:
    payload = [
        (r["symbol"], r["alias"], r["alias_type"], int(r.get("requires_context", 0)))
        for r in rows
    ]
    # 手動加入的別名不會被自動生成覆蓋。
    conn.execute("DELETE FROM aliases WHERE alias_type != 'manual'")
    conn.executemany(
        """
        INSERT INTO aliases (symbol, alias, alias_type, requires_context)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(symbol, alias) DO UPDATE SET
            alias_type = excluded.alias_type,
            requires_context = excluded.requires_context
        """,
        payload,
    )
    return len(payload)


def all_stocks(conn: sqlite3.Connection, active_only: bool = True) -> list[sqlite3.Row]:
    sql = "SELECT * FROM stocks"
    if active_only:
        sql += " WHERE is_active = 1"
    return conn.execute(sql + " ORDER BY symbol").fetchall()


def all_aliases(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT a.symbol, a.alias, a.alias_type, a.requires_context
        FROM aliases a JOIN stocks s ON s.symbol = a.symbol
        WHERE s.is_active = 1
        """
    ).fetchall()


def get_stock(conn: sqlite3.Connection, symbol: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM stocks WHERE symbol = ?", (symbol,)).fetchone()


def search_stocks(conn: sqlite3.Connection, keyword: str, limit: int = 30) -> list[sqlite3.Row]:
    """代號或名稱的模糊搜尋，代號完全命中優先。

    權證的名稱含有標的股名稱（「世界群益5B售01」），數量又以千計，
    不排除的話任何熱門股的搜尋結果都會被它們淹沒。
    """
    like = f"%{keyword}%"
    return conn.execute(
        """
        SELECT DISTINCT s.*
        FROM stocks s
        LEFT JOIN aliases a ON a.symbol = s.symbol
        WHERE s.is_active = 1
          AND s.security_type NOT IN ('warrant', 'other')
          AND (s.symbol LIKE ? OR s.name LIKE ? OR s.clean_name LIKE ? OR a.alias LIKE ?)
        ORDER BY (s.symbol = ?) DESC, LENGTH(s.symbol), s.symbol
        LIMIT ?
        """,
        (like, like, like, like, keyword, limit),
    ).fetchall()


# ------------------------------------------------------------------ 文章


def upsert_post(conn: sqlite3.Connection, post: dict[str, Any]) -> int:
    cur = conn.execute(
        """
        INSERT INTO posts (source, source_id, board, title, author, url, posted_at,
                           push_count, boo_count, neutral_count, content, fetched_at)
        VALUES (:source, :source_id, :board, :title, :author, :url, :posted_at,
                :push_count, :boo_count, :neutral_count, :content, :fetched_at)
        ON CONFLICT(source, source_id) DO UPDATE SET
            title = excluded.title,
            push_count = excluded.push_count,
            boo_count = excluded.boo_count,
            neutral_count = excluded.neutral_count,
            content = excluded.content,
            fetched_at = excluded.fetched_at,
            -- 推文數變了，情緒要重算。
            sentiment = NULL
        RETURNING id
        """,
        {
            "source": post.get("source", "ptt"),
            "source_id": post["source_id"],
            "board": post.get("board"),
            "title": post["title"],
            "author": post.get("author"),
            "url": post["url"],
            "posted_at": post.get("posted_at"),
            "push_count": post.get("push_count", 0),
            "boo_count": post.get("boo_count", 0),
            "neutral_count": post.get("neutral_count", 0),
            "content": post.get("content"),
            "fetched_at": post.get("fetched_at") or _now(),
        },
    )
    return int(cur.fetchone()[0])


def replace_comments(
    conn: sqlite3.Connection, post_id: int, comments: Sequence[dict[str, Any]]
) -> None:
    conn.execute("DELETE FROM comments WHERE post_id = ?", (post_id,))
    conn.executemany(
        "INSERT INTO comments (post_id, seq, tag, author, text) VALUES (?, ?, ?, ?, ?)",
        [(post_id, i, c["tag"], c.get("author"), c.get("text")) for i, c in enumerate(comments)],
    )


def existing_source_ids(conn: sqlite3.Connection, source: str = "ptt") -> set[str]:
    return {r[0] for r in conn.execute("SELECT source_id FROM posts WHERE source = ?", (source,))}


def all_posts(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM posts ORDER BY posted_at").fetchall()


# ------------------------------------------------------------------ 匹配


def replace_mentions_for_post(
    conn: sqlite3.Connection, post_id: int, mentions: Sequence[dict[str, Any]]
) -> None:
    conn.execute("DELETE FROM mentions WHERE post_id = ?", (post_id,))
    conn.executemany(
        """
        INSERT INTO mentions (post_id, symbol, match_type, confidence, in_title, evidence)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(post_id, symbol) DO NOTHING
        """,
        [
            (
                post_id,
                m["symbol"],
                m["match_type"],
                m["confidence"],
                int(m.get("in_title", 0)),
                m.get("evidence"),
            )
            for m in mentions
        ],
    )


def mentions_for_symbol(
    conn: sqlite3.Connection,
    symbol: str,
    limit: int = 200,
    listing_threshold: int | None = DEFAULT_LISTING_THRESHOLD,
) -> list[sqlite3.Row]:
    """個股的提及原文。

    預設濾掉彙整文，否則熱門股的清單會被每日重複的買賣超排行塞滿，
    看不到真正的討論。
    """
    sql = """
        SELECT p.id AS post_id, p.title, p.url, p.posted_at, p.author,
               p.push_count, p.boo_count, p.sentiment,
               m.match_type, m.confidence, m.in_title, m.evidence
        FROM mentions m JOIN posts p ON p.id = m.post_id
        WHERE m.symbol = ?
    """
    params: list[Any] = [symbol]
    if listing_threshold is not None:
        sql += " AND (SELECT COUNT(*) FROM mentions m2 WHERE m2.post_id = m.post_id) <= ?"
        params.append(listing_threshold)
    sql += " ORDER BY p.posted_at DESC LIMIT ?"
    params.append(limit)
    return conn.execute(sql, params).fetchall()


# ------------------------------------------------------------------ 新聞與行情


def upsert_news(conn: sqlite3.Connection, rows: Iterable[dict[str, Any]]) -> int:
    payload = [
        (r["symbol"], r["title"], r["url"], r.get("publisher"), r.get("published_at"), _now())
        for r in rows
    ]
    conn.executemany(
        """
        INSERT INTO news (symbol, title, url, publisher, published_at, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol, url) DO NOTHING
        """,
        payload,
    )
    return len(payload)


def upsert_prices(conn: sqlite3.Connection, rows: Iterable[dict[str, Any]]) -> int:
    payload = [
        (
            r["date"],
            r["symbol"],
            r.get("open"),
            r.get("high"),
            r.get("low"),
            r.get("close"),
            r.get("change"),
            r.get("volume"),
        )
        for r in rows
    ]
    conn.executemany(
        """
        INSERT INTO prices (date, symbol, open, high, low, close, change, volume)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(date, symbol) DO UPDATE SET
            open = excluded.open, high = excluded.high, low = excluded.low,
            close = excluded.close, change = excluded.change, volume = excluded.volume
        """,
        payload,
    )
    return len(payload)


def price_history(conn: sqlite3.Connection, symbol: str, days: int = 90) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM prices WHERE symbol = ? ORDER BY date DESC LIMIT ?", (symbol, days)
    ).fetchall()


# ------------------------------------------------------------------ 聚合


def upsert_daily_metrics(conn: sqlite3.Connection, rows: Iterable[dict[str, Any]]) -> int:
    payload = [
        (
            r["date"],
            r["symbol"],
            int(r.get("post_count", 0)),
            int(r.get("title_post_count", 0)),
            int(r.get("push_sum", 0)),
            int(r.get("boo_sum", 0)),
            int(r.get("comment_sum", 0)),
            int(r.get("news_count", 0)),
            r.get("trends_value"),
            float(r.get("raw_heat", 0.0)),
        )
        for r in rows
    ]
    conn.executemany(
        """
        INSERT INTO daily_metrics (date, symbol, post_count, title_post_count, push_sum,
                                   boo_sum, comment_sum, news_count, trends_value, raw_heat)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(date, symbol) DO UPDATE SET
            post_count = excluded.post_count,
            title_post_count = excluded.title_post_count,
            push_sum = excluded.push_sum,
            boo_sum = excluded.boo_sum,
            comment_sum = excluded.comment_sum,
            news_count = excluded.news_count,
            trends_value = excluded.trends_value,
            raw_heat = excluded.raw_heat
        """,
        payload,
    )
    return len(payload)


def upsert_heat_scores(conn: sqlite3.Connection, rows: Iterable[dict[str, Any]]) -> int:
    payload = [
        (
            r["date"],
            r["symbol"],
            r["raw_heat"],
            r["heat_score"],
            r.get("z_score"),
            r.get("rank"),
            r.get("prev_rank"),
            r.get("sentiment"),
            r.get("sentiment_label"),
            int(r.get("mention_count", 0)),
        )
        for r in rows
    ]
    conn.executemany(
        """
        INSERT INTO heat_scores (date, symbol, raw_heat, heat_score, z_score, rank,
                                 prev_rank, sentiment, sentiment_label, mention_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(date, symbol) DO UPDATE SET
            raw_heat = excluded.raw_heat,
            heat_score = excluded.heat_score,
            z_score = excluded.z_score,
            rank = excluded.rank,
            prev_rank = excluded.prev_rank,
            sentiment = excluded.sentiment,
            sentiment_label = excluded.sentiment_label,
            mention_count = excluded.mention_count
        """,
        payload,
    )
    return len(payload)


def latest_score_date(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT MAX(date) FROM heat_scores").fetchone()
    return row[0] if row and row[0] else None


def scores_on(conn: sqlite3.Connection, date: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT h.*, s.name, s.market
        FROM heat_scores h JOIN stocks s ON s.symbol = h.symbol
        WHERE h.date = ?
        ORDER BY h.raw_heat DESC
        """,
        (date,),
    ).fetchall()


def score_history(conn: sqlite3.Connection, symbol: str, days: int = 60) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT h.*, d.post_count, d.push_sum, d.boo_sum, d.news_count
        FROM heat_scores h
        LEFT JOIN daily_metrics d ON d.date = h.date AND d.symbol = h.symbol
        WHERE h.symbol = ?
        ORDER BY h.date DESC
        LIMIT ?
        """,
        (symbol, days),
    ).fetchall()


# ------------------------------------------------------------------ 自選與狀態


def set_watchlist(conn: sqlite3.Connection, symbols: Sequence[str]) -> None:
    conn.execute("DELETE FROM watchlist")
    conn.executemany(
        "INSERT INTO watchlist (symbol, sort_order, added_at) VALUES (?, ?, ?)",
        [(s, i, _now()) for i, s in enumerate(symbols)],
    )


def add_to_watchlist(conn: sqlite3.Connection, symbol: str) -> None:
    nxt = conn.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM watchlist").fetchone()[0]
    conn.execute(
        "INSERT OR IGNORE INTO watchlist (symbol, sort_order, added_at) VALUES (?, ?, ?)",
        (symbol, int(nxt), _now()),
    )


def remove_from_watchlist(conn: sqlite3.Connection, symbol: str) -> None:
    conn.execute("DELETE FROM watchlist WHERE symbol = ?", (symbol,))


def get_watchlist(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT w.symbol, s.name, s.market
        FROM watchlist w LEFT JOIN stocks s ON s.symbol = w.symbol
        ORDER BY w.sort_order
        """
    ).fetchall()


def set_fetch_state(
    conn: sqlite3.Connection,
    source: str,
    target: str,
    status: str,
    cursor: str | None = None,
    message: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO fetch_log (source, target, cursor, status, message, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, target) DO UPDATE SET
            cursor = excluded.cursor,
            status = excluded.status,
            message = excluded.message,
            updated_at = excluded.updated_at
        """,
        (source, target, cursor, status, message, _now()),
    )


def record_feedback(
    conn: sqlite3.Connection, post_id: int, symbol: str, verdict: str, note: str | None = None
) -> None:
    conn.execute(
        """
        INSERT INTO match_feedback (post_id, symbol, verdict, note, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(post_id, symbol) DO UPDATE SET
            verdict = excluded.verdict, note = excluded.note, created_at = excluded.created_at
        """,
        (post_id, symbol, verdict, note, _now()),
    )
