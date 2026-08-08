"""標的模糊搜尋。"""

from __future__ import annotations

from rapidfuzz import fuzz


def normalize_query(q: str) -> str:
    return (
        (q or "")
        .strip()
        .upper()
        .replace("*", "")
        .replace("-KY", "")
        .replace("KY", "")
        .replace(" ", "")
    )


def stock_search_blob(stock: dict) -> list[str]:
    values = [stock.get("name", ""), stock.get("code", "")]
    values.extend(stock.get("aliases") or [])
    return [normalize_query(v) for v in values if v]


def score_stock(query: str, stock: dict) -> float:
    nq = normalize_query(query)
    if not nq:
        return 100.0

    best = 0.0
    for token in stock_search_blob(stock):
        if not token:
            continue
        if nq == token:
            return 100.0
        if nq in token or token in nq:
            best = max(best, 92.0)
        best = max(best, float(fuzz.partial_ratio(nq, token)))
        best = max(best, float(fuzz.token_set_ratio(nq, token)))
    return best


def search_stocks(
    stocks: list[dict], query: str, limit: int | None = None, min_score: float = 60.0
) -> list[dict]:
    q = (query or "").strip()
    if not q:
        return list(stocks) if limit is None else list(stocks)[:limit]

    ranked: list[tuple[float, dict]] = []
    for s in stocks:
        sc = score_stock(q, s)
        if sc >= min_score:
            ranked.append((sc, s))
    ranked.sort(key=lambda x: (-x[0], x[1]["code"]))
    result = [s for _, s in ranked]
    if limit is not None:
        return result[:limit]
    return result
