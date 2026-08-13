"""熱度與情緒計分。

z-score 是整個系統的主指標，這裡驗證幾個容易寫錯又不會報錯的地方：
基準要含零值日、要排除週末、彙整文要濾掉。
"""

import pandas as pd
import pytest

from stockheat.config import ScoringConfig
from stockheat.scoring.heat import drop_listing_posts, to_session_date
from stockheat.scoring.sentiment import label, lexicon_sentiment, post_sentiment


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-08-07", "2026-08-07"),  # 週五維持原日
        ("2026-08-08", "2026-08-10"),  # 週六 -> 下週一
        ("2026-08-09", "2026-08-10"),  # 週日 -> 下週一
        ("2026-08-10", "2026-08-10"),  # 週一維持原日
    ],
)
def test_weekend_posts_map_to_next_trading_day(raw, expected):
    assert to_session_date(pd.Series([raw])).iloc[0] == expected


def test_drop_listing_posts():
    """買賣超排行這類一次列 100 檔的貼文不是討論，不能計入熱度。"""
    cfg = ScoringConfig(listing_post_threshold=5)
    rows = [{"post_id": 1, "symbol": s} for s in ["2330", "2454"]]
    rows += [{"post_id": 2, "symbol": f"1{i:03d}"} for i in range(8)]

    kept, dropped = drop_listing_posts(pd.DataFrame(rows), cfg)
    assert dropped == 1
    assert set(kept["post_id"]) == {1}
    assert kept["symbols_in_post"].tolist() == [2, 2]


def test_attention_is_split_across_symbols():
    """同時談 4 檔時，每檔分到的份量應少於專講 1 檔。"""
    cfg = ScoringConfig()
    frame = pd.DataFrame(
        [{"post_id": 1, "symbol": "2330"}]
        + [{"post_id": 2, "symbol": s} for s in ["1101", "1102", "1103", "1104"]]
    )
    kept, _ = drop_listing_posts(frame, cfg)
    solo = kept[kept.post_id == 1]["symbols_in_post"].iloc[0]
    shared = kept[kept.post_id == 2]["symbols_in_post"].iloc[0]
    assert solo**cfg.attention_exponent < shared**cfg.attention_exponent


# ----------------------------------------------------------------- 情緒


def test_push_ratio_drives_sentiment():
    assert post_sentiment("盤後心得", "沒什麼特別的", push_count=50, boo_count=2).score > 0.3
    assert post_sentiment("盤後心得", "沒什麼特別的", push_count=2, boo_count=50).score < -0.3


def test_small_sample_is_smoothed():
    """推 1 噓 0 不該等同推 100 噓 0。"""
    weak = post_sentiment("標題", "", push_count=1, boo_count=0)
    strong = post_sentiment("標題", "", push_count=100, boo_count=0)
    assert weak.push_ratio < strong.push_ratio / 3


def test_taiwan_market_slang():
    """通用中文情感模型會把這些詞判反，所以才要自建詞典。"""
    assert lexicon_sentiment("今天軋空 直接噴出 起飛")[0] > 0
    assert lexicon_sentiment("跌破月線 住套房 畢業了")[0] < 0


def test_negation_flips_polarity():
    assert lexicon_sentiment("看好這檔")[0] > 0 > lexicon_sentiment("不看好這檔")[0]


@pytest.mark.parametrize(
    ("score", "mentions", "expected"),
    [
        (0.8, 10, "看多"),
        (0.2, 10, "偏多"),
        (0.0, 10, "中性"),
        (-0.2, 10, "偏空"),
        (-0.8, 10, "看空"),
        # 樣本太少時不給假精確的判斷
        (0.8, 1, "樣本不足"),
        (None, 10, "樣本不足"),
    ],
)
def test_sentiment_label(score, mentions, expected):
    assert label(score, mentions) == expected
