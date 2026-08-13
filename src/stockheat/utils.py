"""共用小工具：HTTP 取得、民國日期轉換、數值解析。"""

from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 stockheat/0.1"
)


def make_client(timeout: float = 20.0, **kwargs: Any) -> httpx.Client:
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "zh-TW,zh;q=0.9"}
    headers.update(kwargs.pop("headers", {}))
    return httpx.Client(timeout=timeout, headers=headers, follow_redirects=True, **kwargs)


def get_with_retry(
    client: httpx.Client,
    url: str,
    *,
    max_retries: int = 3,
    backoff: float = 2.0,
    **kwargs: Any,
) -> httpx.Response | None:
    """指數退避重試。全部失敗回傳 None，讓呼叫端決定要不要中止整批作業。"""
    delay = backoff
    for attempt in range(1, max_retries + 1):
        try:
            resp = client.get(url, **kwargs)
            if resp.status_code == 200:
                return resp
            # 429 與 5xx 值得重試，其餘 4xx 代表請求本身有問題。
            if resp.status_code < 500 and resp.status_code != 429:
                logger.warning("GET %s 回應 %s，不重試", url, resp.status_code)
                return None
            logger.warning("GET %s 回應 %s（第 %d 次）", url, resp.status_code, attempt)
        except httpx.HTTPError as exc:
            logger.warning("GET %s 失敗：%s（第 %d 次）", url, exc, attempt)
        if attempt < max_retries:
            time.sleep(delay)
            delay *= 2
    return None


ROC_DATE_RE = re.compile(r"^(\d{2,3})(\d{2})(\d{2})$")


def roc_to_date(value: str | None) -> date | None:
    """民國日期字串轉西元：1150807 → 2026-08-07。也接受已是西元的 YYYYMMDD。"""
    if not value:
        return None
    value = value.strip().replace("/", "").replace("-", "")
    m = ROC_DATE_RE.match(value)
    if not m:
        if re.fullmatch(r"\d{8}", value):
            try:
                return datetime.strptime(value, "%Y%m%d").date()
            except ValueError:
                return None
        return None
    year, month, day = int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3))
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_number(value: Any) -> float | None:
    """交易所回傳全是字串，且含千分位、正負號、全形空白與 '--' 佔位符。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("　", "").replace("+", "")
    if text in {"", "-", "--", "---", "X", "x", "N/A"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_int(value: Any) -> int | None:
    num = parse_number(value)
    return int(num) if num is not None else None
