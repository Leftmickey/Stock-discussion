"""掃榜與詳情查詢。"""

from __future__ import annotations

from src.db import (
    history_for_stock,
    latest_snapshots,
    list_stocks,
    previous_snapshots,
    recent_ptt_posts,
)
from src.scoring import score_delta
from src.search import search_stocks


def build_board_rows(conn, query: str = "") -> list[dict]:
    stocks = list_stocks(conn, enabled_only=True)
    if query.strip():
        stocks = search_stocks(stocks, query)

    latest = latest_snapshots(conn)
    prev = previous_snapshots(conn)
    rows = []
    for s in stocks:
        snap = latest.get(s["id"])
        prev_snap = prev.get(s["id"])
        composite = snap["composite_score"] if snap else None
        prev_composite = prev_snap["composite_score"] if prev_snap else None
        rows.append(
            {
                "id": s["id"],
                "name": s["name"],
                "code": s["code"],
                "aliases": s["aliases"],
                "trends": snap["trends_score"] if snap else None,
                "ptt": snap["ptt_score"] if snap else None,
                "composite": composite,
                "delta": score_delta(composite, prev_composite),
                "updated_at": snap["ts"] if snap else None,
                "trends_error": snap.get("trends_error") if snap else None,
                "ptt_error": snap.get("ptt_error") if snap else None,
            }
        )
    return rows


def sort_board_rows(rows: list[dict], sort_by: str = "綜合熱度") -> list[dict]:
    key_map = {
        "綜合熱度": "composite",
        "Trends": "trends",
        "PTT": "ptt",
        "變化": "delta",
        "代號": "code",
    }
    key = key_map.get(sort_by, "composite")
    if key == "code":
        return sorted(rows, key=lambda r: r["code"])

    def sort_key(r: dict):
        val = r.get(key)
        # None 排最後
        return (val is None, -(val or 0))

    return sorted(rows, key=sort_key)


def get_stock_detail(conn, stock_id: int, history_days: int = 30) -> dict | None:
    stocks = {s["id"]: s for s in list_stocks(conn, enabled_only=False)}
    stock = stocks.get(stock_id)
    if not stock:
        return None
    latest = latest_snapshots(conn).get(stock_id)
    history = history_for_stock(conn, stock_id, days=history_days)
    posts = recent_ptt_posts(conn, stock_id, limit=40)
    return {
        "stock": stock,
        "latest": latest,
        "history": history,
        "posts": posts,
    }
