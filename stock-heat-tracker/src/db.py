"""SQLite 資料存取層。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT / "data" / "app.db"
DEFAULT_STOCKS_PATH = ROOT / "data" / "stocks.json"


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS stocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_id INTEGER NOT NULL,
            alias TEXT NOT NULL,
            UNIQUE(stock_id, alias),
            FOREIGN KEY(stock_id) REFERENCES stocks(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS heat_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_id INTEGER NOT NULL,
            ts TEXT NOT NULL,
            trends_score REAL,
            ptt_score REAL,
            composite_score REAL,
            trends_error TEXT,
            ptt_error TEXT,
            FOREIGN KEY(stock_id) REFERENCES stocks(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_heat_stock_ts
            ON heat_snapshots(stock_id, ts);

        CREATE TABLE IF NOT EXISTS ptt_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_id INTEGER NOT NULL,
            post_id TEXT NOT NULL,
            board TEXT NOT NULL DEFAULT 'Stock',
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            push_count INTEGER NOT NULL DEFAULT 0,
            posted_at TEXT,
            fetched_at TEXT NOT NULL,
            UNIQUE(stock_id, post_id),
            FOREIGN KEY(stock_id) REFERENCES stocks(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_ptt_stock_fetched
            ON ptt_posts(stock_id, fetched_at);
        """
    )
    conn.commit()


def seed_stocks(
    conn: sqlite3.Connection,
    stocks_path: Path | str | None = None,
    force: bool = False,
) -> int:
    """從 JSON 載入標的；若已有資料且 force=False 則跳過。"""
    path = Path(stocks_path) if stocks_path else DEFAULT_STOCKS_PATH
    existing = conn.execute("SELECT COUNT(*) AS c FROM stocks").fetchone()["c"]
    if existing and not force:
        return 0

    with path.open(encoding="utf-8") as f:
        items: list[dict[str, Any]] = json.load(f)

    if force:
        conn.execute("DELETE FROM aliases")
        conn.execute("DELETE FROM stocks")

    inserted = 0
    for item in items:
        cur = conn.execute(
            "INSERT OR IGNORE INTO stocks(code, name, enabled) VALUES (?, ?, 1)",
            (item["code"], item["name"]),
        )
        if cur.rowcount:
            inserted += 1
        row = conn.execute(
            "SELECT id FROM stocks WHERE code = ?", (item["code"],)
        ).fetchone()
        stock_id = row["id"]
        aliases = set(item.get("aliases") or [])
        aliases.add(item["name"])
        aliases.add(item["code"])
        # 正規化變體
        for alias in list(aliases):
            cleaned = alias.replace("*", "").replace("-KY", "").replace("KY", "")
            if cleaned and cleaned != alias:
                aliases.add(cleaned)
        for alias in aliases:
            alias = alias.strip()
            if not alias:
                continue
            conn.execute(
                "INSERT OR IGNORE INTO aliases(stock_id, alias) VALUES (?, ?)",
                (stock_id, alias),
            )
    conn.commit()
    return inserted


def ensure_ready(db_path: Path | str | None = None) -> sqlite3.Connection:
    conn = connect(db_path)
    init_db(conn)
    seed_stocks(conn)
    return conn


def list_stocks(conn: sqlite3.Connection, enabled_only: bool = True) -> list[dict]:
    sql = """
        SELECT s.id, s.code, s.name, s.enabled,
               GROUP_CONCAT(a.alias, '||') AS aliases
        FROM stocks s
        LEFT JOIN aliases a ON a.stock_id = s.id
    """
    if enabled_only:
        sql += " WHERE s.enabled = 1"
    sql += " GROUP BY s.id ORDER BY s.code"
    rows = conn.execute(sql).fetchall()
    result = []
    for r in rows:
        aliases = [x for x in (r["aliases"] or "").split("||") if x]
        result.append(
            {
                "id": r["id"],
                "code": r["code"],
                "name": r["name"],
                "enabled": bool(r["enabled"]),
                "aliases": aliases,
            }
        )
    return result


def get_stock_by_id(conn: sqlite3.Connection, stock_id: int) -> dict | None:
    for s in list_stocks(conn, enabled_only=False):
        if s["id"] == stock_id:
            return s
    return None


def get_stock_by_code(conn: sqlite3.Connection, code: str) -> dict | None:
    for s in list_stocks(conn, enabled_only=False):
        if s["code"] == code:
            return s
    return None


def insert_heat_snapshot(
    conn: sqlite3.Connection,
    stock_id: int,
    ts: str,
    trends_score: float | None,
    ptt_score: float | None,
    composite_score: float | None,
    trends_error: str | None = None,
    ptt_error: str | None = None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO heat_snapshots(
            stock_id, ts, trends_score, ptt_score, composite_score,
            trends_error, ptt_error
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            stock_id,
            ts,
            trends_score,
            ptt_score,
            composite_score,
            trends_error,
            ptt_error,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def latest_snapshots(conn: sqlite3.Connection) -> dict[int, dict]:
    """回傳 stock_id -> 最新一筆快照。"""
    rows = conn.execute(
        """
        SELECT h.*
        FROM heat_snapshots h
        INNER JOIN (
            SELECT stock_id, MAX(ts) AS max_ts
            FROM heat_snapshots
            GROUP BY stock_id
        ) t ON h.stock_id = t.stock_id AND h.ts = t.max_ts
        """
    ).fetchall()
    return {int(r["stock_id"]): dict(r) for r in rows}


def previous_snapshots(conn: sqlite3.Connection) -> dict[int, dict]:
    """回傳 stock_id -> 倒數第二筆快照（若有）。"""
    latest = latest_snapshots(conn)
    result: dict[int, dict] = {}
    for stock_id, snap in latest.items():
        row = conn.execute(
            """
            SELECT * FROM heat_snapshots
            WHERE stock_id = ? AND ts < ?
            ORDER BY ts DESC
            LIMIT 1
            """,
            (stock_id, snap["ts"]),
        ).fetchone()
        if row:
            result[stock_id] = dict(row)
    return result


def history_for_stock(
    conn: sqlite3.Connection, stock_id: int, days: int = 30
) -> list[dict]:
    rows = conn.execute(
        """
        SELECT * FROM heat_snapshots
        WHERE stock_id = ?
          AND ts >= datetime('now', ?)
        ORDER BY ts ASC
        """,
        (stock_id, f"-{int(days)} days"),
    ).fetchall()
    return [dict(r) for r in rows]


def upsert_ptt_posts(
    conn: sqlite3.Connection, stock_id: int, posts: list[dict], fetched_at: str
) -> int:
    count = 0
    for p in posts:
        cur = conn.execute(
            """
            INSERT INTO ptt_posts(
                stock_id, post_id, board, title, url, push_count,
                posted_at, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(stock_id, post_id) DO UPDATE SET
                title=excluded.title,
                push_count=excluded.push_count,
                posted_at=excluded.posted_at,
                fetched_at=excluded.fetched_at
            """,
            (
                stock_id,
                p["post_id"],
                p.get("board", "Stock"),
                p["title"],
                p["url"],
                int(p.get("push_count") or 0),
                p.get("posted_at"),
                fetched_at,
            ),
        )
        if cur.rowcount:
            count += 1
    conn.commit()
    return count


def recent_ptt_posts(
    conn: sqlite3.Connection, stock_id: int, limit: int = 30
) -> list[dict]:
    rows = conn.execute(
        """
        SELECT * FROM ptt_posts
        WHERE stock_id = ?
        ORDER BY COALESCE(posted_at, fetched_at) DESC
        LIMIT ?
        """,
        (stock_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]
