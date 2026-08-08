"""熱度計分:各視窗指標統計、正規化與加權綜合分數。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

TAIPEI_TZ = timezone(timedelta(hours=8))

# 綜合分數權重(來源整體缺資料時會自動重新分配)
WEIGHTS = {
    "ptt_articles": 0.25,
    "ptt_comments": 0.25,
    "news_count": 0.30,
    "vol_change": 0.20,
}


def _window_metrics(
    stock: dict, days: int, now: datetime, ptt: dict, news: dict, volume: dict
) -> dict:
    code = stock["code"]
    since_ts = (now - timedelta(days=days)).timestamp()

    arts = [a for a in ptt.get(code, {}).get("articles", []) if a["ts"] >= since_ts]
    ptt_articles = len(arts)
    ptt_comments = sum(a["comments"] for a in arts)

    news_data = news.get(code, {})
    items = [i for i in news_data.get("items", []) if i["ts"] >= since_ts]
    news_count = len(items)
    # RSS 回滿 100 則且最舊一則仍落在視窗內 => 視窗內實際新聞數被低估
    oldest_ts = min((i["ts"] for i in news_data.get("items", [])), default=None)
    news_saturated = bool(
        news_data.get("saturated") and oldest_ts is not None and oldest_ts >= since_ts
    )

    daily = volume.get(code, {}).get("daily", [])
    since_date = (now - timedelta(days=days)).date().isoformat()
    prev_since_date = (now - timedelta(days=days * 2)).date().isoformat()
    cur = [r["value"] for r in daily if r["date"] >= since_date]
    prev = [
        r["value"] for r in daily if prev_since_date <= r["date"] < since_date
    ]
    vol_avg = sum(cur) / len(cur) if cur else 0.0
    prev_avg = sum(prev) / len(prev) if prev else 0.0
    vol_change_pct = (
        round((vol_avg - prev_avg) / prev_avg * 100, 1) if prev_avg > 0 else None
    )

    return {
        "code": code,
        "name": stock["name"],
        "market": stock["market"],
        "ptt_articles": ptt_articles,
        "ptt_comments": ptt_comments,
        "news_count": news_count,
        "news_saturated": news_saturated,
        "vol_avg_value": round(vol_avg / 1e8, 2),  # 億元
        "vol_change_pct": vol_change_pct,
    }


def _normalize(rows: list[dict]) -> None:
    """就地為每列加上 score(0~100)。"""
    max_art = max((r["ptt_articles"] for r in rows), default=0)
    max_com = max((r["ptt_comments"] for r in rows), default=0)
    max_news = max((r["news_count"] for r in rows), default=0)
    changes = [r["vol_change_pct"] for r in rows if r["vol_change_pct"] is not None]
    min_chg, max_chg = (min(changes), max(changes)) if changes else (0, 0)

    for r in rows:
        parts: dict[str, float] = {}
        if max_art > 0:
            parts["ptt_articles"] = r["ptt_articles"] / max_art * 100
        if max_com > 0:
            parts["ptt_comments"] = r["ptt_comments"] / max_com * 100
        if max_news > 0:
            parts["news_count"] = r["news_count"] / max_news * 100
        if r["vol_change_pct"] is not None and max_chg > min_chg:
            parts["vol_change"] = (
                (r["vol_change_pct"] - min_chg) / (max_chg - min_chg) * 100
            )

        total_w = sum(WEIGHTS[k] for k in parts)
        r["score"] = (
            round(sum(WEIGHTS[k] * v for k, v in parts.items()) / total_w, 1)
            if total_w > 0
            else 0.0
        )


def build_report(
    stocks: list[dict],
    windows: list[int],
    ptt: dict,
    news: dict,
    volume: dict,
) -> dict:
    now = datetime.now(TAIPEI_TZ)
    report: dict = {
        "generated_at": now.isoformat(timespec="seconds"),
        "windows": {},
        "details": {},
    }

    for days in windows:
        rows = [
            _window_metrics(s, days, now, ptt, news, volume) for s in stocks
        ]
        _normalize(rows)
        rows.sort(key=lambda r: (-r["score"], r["code"]))
        for i, r in enumerate(rows, 1):
            r["rank"] = i
        report["windows"][str(days)] = rows

    for s in stocks:
        code = s["code"]
        arts = ptt.get(code, {}).get("articles", [])
        top_ptt = sorted(arts, key=lambda a: -a["comments"])[:5]
        items = news.get(code, {}).get("items", [])[:5]
        report["details"][code] = {
            "ptt_top": [
                {
                    "title": a["title"],
                    "comments": a["comments"],
                    "url": f"https://www.pttweb.cc/bbs/Stock/{a['aid']}",
                    "ts": a["ts"],
                }
                for a in top_ptt
            ],
            "news_top": [
                {"title": i["title"], "url": i["link"], "ts": i["ts"]} for i in items
            ],
        }
    return report
