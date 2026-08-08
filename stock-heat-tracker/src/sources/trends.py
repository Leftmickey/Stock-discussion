"""Google Trends 適配器（pytrends）。"""

from __future__ import annotations

import time
from typing import Any

import pandas as pd

try:
    from pytrends.request import TrendReq
except Exception:  # pragma: no cover
    TrendReq = None  # type: ignore


class TrendsError(Exception):
    pass


def _build_client() -> Any:
    if TrendReq is None:
        raise TrendsError("未安裝 pytrends，無法查詢 Google Trends")
    # retries 交由外層控制，避免與新版 urllib3 不相容參數衝突
    return TrendReq(hl="zh-TW", tz=480)


def _interest_score(df: pd.DataFrame, col: str) -> float:
    series = df[col].dropna()
    if series.empty:
        return 0.0
    latest = float(series.iloc[-1])
    mean = float(series.tail(min(7, len(series))).mean())
    return round(max(latest, mean), 2)


def fetch_single_keyword(
    keyword: str,
    timeframe: str = "now 7-d",
    geo: str = "TW",
    sleep_sec: float = 2.0,
) -> float:
    client = _build_client()
    try:
        client.build_payload([keyword], timeframe=timeframe, geo=geo)
        df = client.interest_over_time()
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "429" in msg:
            raise TrendsError("Google Trends 被限流（429），請稍後再試或拉長間隔") from exc
        raise TrendsError(f"Google Trends 查詢失敗：{exc}") from exc
    finally:
        if sleep_sec > 0:
            time.sleep(sleep_sec)

    if df is None or df.empty or keyword not in df.columns:
        return 0.0
    return _interest_score(df, keyword)


def fetch_trends_score(
    keywords: list[str],
    timeframe: str = "now 7-d",
    geo: str = "TW",
    sleep_sec: float = 2.0,
) -> dict[str, Any]:
    """
    查詢關鍵字相對熱度。
    為降低 429，改為逐一查詢；分數取各關鍵字最大值。
    """
    cleaned: list[str] = []
    for k in keywords:
        k = (k or "").strip()
        if k and k not in cleaned:
            cleaned.append(k)
    if not cleaned:
        raise TrendsError("沒有可用的 Trends 關鍵字")

    # 預設只查前兩個（名稱、代號）
    query = cleaned[:2]
    per_keyword: dict[str, float] = {}
    errors: list[str] = []

    for kw in query:
        try:
            per_keyword[kw] = fetch_single_keyword(
                kw, timeframe=timeframe, geo=geo, sleep_sec=sleep_sec
            )
        except TrendsError as exc:
            errors.append(f"{kw}: {exc}")
            # 限流時停止後續關鍵字，保留已查到的
            if "429" in str(exc) or "限流" in str(exc):
                break

    if not per_keyword and errors:
        raise TrendsError("；".join(errors))

    score = max(per_keyword.values()) if per_keyword else 0.0
    return {
        "score": float(score),
        "keywords": query,
        "per_keyword": per_keyword,
        "timeframe": timeframe,
        "errors": errors,
    }


def keywords_for_stock(stock: dict) -> list[str]:
    """Trends 查詢用關鍵字：正式名優先，其次代號。"""
    return [stock["name"], stock["code"]]
