"""比對引擎的消歧行為。

每個案例都對應一種在台股文本裡真實發生過的誤判，
所以測的是「該不該算」而不只是「有沒有找到」。
"""

import pytest

from stockheat.matching.engine import MatchEngine
from stockheat.universe.normalize import CONTEXT_CODE, CONTEXT_NEARBY, CONTEXT_NONE

# (symbol, alias, alias_type, requires_context)
ALIASES = [
    ("2330", "2330", "code", CONTEXT_NEARBY),
    ("2330", "台積電", "short", CONTEXT_NONE),
    ("2330", "台積", "short", CONTEXT_NEARBY),
    ("5347", "5347", "code", CONTEXT_NEARBY),
    ("5347", "世界", "short", CONTEXT_CODE),
    ("5347", "世界先進", "name", CONTEXT_NONE),
    ("1303", "1303", "code", CONTEXT_NEARBY),
    ("1303", "南亞", "short", CONTEXT_CODE),
    ("2408", "2408", "code", CONTEXT_NEARBY),
    ("2408", "南亞科", "short", CONTEXT_NONE),
    ("2026", "2026", "code", CONTEXT_NEARBY),
    ("2026", "志剛", "short", CONTEXT_NONE),
    ("2059", "2059", "code", CONTEXT_NEARBY),
    ("2059", "川湖", "short", CONTEXT_NONE),
    ("1783", "1783", "code", CONTEXT_NEARBY),
    ("1783", "和康生", "short", CONTEXT_NONE),
    ("7769", "7769", "code", CONTEXT_NEARBY),
    ("7769", "鴻勁", "short", CONTEXT_NONE),
    ("0050", "0050", "code", CONTEXT_NEARBY),
    ("0050", "元大台灣50", "short", CONTEXT_NONE),
]


@pytest.fixture(scope="module")
def engine() -> MatchEngine:
    return MatchEngine(ALIASES)


def symbols(matches) -> set[str]:
    return {m.symbol for m in matches}


def test_title_tag_gives_top_confidence(engine):
    matches = engine.match("[標的] 2330 台積電 多", "先進製程需求強勁，法說會展望上修。")
    hit = next(m for m in matches if m.symbol == "2330")
    assert hit.match_type == "title_tag"
    assert hit.confidence == 1.0
    assert hit.in_title


def test_code_and_name_together(engine):
    matches = engine.match("[新聞] 台廠動態", "7769 鴻勁 今天營收公布，法人買超。")
    assert next(m for m in matches if m.symbol == "7769").match_type == "code_with_name"


def test_year_is_not_treated_as_stock_code(engine):
    """2026 是志剛的真實代號，寫成「2026 年」時必須排除。"""
    matches = engine.match("[請益] 明年展望", "2026 年的資本支出會不會下修？股價會怎麼走？")
    assert "2026" not in symbols(matches)


def test_year_code_still_counts_when_company_is_named(engine):
    matches = engine.match("[標的] 2026 志剛", "志剛 鋼鐵股，2026 今天漲停。")
    assert "2026" in symbols(matches)


def test_date_string_does_not_leak_codes(engine):
    """20260807 這種連續數字不該被切出 2026。"""
    matches = engine.match("[公告] 資料日期 20260807", "本日成交資訊如附表，股價彙整。")
    assert "2026" not in symbols(matches)


def test_longer_name_wins_over_contained_short_name(engine):
    """「南亞科技」裡的「南亞」不該算成 1303 南亞。"""
    matches = engine.match("[標的] 2408 南亞科", "南亞科 記憶體報價上漲，法人買超。")
    assert "2408" in symbols(matches)
    assert "1303" not in symbols(matches)


def test_generic_name_alone_is_rejected(engine):
    """「世界」是日常用語，沒有代號佐證就不能算成 5347。"""
    matches = engine.match("[閒聊] 世界真是不公平", "這個世界就是這樣，股票也是。")
    assert "5347" not in symbols(matches)


def test_generic_name_accepted_with_code(engine):
    matches = engine.match("[標的] 5347 世界", "世界 今天營收公布，站上季線。")
    assert "5347" in symbols(matches)


def test_derived_long_alias_resolves_generic_name(engine):
    """長別名「世界先進」本身就夠明確，不需要代號佐證。"""
    matches = engine.match("[心得] 世界先進今天真的很雷", "世界先進 跌破月線，我停損了。")
    assert next(m for m in matches if m.symbol == "5347").match_type == "name"


def test_short_alias_requires_nearby_context(engine):
    """兩字簡稱「台積」需要鄰近有金融語彙才採計。"""
    assert "2330" not in symbols(
        engine.match("[閒聊] 隨手記", "今天天氣不錯，台積 這兩個字看起來很順眼。")
    )
    assert "2330" in symbols(engine.match("[心得] 盤後", "台積 今天收盤站上季線，成交量放大。"))


def test_bare_stock_code_in_body_is_rejected(engine):
    """內文的四位數多半是股價或指數點位。

    實測 30 天資料顯示，只有裸代號、同篇沒出現公司名稱的命中大多是誤判；
    而在股板裡「鄰近有金融語彙」幾乎必然成立，擋不住。
    """
    matches = engine.match("[閒聊] 盤中閒聊", "大盤衝到 1783 點附近，成交量放大，股價都在漲。")
    assert "1783" not in symbols(matches)


def test_bare_code_in_title_is_accepted(engine):
    """標題裡的代號通常真的在指這檔股票。"""
    matches = engine.match("[情報] 2059 月營收", "營收年增三成，法人買超，成交量放大。")
    assert "2059" in symbols(matches)


def test_bare_etf_code_is_accepted(engine):
    """ETF 幾乎只會被以代號稱呼，沒人寫「元大台灣50」。"""
    matches = engine.match("[心得] 存股", "我每個月定期定額買 0050，配息穩定，殖利率不錯。")
    assert "0050" in symbols(matches)


def test_multiple_symbols_in_one_post(engine):
    matches = engine.match(
        "[標的] 2330 台積電 多",
        "CoWoS 產能吃緊，帶動 7769 鴻勁 與 2408 南亞科 同步受惠，法人買超。",
    )
    assert {"2330", "7769", "2408"} <= symbols(matches)


def test_no_match_returns_empty(engine):
    assert engine.match("[閒聊] 今天午餐吃什麼", "隨便聊聊，沒有提到任何公司。") == []
