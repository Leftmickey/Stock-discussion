"""Google Trends 搜尋熱度（選配，預設關閉）。

pytrends 於 2025 年 4 月封存後已無法使用，官方 Trends API 至今仍是限量 alpha。
現行替代品 trendspyg 需要 Chrome、單次查詢十幾到九十秒，且極易觸發 429，
因此不可能涵蓋全市場 2,400 檔，只對自選清單與當日熱度前段班執行。

Trends 回傳的是 0-100 的組內相對值，不同批次之間不可直接比較，
所以每組都固定放一個錨定關鍵字，再用它把各組拉到同一尺度。
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime

from stockheat.collectors.news_rss import best_query_alias, news_targets
from stockheat.config import TAIPEI, TrendsConfig

logger = logging.getLogger(__name__)


class TrendsUnavailable(RuntimeError):
    pass


def _load_backend():
    try:
        from trendspyg import download_google_trends_interest_over_time  # type: ignore
    except ImportError as exc:
        raise TrendsUnavailable(
            '未安裝 Trends 相依套件，請執行 pip install -e ".[trends]"（另需本機有 Chrome）'
        ) from exc
    return download_google_trends_interest_over_time


def _chunks(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def collect_trends(
    conn: sqlite3.Connection,
    config: TrendsConfig | None = None,
    symbols: list[str] | None = None,
) -> dict[str, int]:
    cfg = config or TrendsConfig()
    fetch = _load_backend()

    if symbols is None:
        symbols = news_targets(conn, top_n=cfg.top_n)

    keywords: dict[str, str] = {}
    for symbol in symbols:
        alias = best_query_alias(conn, symbol)
        if alias:
            keywords[symbol] = alias

    today = date.today().isoformat()
    now = datetime.now(TAIPEI).isoformat(timespec="seconds")
    written = 0
    # 每組留一個位置給錨定關鍵字，用來校準跨組的相對尺度。
    group_size = max(1, cfg.group_size - 1)

    for group in _chunks(list(keywords.items()), group_size):
        terms = [cfg.anchor_keyword] + [alias for _, alias in group]
        try:
            frame = fetch(terms, geo=cfg.geo, timeframe=cfg.timeframe)
        except Exception as exc:
            logger.warning("Trends 查詢失敗（%s）：%s", terms, exc)
            continue
        if frame is None or getattr(frame, "empty", True):
            continue

        anchor_mean = float(frame[cfg.anchor_keyword].mean()) or 1.0
        for symbol, alias in group:
            if alias not in frame:
                continue
            # 除以錨定關鍵字的均值，讓不同批次的數字落在同一把尺上。
            normalized = float(frame[alias].iloc[-1]) / anchor_mean * 100.0
            conn.execute(
                """
                INSERT INTO trends_values (date, symbol, value, fetched_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(date, symbol) DO UPDATE SET
                    value = excluded.value, fetched_at = excluded.fetched_at
                """,
                (today, symbol, normalized, now),
            )
            written += 1
        conn.commit()

    logger.info("Trends 寫入 %d 檔", written)
    return {"symbols": len(keywords), "written": written}
