"""熱度分數正規化與綜合計算。"""

from __future__ import annotations

import math


def clamp(value: float | None, low: float = 0.0, high: float = 100.0) -> float | None:
    if value is None:
        return None
    return max(low, min(high, float(value)))


def normalize_trends(raw: float | None) -> float | None:
    """Google Trends 本身已是 0–100。"""
    return clamp(raw)


def normalize_ptt(article_count: int, total_push: int) -> float:
    """
    將 PTT 討論量映射到 0–100。
    使用 log 壓縮，避免搜尋命中一多就全部滿分，保留相對差異。
    """
    articles = max(0, int(article_count))
    pushes = max(0, int(total_push))
    # 約十余篇有討論時進入中高分；爆量標的才接近 100
    raw = 18.0 * math.log1p(articles) + 8.0 * math.log1p(pushes)
    return float(clamp(raw))


def composite_score(
    trends: float | None,
    ptt: float | None,
    trends_weight: float = 0.5,
    ptt_weight: float = 0.5,
) -> float | None:
    if trends is None and ptt is None:
        return None
    if trends is None:
        return clamp(ptt)
    if ptt is None:
        return clamp(trends)
    total_w = trends_weight + ptt_weight
    if total_w <= 0:
        return None
    score = (trends * trends_weight + ptt * ptt_weight) / total_w
    return float(clamp(score))


def score_delta(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    return float(current) - float(previous)
