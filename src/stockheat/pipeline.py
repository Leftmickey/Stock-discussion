"""每日批次與首次建庫流程。

兩個入口共用同一組步驟，差別只在時間窗：
  run_backfill  首次建庫，往回抓 30 天
  run_daily     每日收盤後增量

任一步驟中斷都可以直接重跑：文章以 source_id 去重，聚合層每次整批重算。
單一步驟失敗不會中止整批——交易所 API 掛掉時，PTT 的部分還是該照跑。
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from stockheat.collectors import news_rss
from stockheat.collectors.ptt import crawl_to_db
from stockheat.config import TAIPEI, Settings
from stockheat.config import settings as default_settings
from stockheat.matching import load_engine, rematch_all
from stockheat.scoring import compute_scores
from stockheat.storage import repo
from stockheat.universe import refresh_universe

logger = logging.getLogger(__name__)

StepFn = Callable[[str, str], None]


@dataclass
class PipelineReport:
    started_at: str = ""
    finished_at: str = ""
    steps: dict[str, dict] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def ok(self) -> bool:
        return not self.errors


def run_pipeline(
    conn: sqlite3.Connection,
    days: int,
    config: Settings | None = None,
    skip_news: bool = False,
    skip_universe: bool = False,
    on_step: StepFn | None = None,
    progress=None,
) -> PipelineReport:
    cfg = config or default_settings
    report = PipelineReport(started_at=datetime.now(TAIPEI).isoformat(timespec="seconds"))

    def step(name: str, message: str) -> None:
        logger.info("[%s] %s", name, message)
        if on_step:
            on_step(name, message)

    def guard(name: str, label: str, fn) -> None:
        step(name, label)
        try:
            report.steps[name] = fn()
        except Exception as exc:
            report.errors.append(f"{label}失敗：{exc}")
            logger.exception("%s 失敗", label)

    if not skip_universe:
        guard("universe", "更新全市場標的主檔與當日行情", lambda: refresh_universe(conn))

    def crawl():
        result = crawl_to_db(conn, days=days, config=cfg.ptt, progress=progress)
        return {
            "index_pages": result.index_pages,
            "discovered": result.discovered,
            "downloaded": result.downloaded,
            "refreshed": result.refreshed,
            "skipped_known": result.skipped_known,
            "failed": result.failed,
        }

    guard("ptt", f"採集 PTT {cfg.ptt.board} 板近 {days} 天文章", crawl)
    guard("match", "比對全市場標的提及", lambda: rematch_all(conn, load_engine(conn)))

    if not skip_news:
        targets = news_rss.news_targets(conn, top_n=cfg.trends.top_n)
        guard("news", f"採集 {len(targets)} 檔的新聞", lambda: news_rss.collect_news(conn, targets, cfg.news))

    guard("score", "計算熱度與情緒", lambda: compute_scores(conn, cfg.scoring))

    if cfg.trends.enabled:
        def trends_step():
            from stockheat.collectors import trends

            result = trends.collect_trends(conn, cfg.trends)
            compute_scores(conn, cfg.scoring)
            return result

        guard("trends", "取得 Google Trends 搜尋熱度", trends_step)

    report.finished_at = datetime.now(TAIPEI).isoformat(timespec="seconds")
    repo.set_fetch_state(
        conn,
        "pipeline",
        "daily",
        "ok" if report.ok() else "error",
        cursor=report.finished_at,
        message="；".join(report.errors) if report.errors else "完成",
    )
    conn.commit()
    return report


def run_backfill(conn: sqlite3.Connection, days: int | None = None, **kwargs) -> PipelineReport:
    cfg = kwargs.pop("config", None) or default_settings
    return run_pipeline(conn, days=days or cfg.backfill_days, config=cfg, **kwargs)


def run_daily(conn: sqlite3.Connection, **kwargs) -> PipelineReport:
    cfg = kwargs.pop("config", None) or default_settings
    # 增量仍以完整時間窗為界：舊文章的推文數會變動，
    # 而熱度是以「當日全市場相對強度」計算，基準期必須跟著更新。
    return run_pipeline(conn, days=cfg.backfill_days, config=cfg, **kwargs)
