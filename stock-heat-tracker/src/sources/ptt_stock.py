"""PTT Stock 板討論熱度適配器。

優先使用 pttweb.cc（官方 www.ptt.cc 在部分網路環境會 500），
仍會嘗試官方站，失敗則自動降級。
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

PTT_BASE = "https://www.ptt.cc"
PTTWEB_BASE = "https://www.pttweb.cc"
STOCK_INDEX = f"{PTT_BASE}/bbs/Stock/index.html"
PTTWEB_STOCK = f"{PTTWEB_BASE}/bbs/Stock"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
TW = timezone(timedelta(hours=8))


class PTTError(Exception):
    pass


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
        }
    )
    s.cookies.set("over18", "1", domain="www.ptt.cc")
    return s


def _parse_push_count(text: str) -> int:
    text = (text or "").strip()
    if not text:
        return 0
    if text == "爆":
        return 100
    if text.startswith("X"):
        return 0
    try:
        return max(0, int(text))
    except ValueError:
        return 0


def _extract_post_id(href: str) -> str:
    m = re.search(r"/(M\.[^/]+)\.html?", href or "")
    if m:
        return m.group(1)
    m = re.search(r"/(M\.[A-Za-z0-9.]+)", href or "")
    return m.group(1) if m else (href or "").rstrip("/").split("/")[-1]


def _title_matches(title: str, keywords: list[str]) -> bool:
    t = title or ""
    for kw in keywords:
        kw = (kw or "").strip()
        if not kw:
            continue
        if kw.isdigit():
            if len(kw) >= 4 and kw in t:
                return True
        elif kw in t:
            return True
    return False


def keywords_for_stock(stock: dict) -> list[str]:
    keys = [stock["name"], stock["code"]]
    for a in stock.get("aliases") or []:
        a = (a or "").strip()
        if a and a not in keys:
            keys.append(a)
    return [k for k in keys if len(k) >= 2]


def _clean_title(title: str) -> str:
    title = (title or "").strip()
    # pttweb 常把標題重複兩次
    half = len(title) // 2
    if half >= 4 and title[:half].strip() == title[half:].strip():
        return title[:half].strip()
    return title


def _parse_pttweb_containers(soup: BeautifulSoup) -> list[dict[str, Any]]:
    posts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for box in soup.select("div.e7-container"):
        a = box.select_one('a.e7-article-default[href*="/bbs/Stock/M."]')
        if not a:
            continue
        href = a.get("href") or ""
        post_id = _extract_post_id(href)
        if not post_id or post_id in seen:
            continue
        # 只要「直接子樹」內只有這個文章連結，避免抓到外層大容器
        nested_links = box.select('a.e7-article-default[href*="/bbs/Stock/M."]')
        if len(nested_links) != 1:
            continue
        seen.add(post_id)
        title_el = a.select_one(".e7-show-if-device-is-not-xs span") or a.select_one(
            ".e7-title"
        )
        title = _clean_title(
            title_el.get_text(strip=True) if title_el else a.get_text(" ", strip=True)
        )
        score_el = box.select_one(".e7-recommendScore")
        push = _parse_push_count(score_el.get_text(" ", strip=True) if score_el else "")
        date_txt = ""
        for el in box.select("div, span"):
            txt = el.get_text(" ", strip=True)
            if re.search(r"\d{2}/\d{2}|小時前|分鐘前|天前", txt or ""):
                # 取較短的時間字串
                if not date_txt or len(txt) < len(date_txt):
                    date_txt = txt
        posts.append(
            {
                "post_id": post_id,
                "board": "Stock",
                "title": title,
                "url": urljoin(PTTWEB_BASE, href),
                "push_count": push,
                "posted_at": date_txt or None,
                "matched_by": "pttweb",
            }
        )
    return posts


def fetch_pttweb_search(
    keyword: str,
    session: requests.Session | None = None,
    sleep_sec: float = 0.35,
) -> list[dict[str, Any]]:
    sess = session or _session()
    url = f"{PTTWEB_BASE}/bbs/Stock/search/t/{quote(keyword)}"
    try:
        resp = sess.get(url, timeout=25)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise PTTError(f"pttweb 搜尋失敗：{exc}") from exc
    soup = BeautifulSoup(resp.text, "lxml")
    posts = _parse_pttweb_containers(soup)
    if sleep_sec > 0:
        time.sleep(sleep_sec)
    return posts


def fetch_pttweb_recent(
    session: requests.Session | None = None,
    pages: int = 1,
    sleep_sec: float = 0.35,
) -> list[dict[str, Any]]:
    sess = session or _session()
    urls = [PTTWEB_STOCK]
    # 熱門頁可補充討論熱度
    urls.append(f"{PTTWEB_BASE}/bbs/Stock/hot/24h")
    posts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for url in urls[: max(1, pages + 1)]:
        try:
            resp = sess.get(url, timeout=25)
            resp.raise_for_status()
        except requests.RequestException:
            continue
        for p in _parse_pttweb_containers(BeautifulSoup(resp.text, "lxml")):
            if p["post_id"] in seen:
                continue
            seen.add(p["post_id"])
            posts.append(p)
        if sleep_sec > 0:
            time.sleep(sleep_sec)
    return posts


def fetch_official_search_posts(
    keyword: str,
    session: requests.Session | None = None,
    max_pages: int = 2,
    sleep_sec: float = 0.4,
) -> list[dict[str, Any]]:
    sess = session or _session()
    posts: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        url = f"{PTT_BASE}/bbs/Stock/search?page={page}&q={quote(keyword)}"
        try:
            resp = sess.get(url, timeout=20)
        except requests.RequestException as exc:
            raise PTTError(f"PTT 搜尋失敗：{exc}") from exc
        if resp.status_code != 200:
            raise PTTError(f"PTT 搜尋 HTTP {resp.status_code}")
        soup = BeautifulSoup(resp.text, "lxml")
        entries = soup.select("div.r-ent")
        if not entries:
            break
        for ent in entries:
            title_el = ent.select_one("div.title a")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            href = title_el.get("href") or ""
            push_el = ent.select_one("div.nrec")
            date_el = ent.select_one("div.date")
            posts.append(
                {
                    "post_id": _extract_post_id(href),
                    "board": "Stock",
                    "title": title,
                    "url": urljoin(PTT_BASE, href),
                    "push_count": _parse_push_count(
                        push_el.get_text(strip=True) if push_el else ""
                    ),
                    "posted_at": date_el.get_text(strip=True) if date_el else None,
                    "matched_by": keyword,
                }
            )
        if sleep_sec > 0:
            time.sleep(sleep_sec)
    return posts


def fetch_ptt_heat_for_stock(
    stock: dict,
    max_search_pages: int = 2,
    index_pages: int = 2,
    sleep_sec: float = 0.35,
) -> dict[str, Any]:
    """
    取得單一標的的 PTT Stock 討論熱度。
    順序：官方搜尋 → pttweb 搜尋 → pttweb 最新/熱門頁過濾。
    """
    sess = _session()
    kws = keywords_for_stock(stock)
    posts: list[dict[str, Any]] = []
    errors: list[str] = []
    mode = "pttweb_search"

    search_terms: list[str] = []
    for term in [stock["name"], stock["code"]]:
        if term not in search_terms:
            search_terms.append(term)

    # 1) 官方站（若可用）
    official_ok = False
    for term in search_terms:
        try:
            found = fetch_official_search_posts(
                term,
                session=sess,
                max_pages=max_search_pages,
                sleep_sec=sleep_sec,
            )
            posts.extend(found)
            official_ok = True
            mode = "official_search"
        except PTTError as exc:
            errors.append(str(exc))
            break

    # 2) pttweb 搜尋
    if not official_ok:
        for term in search_terms:
            try:
                found = fetch_pttweb_search(term, session=sess, sleep_sec=sleep_sec)
                posts.extend(found)
                mode = "pttweb_search"
            except PTTError as exc:
                errors.append(str(exc))

    dedup: dict[str, dict] = {p["post_id"]: p for p in posts if p.get("post_id")}
    posts = list(dedup.values())

    # 3) 仍無結果：抓最新/熱門後關鍵字過濾
    if not posts:
        mode = "pttweb_filter"
        try:
            recent = fetch_pttweb_recent(
                session=sess, pages=index_pages, sleep_sec=sleep_sec
            )
            posts = [p for p in recent if _title_matches(p["title"], kws)]
        except PTTError as exc:
            errors.append(str(exc))
            raise PTTError("；".join(errors) if errors else "PTT 抓取失敗") from exc

    if not posts and errors:
        # 有嘗試但完全沒資料時不算致命，回傳 0 分
        pass

    posts.sort(key=lambda p: (-int(p.get("push_count") or 0), p.get("title") or ""))
    # 計分只用前 30 篇，避免搜尋結果過長造成分數失真；詳情頁仍可看這些文章
    score_posts = posts[:30]
    article_count = len(score_posts)
    total_push = sum(int(p.get("push_count") or 0) for p in score_posts)

    return {
        "article_count": article_count,
        "total_push": total_push,
        "posts": score_posts,
        "keywords": kws,
        "mode": mode,
        "errors": errors,
        "fetched_at": datetime.now(TW).isoformat(timespec="seconds"),
    }
