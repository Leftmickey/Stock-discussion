"""全市場標的比對與消歧。

規模問題：2,400 檔標的、6,800 個別名，要對上萬篇文章比對。逐檔正則掃描是
O(標的數 × 文章數)，完全跑不動；改用 Aho-Corasick 自動機，一次掃描就能找出
文本中所有別名的出現位置，複雜度與別名數量無關（實測約每秒 6 萬篇）。

準確度比效能更棘手。這裡針對幾個在台股文本裡真實會發生的誤判做防護：
  - 年份撞代號：2024 志聯、2025 千興、2026 志剛都是真實股票
  - 日期黏連：20260807 不該被切出 2026
  - 短名被長名包含：「南亞科技」裡的「南亞」不是 1303 南亞
  - 通用詞簡稱：「世界」「數字」是日常用語
  - 裸代號撞數字：內文的「1783」多半是股價或指數點位，不是和康生
"""

from __future__ import annotations

import re
import sqlite3
from bisect import bisect_left
from dataclasses import dataclass

import ahocorasick

from stockheat.collectors.ptt_parser import title_tag
from stockheat.resources import load_lexicon
from stockheat.storage import repo
from stockheat.universe.normalize import (
    CONTEXT_CODE,
    CONTEXT_NEARBY,
    CONTEXT_NONE,
    MATCHABLE_TYPES,
)

# 命中位置前後多少字元內算是「鄰近語境」。
CONTEXT_WINDOW = 25

DIGIT_RE = re.compile(r"\d")

# 緊接在代號後方就足以判定它是年份而非股票代號的字串。
#
# 刻意不含「月」：真正的日期會寫成「2026 年 8 月」，前面的「年」已經擋掉了；
# 但「2059 月營收」這種標題很常見，把「月」列進來會把合法的代號一起濾掉。
YEAR_FOLLOWERS = ("年", "Q1", "Q2", "Q3", "Q4", "q1", "q2", "q3", "q4", "上半", "下半")
# 緊接在代號前方的區間或紀年用語。
YEAR_LEADERS = ("西元", "民國", "至", "到", "~", "～", "－", "—")


@dataclass(frozen=True)
class Hit:
    start: int
    end: int
    symbol: str
    alias: str
    level: int
    alias_type: str


@dataclass
class Match:
    symbol: str
    match_type: str
    confidence: float
    in_title: bool
    evidence: str


MATCH_CONFIDENCE = {
    "title_tag": 1.0,
    "code_with_name": 0.95,
    "name": 0.85,
    "code_context": 0.70,
    "name_context": 0.65,
}


def is_etf_code(symbol: str) -> bool:
    return symbol.startswith("00")


