"""向證交所與櫃買中心取得全市場標的與當日行情。

兩家的 OpenAPI 都免金鑰、免參數，但共通限制是只給「最新交易日」快照，
無法指定歷史日期。因此每日批次順手把當日快照存下來，時間一長自然累積出歷史。
個股的歷史回補另走舊版端點（見 collectors/prices.py）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

from stockheat.universe.normalize import classify_security
from stockheat.utils import get_with_retry, make_client, parse_int, parse_number, roc_to_date

logger = logging.getLogger(__name__)

TWSE_QUOTES = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TWSE_COMPANIES = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_QUOTES = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
TPEX_COMPANIES = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"


@dataclass
class SecurityRow:
    symbol: str
    name: str
    market: str
    security_type: str
    full_name: str | None = None


@dataclass
class QuoteRow:
    symbol: str
    date: date
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    change: float | None
    volume: int | None


def _fetch_json(url: str, timeout: float = 40.0) -> list[dict[str, Any]]:
    with make_client(timeout=timeout) as client:
        resp = get_with_retry(client, url, max_retries=3)
    if resp is None:
        logger.error("無法取得 %s", url)
        return []
    try:
        data = resp.json()
    except ValueError:
        logger.error("%s 回傳非 JSON", url)
        return []
    return data if isinstance(data, list) else []


def _collect(
    rows: list[dict[str, Any]],
    companies: dict[str, str],
    market: str,
    code_key: str,
    name_key: str,
    price_keys: dict[str, str],
) -> tuple[list[SecurityRow], list[QuoteRow], int]:
    securities: list[SecurityRow] = []
    quotes: list[QuoteRow] = []
    skipped = 0
    for row in rows:
        code = str(row.get(code_key, "")).strip()
        name = str(row.get(name_key, "")).strip()
        if not code or not name:
            continue
        sec_type = classify_security(code)
        # 櫃買日行情一萬多筆裡約九成是權證，先擋掉才不會污染比對字典與搜尋。
        if sec_type in {"warrant", "other"}:
            skipped += 1
            continue
        securities.append(SecurityRow(code, name, market, sec_type, companies.get(code) or None))
        trade_date = roc_to_date(str(row.get("Date", "")))
        if trade_date:
            quotes.append(
                QuoteRow(
                    symbol=code,
                    date=trade_date,
                    open=parse_number(row.get(price_keys["open"])),
                    high=parse_number(row.get(price_keys["high"])),
                    low=parse_number(row.get(price_keys["low"])),
                    close=parse_number(row.get(price_keys["close"])),
                    change=parse_number(row.get(price_keys["change"])),
                    volume=parse_int(row.get(price_keys["volume"])),
                )
            )
    return securities, quotes, skipped


def fetch_twse() -> tuple[list[SecurityRow], list[QuoteRow]]:
    companies = {
        str(r.get("公司代號", "")).strip(): str(r.get("公司名稱", "")).strip()
        for r in _fetch_json(TWSE_COMPANIES)
    }
    securities, quotes, skipped = _collect(
        _fetch_json(TWSE_QUOTES),
        companies,
        "TWSE",
        "Code",
        "Name",
        {
            "open": "OpeningPrice",
            "high": "HighestPrice",
            "low": "LowestPrice",
            "close": "ClosingPrice",
            "change": "Change",
            "volume": "TradeVolume",
        },
    )
    logger.info("TWSE 取得 %d 檔標的、%d 筆行情（略過 %d 筆）", len(securities), len(quotes), skipped)
    return securities, quotes


def fetch_tpex() -> tuple[list[SecurityRow], list[QuoteRow]]:
    companies = {
        str(r.get("SecuritiesCompanyCode", "")).strip(): str(r.get("CompanyName", "")).strip()
        for r in _fetch_json(TPEX_COMPANIES)
    }
    securities, quotes, skipped = _collect(
        _fetch_json(TPEX_QUOTES),
        companies,
        "TPEX",
        "SecuritiesCompanyCode",
        "CompanyName",
        {
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "change": "Change",
            "volume": "TradingShares",
        },
    )
    logger.info(
        "TPEx 取得 %d 檔標的、%d 筆行情（濾除權證等 %d 筆）", len(securities), len(quotes), skipped
    )
    return securities, quotes


def fetch_all() -> tuple[list[SecurityRow], list[QuoteRow]]:
    tw_sec, tw_q = fetch_twse()
    tp_sec, tp_q = fetch_tpex()
    return tw_sec + tp_sec, tw_q + tp_q
