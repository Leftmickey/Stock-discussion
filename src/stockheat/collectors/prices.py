"""個股歷史行情回補。

每日批次會把全市場當日快照存下來，時間一長就自然累積出歷史；
但剛建庫時個股頁沒有線圖可看，所以另外提供逐檔回補。

兩個交易所的歷史端點格式不同，最容易踩的坑是成交量單位：
證交所的 STOCK_DAY 給「股」，櫃買的 tradingStock 給「仟股」。
"""

from __future__ import annotations

import logging
import sqlite3
import time
from datetime import date, timedelta

import httpx

from stockheat.storage import repo
from stockheat.utils import get_with_retry, make_client, parse_int, parse_number, roc_to_date

logger = logging.getLogger(__name__)

TWSE_STOCK_DAY = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
TPEX_STOCK_DAY = "https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock"

# 證交所對此端點有速率限制（約每 5 秒 3 次），寧可慢也不要被暫時封鎖。
REQUEST_INTERVAL = 2.0


def _month_starts(start: date, end: date) -> list[date]:
    months = []
    cursor = start.replace(day=1)
    while cursor <= end:
        months.append(cursor)
        cursor = (cursor + timedelta(days=32)).replace(day=1)
    return months


def _fetch_twse_month(client: httpx.Client, symbol: str, month: date) -> list[dict]:
    resp = get_with_retry(
        client,
        TWSE_STOCK_DAY,
        params={"response": "json", "date": month.strftime("%Y%m%d"), "stockNo": symbol},
        max_retries=3,
    )
    if resp is None:
        return []
    try:
        payload = resp.json()
    except ValueError:
        return []
    if payload.get("stat") != "OK":
        return []

    out = []
    for row in payload.get("data", []):
        trade_date = roc_to_date(str(row[0]).replace("/", ""))
        if not trade_date:
            continue
        out.append(
            {
                "date": trade_date.isoformat(),
                "symbol": symbol,
                "volume": parse_int(row[1]),
                "open": parse_number(row[3]),
                "high": parse_number(row[4]),
                "low": parse_number(row[5]),
                "close": parse_number(row[6]),
                "change": parse_number(row[7]),
            }
        )
    return out


def _fetch_tpex_month(client: httpx.Client, symbol: str, month: date) -> list[dict]:
    resp = get_with_retry(
        client,
        TPEX_STOCK_DAY,
        params={
            "code": symbol,
            "date": month.strftime("%Y/%m/%d"),
            "id": "",
            "response": "json",
        },
        max_retries=3,
    )
    if resp is None:
        return []
    try:
        payload = resp.json()
    except ValueError:
        return []

    tables = payload.get("tables") or []
    if not tables:
        return []

    out = []
    for row in tables[0].get("data", []):
        trade_date = roc_to_date(str(row[0]).replace("/", ""))
        if not trade_date:
            continue
        shares = parse_number(row[1])
        out.append(
            {
                "date": trade_date.isoformat(),
                "symbol": symbol,
                # 櫃買此端點的成交量以仟股計，換算成股才能與證交所對齊。
                "volume": int(shares * 1000) if shares is not None else None,
                "open": parse_number(row[3]),
                "high": parse_number(row[4]),
                "low": parse_number(row[5]),
                "close": parse_number(row[6]),
                "change": parse_number(row[7]),
            }
        )
    return out


def backfill_prices(
    conn: sqlite3.Connection,
    symbols: list[str],
    days: int = 90,
    interval: float = REQUEST_INTERVAL,
) -> dict[str, int]:
    end = date.today()
    months = _month_starts(end - timedelta(days=days), end)

    placeholders = ",".join("?" * len(symbols))
    markets = {
        r["symbol"]: r["market"]
        for r in conn.execute(
            f"SELECT symbol, market FROM stocks WHERE symbol IN ({placeholders})", symbols
        )
    }

    total = 0
    with make_client(timeout=25.0) as client:
        for symbol in symbols:
            market = markets.get(symbol)
            if market is None:
                logger.warning("%s 不在標的主檔內，略過", symbol)
                continue
            fetch = _fetch_twse_month if market == "TWSE" else _fetch_tpex_month
            for month in months:
                rows = fetch(client, symbol, month)
                if rows:
                    total += repo.upsert_prices(conn, rows)
                time.sleep(interval)
            conn.commit()
    logger.info("回補 %d 檔、%d 筆行情", len(symbols), total)
    return {"symbols": len(symbols), "rows": total}
