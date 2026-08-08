"""Google News 媒體曝光度。

透過 Google News RSS 搜尋(zh-TW / TW),以 pubDate 落在視窗內的則數計算。
單次 RSS 最多回 100 則,超過即飽和(以 saturated 標記,對超熱門股的
30 天新聞數會低估)。
"""
from __future__ import annotations

import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from common import get_text

RSS_URL = (
    "https://news.google.com/rss/search?q={query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
)
RSS_MAX_ITEMS = 100
REQUEST_DELAY = 0.5


def _fetch_rss_items(query: str) -> list[dict]:
    url = RSS_URL.format(query=urllib.parse.quote(query))
    xml_text = get_text(url)
    root = ET.fromstring(xml_text)
    items = []
    for item in root.iter("item"):
        title = item.findtext("title") or ""
        link = item.findtext("link") or ""
        pub = item.findtext("pubDate")
        if not pub:
            continue
        try:
            dt = parsedate_to_datetime(pub)
        except (TypeError, ValueError):
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        items.append({"title": title, "link": link, "ts": dt.timestamp()})
    return items


def fetch_news(stocks: list[dict], max_days: int) -> dict[str, dict]:
    """回傳 {code: {"items": [...], "saturated": bool}}。

    saturated=True 表示 RSS 回滿 100 則,視窗內的實際新聞數可能更多。
    """
    now = datetime.now(timezone.utc)
    since_ts = (now - timedelta(days=max_days)).timestamp()
    result: dict[str, dict] = {}

    for stock in stocks:
        query = stock["news_query"]
        try:
            items = _fetch_rss_items(query)
        except Exception as e:
            print(f"  [News] {stock['name']} 搜尋失敗:{e}")
            result[stock["code"]] = {"items": [], "saturated": False, "failed": True}
            continue
        saturated = len(items) >= RSS_MAX_ITEMS
        in_window = sorted(
            (i for i in items if i["ts"] >= since_ts), key=lambda i: -i["ts"]
        )
        result[stock["code"]] = {"items": in_window, "saturated": saturated}
        print(
            f"  [News] {stock['name']}({stock['code']}):{max_days} 天內 "
            f"{len(in_window)} 則{'(飽和,實際更多)' if saturated else ''}"
        )
        time.sleep(REQUEST_DELAY)
    return result
