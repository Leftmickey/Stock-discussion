"""標的主檔的名稱正規化、別名衍生與證券分類。"""

import pytest

from stockheat.universe.normalize import (
    CONTEXT_CODE,
    CONTEXT_NEARBY,
    CONTEXT_NONE,
    Alias,
    build_aliases,
    classify_security,
    clean_name,
    company_core,
    derive_long_aliases,
    derive_prefix_alias,
    resolve_collisions,
)

GENERIC = frozenset({"世界", "創意", "南亞", "數字"})


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("國巨*", "國巨"), ("臻鼎-KY", "臻鼎"), ("世界健身-KY", "世界健身"), ("台積電", "台積電")],
)
def test_clean_name_strips_exchange_suffixes(raw, expected):
    assert clean_name(raw) == expected


def test_company_core_strips_legal_form():
    assert company_core("台灣積體電路製造股份有限公司") == "台灣積體電路製造"
    assert company_core("金像電子(股)公司") == "金像電子"


@pytest.mark.parametrize(
    ("full_name", "short", "expected"),
    [
        # 公司全名是解開通用詞歧義的關鍵：「世界」查不出東西，「世界先進」可以。
        ("世界先進積體電路股份有限公司", "世界", "世界先進"),
        ("創意電子股份有限公司", "創意", "創意電子"),
        ("高力熱處理工業股份有限公司", "高力", "高力熱處理"),
        ("聯亞光電工業股份有限公司", "聯亞", "聯亞光電"),
    ],
)
def test_long_alias_resolves_generic_short_name(full_name, short, expected):
    assert expected in derive_long_aliases(company_core(full_name), short)


def test_long_alias_requires_short_name_as_prefix():
    """簡稱與全名無關時不可硬湊，否則會張冠李戴。"""
    assert derive_long_aliases("南亞電路板", "南電") == []


@pytest.mark.parametrize(
    ("short", "expected"),
    [("日月光投控", "日月光"), ("台積電", "台積"), ("華邦電", "華邦"), ("南電", None)],
)
def test_prefix_alias(short, expected):
    assert derive_prefix_alias(short) == expected


def test_build_aliases_levels():
    aliases = {
        a.alias: a.requires_context
        for a in build_aliases("5347", "世界", "世界先進積體電路股份有限公司", generic_names=GENERIC)
    }
    assert aliases["世界先進"] == CONTEXT_NONE
    assert aliases["世界"] == CONTEXT_CODE, "通用詞必須要有代號佐證"
    assert aliases["5347"] == CONTEXT_NEARBY, "純數字代號會撞年份，需要語境"


def test_resolve_collisions_downgrades_shared_alias():
    """同一個名稱指向兩家公司時，它就不足以單獨識別任何一家。"""
    aliases = [
        Alias("1303", "南亞", "short", CONTEXT_NEARBY),
        Alias("2408", "南亞", "short", CONTEXT_NEARBY),
        Alias("2330", "台積電", "short", CONTEXT_NONE),
    ]
    resolved = {(a.symbol, a.alias): a.requires_context for a in resolve_collisions(aliases)}
    assert resolved[("1303", "南亞")] == CONTEXT_CODE
    assert resolved[("2408", "南亞")] == CONTEXT_CODE
    assert resolved[("2330", "台積電")] == CONTEXT_NONE


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("2330", "stock"),
        ("0050", "etf"),
        ("00878", "etf"),
        ("006201", "etf"),
        ("00679B", "etf"),
        ("00400A", "etf"),
        ("2887Z1", "preferred"),
        ("1101B", "preferred"),
        ("01001T", "reit"),
        ("910322", "tdr"),
        # 權證有純數字與認售字尾兩種寫法，漏掉任一種都會讓搜尋被洗版。
        ("715001", "warrant"),
        ("72713U", "warrant"),
        ("73007U", "warrant"),
    ],
)
def test_classify_security(code, expected):
    assert classify_security(code) == expected
