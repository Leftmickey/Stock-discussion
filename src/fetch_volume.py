"""成交量(真金白銀的熱度)。

上市:證交所 STOCK_DAY 月資料(單位:股、元)
上櫃:櫃買中心 tradingStock 月資料(單位:張、仟元)

抓取近幾個月的每日成交金額,供後續計算各視窗的日均成交金額與
相對前一期的變化率。
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone

from common import get_json

TWSE_URL = "https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date={d}&stockNo={code}"
TPEX_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock?code={code}&date={d}&response=json"
REQUEST_DELAY = 0.6

TAIPEI_TZ = timezone(timedelta(hours=8))


def _roc_date_to_iso(roc: str) -> str | None:
    """民國日期 '115/08/03' -> '2026-08-03'。"""
    try:
        y, m, d = roc.strip().split("/")
        return f"{int(y) + 1911:04d}-{int(m):02d}-{int(d):02d}"
    except (ValueError, AttributeError):
        return None


def _num(s: str) -> float:
    s = (s or "").replace(",", "").strip()
    if s in ("", "--", "X", "―"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _month_starts(months: int) -> list[date]:
    """回傳最近 months 個月的月初日期(含當月),由舊到新。"""
    today = datetime.now(TAIPEI_TZ).date()
    starts = []
    y, m = today.year, today.month
    for _ in range(months):
        starts.append(date(y, m, 1))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(starts))


def _fetch_twse_month(code: str, month_start: date) -> list[dict]:
    url = TWSE_URL.format(d=month_start.strftime("%Y%m%d"), code=code)
    d = get_json(url)
    if d.get("stat") != "OK":
        return []
    rows = []
    for row in d.get("data") or []:
        iso = _roc_date_to_iso(row[0])
        if iso:
            rows.append({"date": iso, "shares": _num(row[1]), "value": _num(row[2])})
    return rows


def _fetch_tpex_month(code: str, month_start: date) -> list[dict]:
    url = TPEX_URL.format(d=month_start.strftime("%Y/%m/%d"), code=code)
    d = get_json(url)
    tables = d.get("tables") or []
    if not tables:
        return []
    rows = []
    for row in tables[0].get("data") or []:
        iso = _roc_date_to_iso(row[0])
        if iso:
            rows.append(
                {
                    "date": iso,
                    "shares": _num(row[1]) * 1000,  # 張 -> 股
                    "value": _num(row[2]) * 1000,  # 仟元 -> 元
                }
            )
    return rows


def fetch_volume(stocks: list[dict], max_days: int) -> dict[str, dict]:
    """回傳 {code: {"daily": [{date, shares, value}, ...]}}(由舊到新)。

    抓取涵蓋 max_days*2 天(供計算前一期比較基準)所需的月份數。
    """
    months_needed = (max_days * 2) // 28 + 2
    month_starts = _month_starts(months_needed)
    result: dict[str, dict] = {}

    for stock in stocks:
        code, market = stock["code"], stock["market"]
        daily: list[dict] = []
        failed = False
        for ms in month_starts:
            try:
                if market == "tpex":
                    rows = _fetch_tpex_month(code, ms)
                    if not rows:  # 市場別設錯時自動改試證交所
                        rows = _fetch_twse_month(code, ms)
                else:
                    rows = _fetch_twse_month(code, ms)
                    if not rows:
                        rows = _fetch_tpex_month(code, ms)
                daily.extend(rows)
            except Exception as e:
                print(f"  [Volume] {stock['name']} {ms:%Y-%m} 抓取失敗:{e}")
                failed = True
            time.sleep(REQUEST_DELAY)
        daily.sort(key=lambda r: r["date"])
        result[code] = {"daily": daily, "failed": failed and not daily}
        print(f"  [Volume] {stock['name']}({code}):{len(daily)} 個交易日資料")
    return result
