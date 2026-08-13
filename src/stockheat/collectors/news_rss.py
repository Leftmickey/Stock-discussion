"""Google News RSS 新聞熱度。

RSS 免金鑰、格式穩定，是全免費方案裡最可靠的新聞來源。
但它是逐個關鍵字查詢，成本與標的數成正比，因此只對自選清單與
當日熱度前段班執行，不對全市場 2,400 檔跑。
"""

from __future__ import annotations

import logging
import sqlite3
import time
from email.utils import parsedate_to_datetime
from urllib.parse import quote
from xml.etree import ElementTree

from stockheat.config import TAIPEI, NewsConfig
from stockheat.storage import repo
from stockheat.universe.normalize import CONTEXT_CODE, CONTEXT_NONE
from stockheat.utils import get_with_retry, make_client

logger = logging.getLogger(__name__)

RSS_URL = "https://news.google.com/rss/search?q={query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"


def best_query_alias(conn: sqlite3.Connection, symbol: str) -> str | None:
    """挑最短且不含歧義的別名。

    要短是因為媒體用的是通稱而非登記全名：拿「世界先進積體電路」去查只撈得到
    個位數則新聞，「世界先進」則有數十則。但也不能短到用交易所簡稱「世界」，
    那會撈回滿滿的無關新聞，所以通用詞層級的別名一律排除。
    """
    rows = conn.execute(
        "SELECT alias, requires_context FROM aliases WHERE symbol = ? AND alias_type != 'code'",
        (symbol,),
    ).fetchall()
    if not rows:
        return None
    usable = [r["alias"] for r in rows if r["requires_context"] != CONTEXT_CODE]
    if usable:
        return min(usable, key=len)
    unambiguous = [r["alias"] for r in rows if r["requires_context"] == CONTEXT_NONE]
    return min(unambiguous, key=len) if unambiguous else None


def fetch_news_for_symbol(
    conn: sqlite3.Connection, symbol: str, config: NewsConfig | None = None
) -> int:
    cfg = config or NewsConfig()
    keyword = best_query_alias(conn, symbol)
    if not keyword:
        return 0

    url = RSS_URL.format(query=quote(f'"{keyword}"'))
    with make_client(timeout=cfg.timeout) as client:
        resp = get_with_retry(client, url, max_retries=2)
    if resp is None:
        return 0

    try:
        root = ElementTree.fromstring(resp.text)
    except ElementTree.ParseError:
        logger.warning("%s 的 RSS 解析失敗", symbol)
        return 0

    rows = []
    for item in list(root.iterfind("./channel/item"))[: cfg.max_items_per_symbol]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        # Google News 的查詢是模糊比對，標題不含關鍵字的一律丟掉。
        if keyword not in title:
            continue

        published = None
        raw_date = item.findtext("pubDate")
        if raw_date:
            try:
                published = parsedate_to_datetime(raw_date).astimezone(TAIPEI)
            except (TypeError, ValueError):
                published = None

        source_node = item.find("source")
        rows.append(
            {
                "symbol": symbol,
                "title": title,
                "url": link,
                "publisher": source_node.text if source_node is not None else None,
                "published_at": published.isoformat() if published else None,
            }
        )

    if rows:
        repo.upsert_news(conn, rows)
        conn.commit()
    return len(rows)


def collect_news(
    conn: sqlite3.Connection, symbols: list[str], config: NewsConfig | None = None
) -> dict[str, int]:
    cfg = config or NewsConfig()
    total = 0
    for i, symbol in enumerate(symbols):
        total += fetch_news_for_symbol(conn, symbol, cfg)
        if i < len(symbols) - 1:
            time.sleep(cfg.request_interval)
    logger.info("新聞採集完成：%d 檔、%d 則", len(symbols), total)
    return {"symbols": len(symbols), "items": total}


def news_targets(conn: sqlite3.Connection, top_n: int = 20) -> list[str]:
    """自選清單，加上最近一日熱度前段班。"""
    watch = [r["symbol"] for r in repo.get_watchlist(conn)]
    latest = repo.latest_score_date(conn)
    top: list[str] = []
    if latest:
        top = [
            r["symbol"]
            for r in conn.execute(
                "SELECT symbol FROM heat_scores WHERE date = ? ORDER BY raw_heat DESC LIMIT ?",
                (latest, top_n),
            )
        ]
    seen: list[str] = []
    for s in watch + top:
        if s not in seen:
            seen.append(s)
    return seen
