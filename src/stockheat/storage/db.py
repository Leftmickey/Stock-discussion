"""SQLite 連線與結構初始化。"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from stockheat.config import DB_PATH, ensure_dirs

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# CREATE TABLE IF NOT EXISTS 不會替既有資料庫補上新欄位，
# 因此新增欄位時同步登記在這裡，讓舊資料庫升級時自動補齊。
ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (("posts", "sentiment", "REAL"),)


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    ensure_dirs()
    path = Path(db_path) if db_path else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    for table, column, coltype in ADDED_COLUMNS:
        existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


def init_db(db_path: Path | str | None = None) -> sqlite3.Connection:
    conn = connect(db_path)
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    _migrate(conn)
    conn.commit()
    return conn


@contextmanager
def session(db_path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    conn = init_db(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
