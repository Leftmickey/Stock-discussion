"""共用工具:HTTP 請求(含重試)、設定檔載入、時間視窗。"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# 統計視窗(天)
WINDOWS = [1, 7, 30]


def http_request(
    url: str,
    data: bytes | None = None,
    headers: dict | None = None,
    timeout: int = 25,
    retries: int = 3,
    backoff: float = 2.0,
) -> bytes:
    """送出 HTTP 請求,失敗時指數退避重試。"""
    merged = {"User-Agent": USER_AGENT}
    if headers:
        merged.update(headers)
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=merged)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(backoff * (2**attempt))
    raise RuntimeError(f"HTTP 請求失敗 ({url}): {last_err}")


def post_json(url: str, body: dict, timeout: int = 25, retries: int = 3) -> dict:
    raw = http_request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        timeout=timeout,
        retries=retries,
    )
    return json.loads(raw)


def get_json(url: str, timeout: int = 25, retries: int = 3) -> dict:
    return json.loads(http_request(url, timeout=timeout, retries=retries))


def get_text(url: str, timeout: int = 25, retries: int = 3) -> str:
    return http_request(url, timeout=timeout, retries=retries).decode("utf-8", "replace")


def load_stocks() -> list[dict]:
    """讀取股票清單設定檔,補齊預設欄位。"""
    cfg = json.loads((ROOT / "config" / "stocks.json").read_text(encoding="utf-8"))
    stocks = []
    for s in cfg["stocks"]:
        stock = {
            "name": s["name"],
            "code": s["code"],
            "market": s.get("market", "twse"),
            "ptt_queries": s.get("ptt_queries") or [s["name"], s["code"]],
            "news_query": s.get("news_query") or s["name"],
        }
        stocks.append(stock)
    return stocks