class MatchEngine:
    def __init__(
        self,
        aliases: list[tuple[str, str, str, int]],
        context_tokens: frozenset[str] | None = None,
    ) -> None:
        """aliases 為 (symbol, alias, alias_type, requires_context) 序列。"""
        lexicon = load_lexicon()
        self.context_tokens = context_tokens or lexicon["context_tokens"]
        self.strong_title_tags = set(lexicon["title_tags"].get("strong", []))

        self.automaton = ahocorasick.Automaton()
        grouped: dict[str, list[tuple[str, str, int]]] = {}
        for symbol, alias, alias_type, level in aliases:
            grouped.setdefault(alias, []).append((symbol, alias_type, level))
        for alias, owners in grouped.items():
            self.automaton.add_word(alias, (alias, owners))
        self.automaton.make_automaton()

        self.context_automaton = ahocorasick.Automaton()
        for token in self.context_tokens:
            self.context_automaton.add_word(token, token)
        self.context_automaton.make_automaton()

    # ------------------------------------------------------------------ 掃描

    def _raw_hits(self, text: str) -> list[Hit]:
        hits: list[Hit] = []
        for end_idx, (alias, owners) in self.automaton.iter(text):
            start = end_idx - len(alias) + 1
            for symbol, alias_type, level in owners:
                if alias_type == "code" and not self._valid_code_boundary(text, start, end_idx):
                    continue
                hits.append(Hit(start, end_idx + 1, symbol, alias, level, alias_type))
        return hits

    @staticmethod
    def _valid_code_boundary(text: str, start: int, end_idx: int) -> bool:
        """代號兩側不得為數字，且排除明顯是年份或日期的用法。"""
        if start > 0 and DIGIT_RE.match(text[start - 1]):
            return False
        if end_idx + 1 < len(text) and DIGIT_RE.match(text[end_idx + 1]):
            return False

        # 「2026 年」中間常有空白或全形空格，比對前先去掉。
        after = text[end_idx + 1 : end_idx + 6].lstrip(" \t　")
        if any(after.startswith(f) for f in YEAR_FOLLOWERS):
            return False
        before = text[max(0, start - 4) : start].rstrip(" \t　")
        if any(before.endswith(lead) for lead in YEAR_LEADERS):
            return False
        return True

    @staticmethod
    def _resolve_overlaps(hits: list[Hit]) -> list[Hit]:
        """同一段文字上最長的命中勝出。

        「南亞科技」同時命中 2408 的「南亞科」與 1303 的「南亞」，
        後者被前者完整包含且更短，屬於誤判，必須丟掉。
        """
        if not hits:
            return []
        ordered = sorted(hits, key=lambda h: (h.start, -(h.end - h.start)))
        kept: list[Hit] = []
        for hit in ordered:
            span = hit.end - hit.start
            covered = any(
                other.start <= hit.start
                and other.end >= hit.end
                and (other.end - other.start) > span
                for other in ordered
            )
            if not covered:
                kept.append(hit)
        return kept

    def _context_positions(self, text: str) -> list[int]:
        return sorted(end for end, _ in self.context_automaton.iter(text))

    @staticmethod
    def _has_nearby_context(positions: list[int], hit: Hit) -> bool:
        if not positions:
            return False
        idx = bisect_left(positions, hit.start - CONTEXT_WINDOW)
        return idx < len(positions) and positions[idx] <= hit.end + CONTEXT_WINDOW

    # ------------------------------------------------------------------ 判定

    def match(self, title: str, content: str | None) -> list[Match]:
        title = title or ""
        text = f"{title}\n{content or ''}"
        title_end = len(title)

        hits = self._resolve_overlaps(self._raw_hits(text))
        if not hits:
            return []

        ctx_positions = self._context_positions(text)
        is_strong_tag = (title_tag(title) or "") in self.strong_title_tags

        per_symbol: dict[str, list[Hit]] = {}
        for hit in hits:
            per_symbol.setdefault(hit.symbol, []).append(hit)

        results: list[Match] = []
        for symbol, symbol_hits in per_symbol.items():
            match = self._judge(symbol, symbol_hits, ctx_positions, title_end, is_strong_tag)
            if match is not None:
                results.append(match)
        results.sort(key=lambda m: (-m.confidence, m.symbol))
        return results

    def _judge(
        self,
        symbol: str,
        hits: list[Hit],
        ctx_positions: list[int],
        title_end: int,
        is_strong_tag: bool,
    ) -> Match | None:
        code_hits = [h for h in hits if h.alias_type == "code"]
        name_hits = [h for h in hits if h.alias_type != "code"]

        has_code = bool(code_hits)
        # 需要代號佐證的通用詞，在同篇沒看到代號時完全不採計。
        usable_names = [h for h in name_hits if h.level != CONTEXT_CODE or has_code]
        strong_names = [h for h in usable_names if h.level == CONTEXT_NONE]
        weak_names = [h for h in usable_names if h.level == CONTEXT_NEARBY]

        in_title = any(h.start < title_end for h in hits)

        # [標的] 文一定是在談特定個股，標題命中即為最高信心。
        if is_strong_tag and in_title and (has_code or strong_names):
            return self._build(symbol, "title_tag", in_title, hits)

        if has_code and usable_names:
            return self._build(symbol, "code_with_name", in_title, hits)

        if strong_names:
            return self._build(symbol, "name", in_title, hits)

        # 只有裸代號、同篇完全沒出現公司名稱的情況。
        #
        # 實測 30 天資料顯示這類命中大多是誤判：內文的四位數多半是股價、指數點位
        # 或新聞編號，而在股板裡「鄰近有金融語彙」幾乎必然成立，擋不住。
        # 兩個例外值得保留：ETF 幾乎只會被以代號稱呼（沒人寫「元大台灣50」），
        # 以及代號出現在標題時，那通常是真的在指這檔股票。
        if has_code and (is_etf_code(symbol) or any(h.start < title_end for h in code_hits)):
            if any(self._has_nearby_context(ctx_positions, h) for h in code_hits):
                return self._build(symbol, "code_context", in_title, hits)

        if weak_names and any(self._has_nearby_context(ctx_positions, h) for h in weak_names):
            return self._build(symbol, "name_context", in_title, hits)

        return None

    @staticmethod
    def _build(symbol: str, match_type: str, in_title: bool, hits: list[Hit]) -> Match:
        seen: list[str] = []
        for h in hits:
            if h.alias not in seen:
                seen.append(h.alias)
        return Match(
            symbol=symbol,
            match_type=match_type,
            confidence=MATCH_CONFIDENCE[match_type],
            in_title=in_title,
            evidence="命中：" + "、".join(seen[:5]),
        )


def load_engine(conn: sqlite3.Connection) -> MatchEngine:
    """從資料庫載入可比對的別名，建成自動機。"""
    matchable = {
        r["symbol"] for r in repo.all_stocks(conn) if r["security_type"] in MATCHABLE_TYPES
    }
    aliases = [
        (r["symbol"], r["alias"], r["alias_type"], r["requires_context"])
        for r in repo.all_aliases(conn)
        if r["symbol"] in matchable
    ]
    return MatchEngine(aliases)


def rematch_all(conn: sqlite3.Connection, engine: MatchEngine | None = None) -> dict[str, int]:
    """對全部已存文章重跑比對。

    消歧規則調整後不需要重爬，這是把原始文本留在庫裡的主要理由。
    """
    engine = engine or load_engine(conn)
    posts = repo.all_posts(conn)
    total = 0
    for i, post in enumerate(posts, 1):
        matches = engine.match(post["title"], post["content"])
        repo.replace_mentions_for_post(
            conn,
            post["id"],
            [
                {
                    "symbol": m.symbol,
                    "match_type": m.match_type,
                    "confidence": m.confidence,
                    "in_title": m.in_title,
                    "evidence": m.evidence,
                }
                for m in matches
            ],
        )
        total += len(matches)
        if i % 500 == 0:
            conn.commit()
    conn.commit()
    return {"posts": len(posts), "mentions": total}
