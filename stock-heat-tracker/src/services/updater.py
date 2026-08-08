"""手動更新編排：Trends + PTT → 寫入快照。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from src.db import insert_heat_snapshot, upsert_ptt_posts
from src.scoring import composite_score, normalize_ptt, normalize_trends
from src.sources.ptt_stock import PTTError, fetch_ptt_heat_for_stock
from src.sources.trends import TrendsError, fetch_trends_score, keywords_for_stock

TW = timezone(timedelta(hours=8))
ProgressCb = Callable[[str], None]


def _now_iso() -> str:
    return datetime.now(TW).isoformat(timespec="seconds")


def update_stock(
    conn,
    stock: dict,
    fetch_trends: bool = True,
    fetch_ptt: bool = True,
    progress: ProgressCb | None = None,
) -> dict[str, Any]:
    """更新單一標的熱度並寫入 DB。"""

    def log(msg: str) -> None:
        if progress:
            progress(msg)

    trends_score = None
    ptt_score = None
    trends_error = None
    ptt_error = None
    ptt_meta: dict[str, Any] = {}
    trends_meta: dict[str, Any] = {}

    label = f"{stock['name']}（{stock['code']}）"

    if fetch_trends:
        log(f"查詢 Google Trends：{label}")
        try:
            # 較長間隔降低 429；批量更新時尤其重要
            trends_meta = fetch_trends_score(
                keywords_for_stock(stock), sleep_sec=2.5
            )
            trends_score = normalize_trends(trends_meta.get("score"))
            if trends_meta.get("errors"):
                log("Trends 部分警告：" + "；".join(trends_meta["errors"]))
        except TrendsError as exc:
            trends_error = str(exc)
            log(f"Trends 失敗：{trends_error}")
        except Exception as exc:  # noqa: BLE001
            trends_error = f"Trends 未預期錯誤：{exc}"
            log(trends_error)

    if fetch_ptt:
        log(f"查詢 PTT Stock：{label}")
        try:
            ptt_meta = fetch_ptt_heat_for_stock(stock)
            ptt_score = normalize_ptt(
                int(ptt_meta.get("article_count") or 0),
                int(ptt_meta.get("total_push") or 0),
            )
            upsert_ptt_posts(
                conn,
                stock["id"],
                ptt_meta.get("posts") or [],
                ptt_meta.get("fetched_at") or _now_iso(),
            )
        except PTTError as exc:
            ptt_error = str(exc)
            log(f"PTT 失敗：{ptt_error}")
        except Exception as exc:  # noqa: BLE001
            ptt_error = f"PTT 未預期錯誤：{exc}"
            log(ptt_error)

    comp = composite_score(trends_score, ptt_score)
    ts = _now_iso()
    snap_id = insert_heat_snapshot(
        conn,
        stock_id=stock["id"],
        ts=ts,
        trends_score=trends_score,
        ptt_score=ptt_score,
        composite_score=comp,
        trends_error=trends_error,
        ptt_error=ptt_error,
    )
    log(f"完成：{label}｜綜合={comp}")
    return {
        "stock_id": stock["id"],
        "snapshot_id": snap_id,
        "ts": ts,
        "trends_score": trends_score,
        "ptt_score": ptt_score,
        "composite_score": comp,
        "trends_error": trends_error,
        "ptt_error": ptt_error,
        "trends_meta": trends_meta,
        "ptt_meta": {
            "article_count": ptt_meta.get("article_count"),
            "total_push": ptt_meta.get("total_push"),
            "mode": ptt_meta.get("mode"),
            "post_count": len(ptt_meta.get("posts") or []),
        },
    }


def update_stocks(
    conn,
    stocks: list[dict],
    fetch_trends: bool = True,
    fetch_ptt: bool = True,
    progress: ProgressCb | None = None,
) -> list[dict[str, Any]]:
    results = []
    total = len(stocks)
    for idx, stock in enumerate(stocks, start=1):
        if progress:
            progress(f"進度 {idx}/{total}")
        results.append(
            update_stock(
                conn,
                stock,
                fetch_trends=fetch_trends,
                fetch_ptt=fetch_ptt,
                progress=progress,
            )
        )
    return results
