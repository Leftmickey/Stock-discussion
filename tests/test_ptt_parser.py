"""PTT HTML 解析。

PTT 偶爾會改版，改版時這組測試會先失敗，比從熱度數字反推容易定位得多。
"""

from pathlib import Path

import pytest

from stockheat.collectors import ptt_parser as parser

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def index_html() -> str:
    return (FIXTURES / "ptt_index.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def article_html() -> str:
    return (FIXTURES / "ptt_article.html").read_text(encoding="utf-8")


def test_index_skips_deleted_and_pinned(index_html):
    entries = parser.parse_index(index_html)
    ids = [e.source_id for e in entries]
    assert len(entries) == 3, "已刪除文章與分隔線以下的置底公告都不該計入"
    assert "M.1600000000.A.Z99" not in ids, "置底公告天天出現，會製造穩定的假熱度"


def test_index_extracts_epoch_from_url(index_html):
    """有了 epoch 就能在不下載文章的前提下判斷它是否落在時間窗內。"""
    entries = parser.parse_index(index_html)
    assert entries[0].epoch == 1754500000
    assert entries[0].url == "https://www.ptt.cc/bbs/Stock/M.1754500000.A.A01.html"


@pytest.mark.parametrize(
    ("text", "expected"),
    [("26", 26), ("爆", 100), ("X3", -30), ("XX", -100), ("", 0), (None, 0)],
)
def test_parse_nrec(text, expected):
    assert parser.parse_nrec(text) == expected


def test_parse_prev_page_number(index_html):
    assert parser.parse_prev_page_number(index_html) == 7421


def test_article_metadata(article_html):
    article = parser.parse_article(
        article_html, "https://www.ptt.cc/bbs/Stock/M.1754500000.A.A01.html"
    )
    assert article is not None
    assert article.title == "[標的] 2330 台積電 多"
    assert article.author == "investor01"
    assert article.board == "Stock"
    assert article.source_id == "M.1754500000.A.A01"


def test_article_time_comes_from_url_epoch(article_html):
    """時間欄位可被發文者偽造，URL 裡的 epoch 由伺服器寫入，較可信。"""
    article = parser.parse_article(
        article_html, "https://www.ptt.cc/bbs/Stock/M.1754500000.A.A01.html"
    )
    assert int(article.posted_at.timestamp()) == 1754500000


def test_article_comments_classified(article_html):
    article = parser.parse_article(
        article_html, "https://www.ptt.cc/bbs/Stock/M.1754500000.A.A01.html"
    )
    assert (article.push_count, article.boo_count, article.neutral_count) == (2, 1, 1)
    assert article.comments[0]["author"] == "bull001"
    assert "看好" in article.comments[0]["text"]


def test_article_content_excludes_system_lines_and_comments(article_html):
    article = parser.parse_article(
        article_html, "https://www.ptt.cc/bbs/Stock/M.1754500000.A.A01.html"
    )
    assert "CoWoS" in article.content
    assert "發信站" not in article.content
    assert "bull001" not in article.content


def test_parse_article_returns_none_on_garbage():
    assert parser.parse_article("<html><body>404</body></html>", "http://x") is None


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("[標的] 2330 台積電 多", "標的"),
        ("Re: [標的] 2330 台積電", "標的"),
        ("Re: Re: [新聞] 某某", "新聞"),
        ("沒有標籤的標題", None),
    ],
)
def test_title_tag(title, expected):
    assert parser.title_tag(title) == expected
