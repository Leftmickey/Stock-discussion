"""情緒判讀：推噓比為主，台股用語詞典為輔。

不使用預訓練模型是刻意的選擇。開源的繁體中文金融情緒分類器並不存在
（FinBERT2 是簡體語料的預訓練骨幹，需自行微調），而通用中文情感模型在股板語境下
會系統性判錯：「軋空」是大利多、「畢業」是慘賠出場、「住套房」跟房地產無關。

PTT 的推與噓本身就是台股散戶情緒的天然標註，是這個場景裡免費且準確度最高的訊號，
詞典只用來補足推文量不足的文章。
"""

from __future__ import annotations

from dataclasses import dataclass

from stockheat.config import ScoringConfig
from stockheat.resources import load_lexicon

# 否定詞出現在情緒詞前方幾個字元內就反轉極性（「不看好」「沒起飛」）。
NEGATION_WINDOW = 3


@dataclass(frozen=True)
class SentimentBreakdown:
    score: float  # -1 ~ +1
    push_ratio: float
    lexicon_score: float
    bullish_hits: int
    bearish_hits: int


def _count_polarity(
    text: str, terms: dict[str, float], negations: tuple[str, ...]
) -> tuple[float, float, int]:
    """回傳 (維持原極性的權重, 被否定而反轉的權重, 命中次數)。"""
    positive = 0.0
    flipped = 0.0
    hits = 0
    for term, weight in terms.items():
        start = 0
        while True:
            idx = text.find(term, start)
            if idx < 0:
                break
            start = idx + len(term)
            hits += 1
            prefix = text[max(0, idx - NEGATION_WINDOW) : idx]
            if any(neg in prefix for neg in negations):
                flipped += weight
            else:
                positive += weight
    return positive, flipped, hits


def lexicon_sentiment(text: str) -> tuple[float, int, int]:
    """以多空詞典評分，回傳 (分數 -1~1, 看多命中, 看空命中)。"""
    lex = load_lexicon()
    negations = lex["negations"]

    bull, bull_flipped, bull_hits = _count_polarity(text, lex["bullish"], negations)
    bear, bear_flipped, bear_hits = _count_polarity(text, lex["bearish"], negations)

    # 被否定的看多詞算作看空，反之亦然。
    total_bull = bull + bear_flipped
    total_bear = bear + bull_flipped
    denom = total_bull + total_bear
    if denom == 0:
        return 0.0, 0, 0
    return (total_bull - total_bear) / denom, bull_hits, bear_hits


def post_sentiment(
    title: str,
    content: str | None,
    comments: list[dict[str, str]] | None = None,
    push_count: int | None = None,
    boo_count: int | None = None,
    config: ScoringConfig | None = None,
) -> SentimentBreakdown:
    """單篇文章的情緒。

    推噓比與詞典各自產生 -1~1 的分數再加權。文章沒有任何推噓時，
    推噓比為 0（中性）而非缺值，讓權重維持穩定。
    """
    cfg = config or ScoringConfig()

    if push_count is None or boo_count is None:
        comments = comments or []
        push_count = sum(1 for c in comments if c.get("tag") == "push")
        boo_count = sum(1 for c in comments if c.get("tag") == "boo")

    # 平滑常數讓「推 1 噓 0」不會等同於「推 100 噓 0」。
    push_ratio = (push_count - boo_count) / (push_count + boo_count + cfg.sentiment_smoothing)

    parts = [title or "", content or ""]
    if comments:
        parts.extend(c.get("text", "") for c in comments)
    lex_score, bull_hits, bear_hits = lexicon_sentiment("\n".join(parts))

    score = cfg.weight_pushratio * push_ratio + cfg.weight_lexicon * lex_score
    return SentimentBreakdown(
        score=max(-1.0, min(1.0, score)),
        push_ratio=push_ratio,
        lexicon_score=lex_score,
        bullish_hits=bull_hits,
        bearish_hits=bear_hits,
    )


def label(score: float | None, mention_count: int, config: ScoringConfig | None = None) -> str:
    """把分數轉成標籤。樣本太少時明說，不要給假精確的判斷。"""
    cfg = config or ScoringConfig()
    if score is None or mention_count < cfg.sentiment_min_mentions:
        return "樣本不足"
    if score >= 0.35:
        return "看多"
    if score >= 0.12:
        return "偏多"
    if score <= -0.35:
        return "看空"
    if score <= -0.12:
        return "偏空"
    return "中性"
