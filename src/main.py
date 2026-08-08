"""台股網路熱度搜尋器:抓取 PTT / Google News / 成交量並產出報表。

用法:
    python3 src/main.py            # 完整執行(30 檔、三個視窗)
    python3 src/main.py --limit 3  # 只跑前 3 檔(測試用)
    python3 src/main.py --skip-volume
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import ROOT, WINDOWS, load_stocks
from fetch_news import fetch_news
from fetch_ptt import fetch_ptt
from fetch_volume import fetch_volume
from scoring import build_report


def main() -> None:
    parser = argparse.ArgumentParser(description="台股網路熱度搜尋器")
    parser.add_argument("--limit", type=int, help="只處理前 N 檔股票(測試用)")
    parser.add_argument("--skip-volume", action="store_true", help="略過成交量抓取")
    parser.add_argument("--skip-ptt", action="store_true", help="略過 PTT 抓取")
    parser.add_argument("--skip-news", action="store_true", help="略過新聞抓取")
    args = parser.parse_args()

    stocks = load_stocks()
    if args.limit:
        stocks = stocks[: args.limit]
    max_days = max(WINDOWS)

    print(f"共 {len(stocks)} 檔股票,統計視窗:{WINDOWS} 天")

    print("\n[1/3] 抓取 PTT Stock 板討論…")
    ptt = {} if args.skip_ptt else fetch_ptt(stocks, max_days)

    print("\n[2/3] 抓取 Google News…")
    news = {} if args.skip_news else fetch_news(stocks, max_days)

    print("\n[3/3] 抓取成交量…")
    volume = {} if args.skip_volume else fetch_volume(stocks, max_days)

    report = build_report(stocks, WINDOWS, ptt, news, volume)

    data_path = ROOT / "data" / "heat.json"
    data_path.parent.mkdir(exist_ok=True)
    data_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    # docs/data.js:讓 docs/index.html 直接以 file:// 開啟也能載入資料
    js_path = ROOT / "docs" / "data.js"
    js_path.write_text(
        "window.HEAT_DATA = " + json.dumps(report, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )

    print(f"\n完成:{data_path.relative_to(Path.cwd()) if data_path.is_relative_to(Path.cwd()) else data_path}")
    top = report["windows"][str(max_days)][:5]
    print(f"\n近 {max_days} 天熱度前五名:")
    for r in top:
        print(
            f"  {r['rank']}. {r['name']}({r['code']}) 分數 {r['score']} | "
            f"PTT {r['ptt_articles']} 篇/{r['ptt_comments']} 留言 | "
            f"新聞 {r['news_count']}{'+' if r['news_saturated'] else ''} 則"
        )


if __name__ == "__main__":
    main()
