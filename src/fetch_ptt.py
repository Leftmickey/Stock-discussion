"""PTT Stock 板討論熱度。

資料來源:pttweb.cc 的 Twirp JSON API(GetPttBoard,標題搜尋 + 游標翻頁)。
PTT 官方站(ptt.cc)會封鎖雲端機房 IP,因此改走鏡像站的公開 API。

每檔股票以多組關鍵字(預設:名稱、代號)做標題搜尋,依 article_id 去重,
統計視窗內的文章數與留言數(推+噓+箭頭)。
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from common import post_json

API_URL = "https://www.pttweb.cc/twirp/e7pttV1.E7Service/GetPttBoard"
BOARD = "Stock"
DISPLAY_MODE_SEARCH_TITLE = 4
PAGE_LIMIT = 26  # 伺服器單頁上限
MAX_PAGES = 40  # 單一關鍵字翻頁安全上限
REQUEST_DELAY = 0.4

TAIPEI_TZ = timezone(timedelta(hours=8))


def _search_titles(query: str, since_ts: float) -> list[dict]:
    """標題搜尋,往舊翻頁直到 since_ts(Unix 秒)之前,回傳文章列表。"""
    articles: list[dict] = []
    cursor_aid_time = None
    cursor_article_id = None

    for _ in range(MAX_PAGES):
        body = {
            "pttBoardName": BOARD,
            "displayMode": DISPLAY_MODE_SEARCH_TITLE,
            "searchDoSearch": True,
            "searchParamString": query,
            "resultCountLimit": PAGE_LIMIT,
        }
        if cursor_aid_time:
            body["searchPaginationArticleAidTime"] = cursor_aid_time
            body["searchPaginationArticleId"] = cursor_article_id

        reply = post_json(API_URL, body)
        page = (reply.get("ptt_board") or {}).get("articles") or []
        if not page:
            break

        reached_cutoff = False
        for a in page:
            ts = int(a["aid_time"]) / 1e9
            if ts < since_ts:
                reached_cutoff = True
                continue
            articles.append(
                {
                    "article_id": a["article_id"],
                    "aid": a.get("article_aid", ""),
                    "title": a.get("title", ""),
                    "ts": ts,
                    "comments": int(a.get("recommend_total_count") or 0),
                    "up": int(a.get("recommend_up_count") or 0),
                    "down": int(a.get("recommend_down_count") or 0),
                }
            )

        if reached_cutoff or len(page) < PAGE_LIMIT:
            break
        last = page[-1]
        cursor_aid_time = last["aid_time"]
        cursor_article_id = last["article_id"]
        time.sleep(REQUEST_DELAY)

    return articles


def fetch_ptt(stocks: list[dict], max_days: int) -> dict[str, dict]:
    """回傳 {code: {"articles": [...]}},文章依 article_id 去重、時間新到舊。"""
    now = datetime.now(TAIPEI_TZ)
    since_ts = (now - timedelta(days=max_days)).timestamp()
    result: dict[str, dict] = {}

    for stock in stocks:
        merged: dict[str, dict] = {}
        for query in stock["ptt_queries"]:
            try:
                for art in _search_titles(query, since_ts):
                    merged[art["article_id"]] = art
            except Exception as e:
                print(f"  [PTT] {stock['name']} 關鍵字「{query}」搜尋失敗:{e}")
            time.sleep(REQUEST_DELAY)
        articles = sorted(merged.values(), key=lambda a: -a["ts"])
        result[stock["code"]] = {"articles": articles}
        print(
            f"  [PTT] {stock['name']}({stock['code']}):{max_days} 天內 "
            f"{len(articles)} 篇、{sum(a['comments'] for a in articles)} 則留言"
        )
    return result
