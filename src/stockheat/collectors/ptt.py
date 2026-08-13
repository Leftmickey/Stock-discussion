"""PTT 看板採集器。

架構關鍵：不對每檔股票各發一次搜尋，而是把整個看板爬下來建成本地文章庫，
再由比對層一次掃描出全市場所有標的的提及。這讓「支援全市場」的邊際成本趨近於零，
同時把對 PTT 的請求量壓到最低。

索引頁的文章連結本身就含 epoch，因此不必下載文章就能判斷它落在時間窗內外，
30 天回補只會下載真正需要的文章。
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import md5
from pathlib import Path

import httpx

from stockheat.collectors import ptt_parser as parser
from stockheat.config import CACHE_DIR, TAIPEI, PttConfig
from stockheat.storage import repo
from stockheat.utils import get_with_retry, make_client

logger = logging.getLogger(__name__)

ProgressFn = Callable[[str, int, int], None]


class RateLimiter:
    """跨執行緒的最小請求間隔，確保並發下仍維持對站方友善的節奏。"""

    def __init__(self, interval: float) -> None:
        self._interval = interval
        self._lock = threading.Lock()
        self._next_at = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            sleep_for = max(0.0, self._next_at - now)
            self._next_at = max(now, self._next_at) + self._interval
        if sleep_for > 0:
            time.sleep(sleep_for)


@dataclass
class CrawlResult:
    index_pages: int = 0
    discovered: int = 0
    downloaded: int = 0
    skipped_known: int = 0
    refreshed: int = 0
    failed: int = 0


class PttCrawler:
    def __init__(
        self,
        config: PttConfig | None = None,
        cache_dir: Path | None = None,
        use_cache: bool = True,
    ) -> None:
        self.config = config or PttConfig()
        self.cache_dir = (cache_dir or CACHE_DIR) / "ptt"
        self.use_cache = use_cache
        self.limiter = RateLimiter(self.config.request_interval)
        self._client: httpx.Client | None = None

    def __enter__(self) -> PttCrawler:
        self._client = make_client(timeout=self.config.timeout, cookies={"over18": "1"})
        return self

    def __exit__(self, *exc: object) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _cache_path(self, url: str) -> Path:
        digest = md5(url.encode("utf-8")).hexdigest()
        return self.cache_dir / digest[:2] / f"{digest}.html"

    def _fetch(self, url: str, allow_cache: bool = True) -> str | None:
        path = self._cache_path(url)
        if self.use_cache and allow_cache and path.exists():
            return path.read_text(encoding="utf-8", errors="replace")

        assert self._client is not None, "PttCrawler 必須以 with 陳述式使用"
        self.limiter.wait()
        resp = get_with_retry(self._client, url, max_retries=self.config.max_retries)
        if resp is None:
            return None
        html = resp.text
        if self.use_cache:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(html, encoding="utf-8")
        return html

    # ---------------------------------------------------------------- 索引頁

    def iter_index_entries(
        self, since: datetime, progress: ProgressFn | None = None
    ) -> tuple[list[parser.IndexEntry], int]:
        """由最新頁往回走，收集時間窗內的文章連結。

        一律走完整個時間窗，不做「整頁都已抓過就提前停止」的優化。
        那個優化假設「這一頁全在庫裡，更舊的也一定在」，只要前一次回補被中斷過
        就不成立，會讓後續每次執行都只走一頁就結束，而且完全不會報錯。
        走完 30 天約 110 個索引頁、不到一分鐘，不值得為此冒資料靜默不完整的風險。

        索引頁不快取：內容每天都在變。
        """
        board = self.config.board
        base = self.config.base_url
        since_epoch = int(since.timestamp())

        url = f"{base}/bbs/{board}/index.html"
        collected: dict[str, parser.IndexEntry] = {}
        pages = 0

        while url and pages < self.config.max_index_pages:
            html = self._fetch(url, allow_cache=False)
            if html is None:
                logger.warning("索引頁取得失敗，停在 %s", url)
                break
            pages += 1

            entries = parser.parse_index(html, base_url=base)
            for e in entries:
                if e.epoch and e.epoch >= since_epoch:
                    collected[e.source_id] = e

            if progress:
                progress("index", pages, len(collected))

            epochs = [e.epoch for e in entries if e.epoch]
            if epochs and max(epochs) < since_epoch:
                break

            prev = parser.parse_prev_page_number(html)
            url = f"{base}/bbs/{board}/index{prev}.html" if prev else None

        ordered = sorted(collected.values(), key=lambda e: e.epoch or 0, reverse=True)
        return ordered, pages

    # ------------------------------------------------------------------ 文章

    def fetch_article(
        self, entry: parser.IndexEntry, allow_cache: bool = True
    ) -> parser.Article | None:
        html = self._fetch(entry.url, allow_cache=allow_cache)
        if html is None:
            return None
        article = parser.parse_article(html, entry.url, fallback_epoch=entry.epoch)
        if article is not None and not article.title:
            article.title = entry.title
        return article

    def fetch_articles(
        self,
        entries: Iterable[parser.IndexEntry],
        progress: ProgressFn | None = None,
        refresh_ids: set[str] | None = None,
    ) -> Iterable[parser.Article]:
        """refresh_ids 內的文章會略過本地 HTML 快取，重新向 PTT 取回最新推文數。"""
        entries = list(entries)
        refresh = refresh_ids or set()
        total = len(entries)
        done = 0

        def fetch(entry: parser.IndexEntry) -> parser.Article | None:
            return self.fetch_article(entry, allow_cache=entry.source_id not in refresh)

        with ThreadPoolExecutor(max_workers=self.config.concurrency) as pool:
            for article in pool.map(fetch, entries):
                done += 1
                if progress and (done % 20 == 0 or done == total):
                    progress("article", done, total)
                if article is not None:
                    yield article


def crawl_to_db(
    conn: sqlite3.Connection,
    days: int,
    config: PttConfig | None = None,
    progress: ProgressFn | None = None,
    use_cache: bool = True,
) -> CrawlResult:
    """把時間窗內的文章抓進資料庫。

    已存在的文章會被跳過，所以中斷後直接重跑就能續爬，不需要額外維護待辦佇列。

    但最近幾天的文章一定重抓。推文會持續累積，一篇早上發的文在下午批次時可能
    只累積了幾小時的推噓；若就此定案，當日互動量會被系統性低估，
    讓每一天的熱度看起來都比前幾天低，直接扭曲 z-score。
    """
    config = config or PttConfig()
    now = datetime.now(TAIPEI)
    since = now - timedelta(days=days)
    refresh_after = int((now - timedelta(days=config.refresh_days)).timestamp())
    known = repo.existing_source_ids(conn, source="ptt")
    result = CrawlResult()

    with PttCrawler(config=config, use_cache=use_cache) as crawler:
        entries, pages = crawler.iter_index_entries(since, progress=progress)
        result.index_pages = pages
        result.discovered = len(entries)

        refresh_ids = {
            e.source_id
            for e in entries
            if e.epoch and e.epoch >= refresh_after and e.source_id in known
        }
        pending = [e for e in entries if e.source_id not in known or e.source_id in refresh_ids]
        result.skipped_known = len(entries) - len(pending)
        result.refreshed = len(refresh_ids)
        logger.info(
            "索引頁 %d 頁，時間窗內 %d 篇：待下載 %d 篇（其中 %d 篇為更新推文數）、既有 %d 篇",
            pages,
            len(entries),
            len(pending),
            len(refresh_ids),
            result.skipped_known,
        )

        repo.set_fetch_state(
            conn, "ptt", config.board, "running", message=f"待下載 {len(pending)} 篇"
        )
        conn.commit()

        batch = 0
        for article in crawler.fetch_articles(
            pending, progress=progress, refresh_ids=refresh_ids
        ):
            post_id = repo.upsert_post(
                conn,
                {
                    "source": "ptt",
                    "source_id": article.source_id,
                    "board": article.board or config.board,
                    "title": article.title,
                    "author": article.author,
                    "url": article.url,
                    "posted_at": article.posted_at.isoformat() if article.posted_at else None,
                    "push_count": article.push_count,
                    "boo_count": article.boo_count,
                    "neutral_count": article.neutral_count,
                    "content": article.content,
                },
            )
            repo.replace_comments(conn, post_id, article.comments)
            result.downloaded += 1
            batch += 1
            # 分批 commit，中途斷線也保得住已抓到的部分。
            if batch >= 50:
                conn.commit()
                batch = 0
        conn.commit()

    result.failed = len(entries) - result.skipped_known - result.downloaded
    repo.set_fetch_state(
        conn,
        "ptt",
        config.board,
        "ok",
        cursor=datetime.now(TAIPEI).isoformat(timespec="seconds"),
        message=f"下載 {result.downloaded} 篇、既有 {result.skipped_known} 篇、失敗 {result.failed} 篇",
    )
    conn.commit()
    return result
