"""命令列入口。Windows 工作排程器直接呼叫 `stockheat daily`。"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime

from stockheat.config import DB_PATH, LOG_DIR, TAIPEI, ensure_dirs, settings
from stockheat.storage import db, repo


def _setup_logging(verbose: bool) -> None:
    ensure_dirs()
    log_file = LOG_DIR / f"stockheat-{datetime.now(TAIPEI):%Y%m}.log"
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    # httpx 每個請求都會記一行，回補時會刷掉上萬行日誌。
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _print_report(report) -> None:
    print()
    print(f"開始 {report.started_at}　結束 {report.finished_at}")
    for name, stats in report.steps.items():
        print(f"  {name:<10} {stats}")
    if report.errors:
        print("\n發生錯誤：")
        for err in report.errors:
            print(f"  - {err}")


def _progress(kind: str, done: int, total: int) -> None:
    label = "索引頁" if kind == "index" else "文章"
    suffix = "…" if kind == "index" else str(total)
    print(f"\r  {label} {done}/{suffix}", end="", flush=True)


def cmd_init(args: argparse.Namespace) -> int:
    from stockheat.universe import refresh_universe

    conn = db.init_db()
    stats = refresh_universe(conn)
    print(f"資料庫建立於 {DB_PATH}")
    print(f"標的 {stats['securities']} 檔、別名 {stats['aliases']} 組")
    print(f"預設自選 {len(repo.get_watchlist(conn))} 檔")
    return 0


def cmd_backfill(args: argparse.Namespace) -> int:
    from stockheat.pipeline import run_backfill

    conn = db.init_db()
    report = run_backfill(conn, days=args.days, skip_news=args.no_news, progress=_progress)
    _print_report(report)
    return 0 if report.ok() else 1


def cmd_daily(args: argparse.Namespace) -> int:
    from stockheat.pipeline import run_daily

    conn = db.init_db()
    report = run_daily(conn, skip_news=args.no_news, progress=_progress)
    _print_report(report)
    return 0 if report.ok() else 1


def cmd_rematch(args: argparse.Namespace) -> int:
    from stockheat.matching import rematch_all
    from stockheat.scoring import compute_scores

    conn = db.init_db()
    print("重跑比對…", flush=True)
    print(" ", rematch_all(conn))
    print("重算熱度…", flush=True)
    print(" ", compute_scores(conn, settings.scoring))
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    conn = db.init_db()
    rows = repo.search_stocks(conn, args.keyword)
    if not rows:
        print(f"找不到「{args.keyword}」")
        return 1
    latest = repo.latest_score_date(conn)
    for r in rows:
        score = None
        if latest:
            score = conn.execute(
                "SELECT heat_score, z_score, rank, sentiment_label FROM heat_scores"
                " WHERE date = ? AND symbol = ?",
                (latest, r["symbol"]),
            ).fetchone()
        if score:
            z = f"{score['z_score']:+.2f}" if score["z_score"] is not None else "—"
            tail = (
                f"　熱度 {score['heat_score']:.0f}　異常 {z}"
                f"　排名 {score['rank']}　{score['sentiment_label']}"
            )
        else:
            tail = "　近期無討論紀錄"
        print(f"{r['symbol']:<8}{r['name']:<12}{r['market']}{tail}")
    return 0


def cmd_prices(args: argparse.Namespace) -> int:
    from stockheat.collectors.prices import backfill_prices

    conn = db.init_db()
    symbols = args.symbols or [r["symbol"] for r in repo.get_watchlist(conn)]
    print(f"回補 {len(symbols)} 檔、近 {args.days} 天行情（受交易所速率限制，請耐心等候）")
    print(backfill_prices(conn, symbols, days=args.days))
    return 0


def cmd_watchlist(args: argparse.Namespace) -> int:
    conn = db.init_db()
    if args.add:
        repo.add_to_watchlist(conn, args.add)
        conn.commit()
    if args.remove:
        repo.remove_from_watchlist(conn, args.remove)
        conn.commit()
    for r in repo.get_watchlist(conn):
        print(f"{r['symbol']:<8}{r['name'] or '（不在主檔）'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="stockheat", description="台股標的查詢與網路討論熱度追蹤器"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="輸出除錯訊息")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="建立資料庫並抓取全市場標的主檔")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("backfill", help="首次建庫：回補指定天數的討論資料")
    p.add_argument("--days", type=int, default=settings.backfill_days)
    p.add_argument("--no-news", action="store_true", help="略過新聞採集")
    p.set_defaults(func=cmd_backfill)

    p = sub.add_parser("daily", help="每日收盤後增量更新")
    p.add_argument("--no-news", action="store_true")
    p.set_defaults(func=cmd_daily)

    p = sub.add_parser("rematch", help="調整消歧規則後重跑比對與計分，不重新爬取")
    p.set_defaults(func=cmd_rematch)

    p = sub.add_parser("search", help="以代號或名稱查詢標的")
    p.add_argument("keyword")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("prices", help="回補個股歷史行情")
    p.add_argument("symbols", nargs="*", help="留空則回補自選清單")
    p.add_argument("--days", type=int, default=90)
    p.set_defaults(func=cmd_prices)

    p = sub.add_parser("watchlist", help="檢視或調整自選清單")
    p.add_argument("--add")
    p.add_argument("--remove")
    p.set_defaults(func=cmd_watchlist)

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
