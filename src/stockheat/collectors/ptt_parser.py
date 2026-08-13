"""PTT 網頁版 HTML 解析。

抽成獨立模組是為了能用 fixture 測試——PTT 偶爾會改版，
解析器必須是整個專案裡測試覆蓋最完整的部分。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from bs4 import BeautifulSoup

from stockheat.config import TAIPEI

# 文章 ID 形如 M.1754500000.A.ABC，中間那段是伺服器寫入的 epoch。
# 它比內文的「時間」欄可靠（時間欄可被發文者偽造），所以拿它當主要時間來源。
# 另一個好處是不必下載文章就能判斷它落在時間窗內外。
ARTICLE_ID_RE = re.compile(r"(M\.(\d+)\.A\.[0-9A-Za-z]+)")
PUSH_TAG_MAP = {"推": "push", "噓": "boo", "→": "neutral"}


@dataclass
class IndexEntry:
    source_id: str
    url: str
    title: str
    author: str | None
    epoch: int | None
    nrec: int


@dataclass
class Article:
    source_id: str
    url: str
    title: str
    author: str | None
    board: str | None
    posted_at: datetime | None
    content: str
    comments: list[dict[str, str]] = field(default_factory=list)

    @property
    def push_count(self) -> int:
        return sum(1 for c in self.comments if c["tag"] == "push")

    @property
    def boo_count(self) -> int:
        return sum(1 for c in self.comments if c["tag"] == "boo")

    @property
    def neutral_count(self) -> int:
        return sum(1 for c in self.comments if c["tag"] == "neutral")


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def parse_article_id(href: str) -> tuple[str | None, int | None]:
    m = ARTICLE_ID_RE.search(href or "")
    if not m:
        return None, None
    return m.group(1), int(m.group(2))


def parse_nrec(text: str | None) -> int:
    """推文數欄位：數字、「爆」（>=100）、X1~X9 與 XX（負推）。"""
    if not text:
        return 0
    text = text.strip()
    if text == "爆":
        return 100
    if text == "XX":
        return -100
    if text.startswith("X"):
        try:
            return -int(text[1:]) * 10
        except ValueError:
            return -10
    try:
        return int(text)
    except ValueError:
        return 0


def parse_index(html: str, base_url: str = "https://www.ptt.cc") -> list[IndexEntry]:
    """解析看板索引頁的文章列表。

    置底公告（r-list-sep 之後的區塊）會被排除，它們天天出現，
    計入熱度會替被提及的個股製造穩定的假訊號。
    """
    soup = _soup(html)
    container = soup.find("div", class_="r-list-container")
    if container is None:
        return []

    entries: list[IndexEntry] = []
    for node in container.find_all("div", recursive=False):
        classes = node.get("class") or []
        if "r-list-sep" in classes:
            break  # 分隔線以下是置底公告
        if "r-ent" not in classes:
            continue

        title_div = node.find("div", class_="title")
        link = title_div.find("a") if title_div else None
        if link is None:
            continue  # 已刪除的文章沒有連結

        href = link.get("href", "")
        source_id, epoch = parse_article_id(href)
        if not source_id:
            continue

        author_div = node.find("div", class_="author")
        nrec_div = node.find("div", class_="nrec")
        entries.append(
            IndexEntry(
                source_id=source_id,
                url=base_url + href,
                title=link.get_text(strip=True),
                author=author_div.get_text(strip=True) if author_div else None,
                epoch=epoch,
                nrec=parse_nrec(nrec_div.get_text(strip=True) if nrec_div else None),
            )
        )
    return entries


PREV_PAGE_RE = re.compile(r"index(\d+)\.html")


def parse_prev_page_number(html: str) -> int | None:
    """從分頁列取出「‹ 上頁」的索引頁號。"""
    soup = _soup(html)
    group = soup.find("div", class_="btn-group-paging")
    if group is None:
        return None
    for a in group.find_all("a"):
        if "上頁" in a.get_text():
            if "disabled" in (a.get("class") or []):
                return None
            m = PREV_PAGE_RE.search(a.get("href", ""))
            if m:
                return int(m.group(1))
    return None


def _parse_post_time(value: str) -> datetime | None:
    """PTT 時間欄格式為 'Thu Aug  7 12:34:56 2026'（單位數日期會有雙空格）。"""
    normalized = " ".join(value.split())
    for fmt in ("%a %b %d %H:%M:%S %Y", "%b %d %H:%M:%S %Y"):
        try:
            return datetime.strptime(normalized, fmt).replace(tzinfo=TAIPEI)
        except ValueError:
            continue
    return None


def parse_article(html: str, url: str, fallback_epoch: int | None = None) -> Article | None:
    soup = _soup(html)
    main = soup.find("div", id="main-content")
    if main is None:
        return None

    meta: dict[str, str] = {}
    for line in main.find_all("div", class_=["article-metaline", "article-metaline-right"]):
        tag = line.find("span", class_="article-meta-tag")
        val = line.find("span", class_="article-meta-value")
        if tag and val:
            meta[tag.get_text(strip=True)] = val.get_text(strip=True)
        line.decompose()

    comments: list[dict[str, str]] = []
    for push in main.find_all("div", class_="push"):
        tag_node = push.find("span", class_="push-tag")
        user_node = push.find("span", class_="push-userid")
        text_node = push.find("span", class_="push-content")
        raw_tag = tag_node.get_text(strip=True) if tag_node else ""
        comments.append(
            {
                "tag": PUSH_TAG_MAP.get(raw_tag, "neutral"),
                "author": user_node.get_text(strip=True) if user_node else "",
                "text": (text_node.get_text() if text_node else "").lstrip(": ").strip(),
            }
        )
        push.decompose()

    # 剩下的就是正文加簽名檔，把 ※ 開頭的系統訊息切掉。
    for span in main.find_all("span", class_="f2"):
        span.decompose()
    content = main.get_text("\n", strip=True)
    content = re.sub(r"^※.*$", "", content, flags=re.MULTILINE).strip()

    source_id, epoch = parse_article_id(url)
    posted_at = None
    if fallback_epoch or epoch:
        posted_at = datetime.fromtimestamp(fallback_epoch or epoch, tz=TAIPEI)
    if posted_at is None and meta.get("時間"):
        posted_at = _parse_post_time(meta["時間"])

    author = meta.get("作者", "")
    if author:
        author = author.split("(")[0].strip()

    return Article(
        source_id=source_id or url,
        url=url,
        title=meta.get("標題", "").strip(),
        author=author or None,
        board=meta.get("看板"),
        posted_at=posted_at,
        content=content,
        comments=comments,
    )


TITLE_TAG_RE = re.compile(r"^(?:Re:\s*|Fw:\s*)*\[([^\]]{1,6})\]")


def title_tag(title: str) -> str | None:
    """取出標題的分類標籤：'[標的] 2330 台積電' → '標的'。"""
    m = TITLE_TAG_RE.match(title.strip())
    return m.group(1).strip() if m else None
