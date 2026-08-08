from src.search import normalize_query, search_stocks, score_stock


STOCKS = [
    {
        "id": 1,
        "code": "2327",
        "name": "國巨",
        "aliases": ["國巨*", "Yageo", "國巨", "2327"],
    },
    {
        "id": 2,
        "code": "4958",
        "name": "臻鼎-KY",
        "aliases": ["臻鼎", "臻鼎KY", "4958", "臻鼎-KY"],
    },
    {
        "id": 3,
        "code": "2330",
        "name": "台積電",
        "aliases": ["台積", "TSMC", "2330"],
    },
]


def test_normalize_strips_star_and_ky():
    assert normalize_query("國巨*") == "國巨"
    assert "臻鼎" in normalize_query("臻鼎-KY")


def test_search_by_alias_and_code():
    assert search_stocks(STOCKS, "國巨")[0]["code"] == "2327"
    assert search_stocks(STOCKS, "2327")[0]["name"] == "國巨"
    assert search_stocks(STOCKS, "臻鼎")[0]["code"] == "4958"
    assert search_stocks(STOCKS, "台積")[0]["code"] == "2330"


def test_exact_code_scores_highest():
    assert score_stock("2330", STOCKS[2]) == 100.0
