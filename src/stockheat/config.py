"""全域設定：路徑、採集參數、計分權重。

所有可調參數集中在此，pipeline 與 UI 都從這裡讀，避免魔術數字散落各處。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("STOCKHEAT_DATA_DIR", PROJECT_ROOT / "data"))
DB_PATH = Path(os.environ.get("STOCKHEAT_DB", DATA_DIR / "stockheat.db"))
CACHE_DIR = DATA_DIR / "cache"
LOG_DIR = DATA_DIR / "logs"


@dataclass(frozen=True)
class PttConfig:
    board: str = "Stock"
    base_url: str = "https://www.ptt.cc"
    # 對站方友善的節奏：並發 3、全域每 0.4 秒一次請求。
    concurrency: int = 3
    request_interval: float = 0.4
    timeout: float = 20.0
    max_retries: int = 3
    # 索引頁往回翻的上限，避免解析異常時無限往回爬。
    max_index_pages: int = 800
    # 最近幾天的文章一律重抓。推文會持續累積，不重抓的話當天互動量會被低估。
    refresh_days: int = 3


@dataclass(frozen=True)
class NewsConfig:
    request_interval: float = 1.0
    timeout: float = 20.0
    max_items_per_symbol: int = 50


@dataclass(frozen=True)
class ScoringConfig:
    """熱度與情緒的計分參數。

    熱度刻意輸出兩個獨立指標而非單一分數：
      heat_score  當日全市場百分位（0-100），回答「今天排第幾」
      z_score     相對自身 30 日基準的標準差倍數，回答「比平常熱多少」
    真正的訊號在 z_score；heat_score 只用來排序與顯示量級。
    """

    weight_posts: float = 1.0
    weight_engagement: float = 0.6
    weight_news: float = 0.4
    # 標題命中比內文順帶一提更能代表「整篇在談這檔」。
    title_hit_bonus: float = 0.5

    # 提及超過這個檔數的文章視為彙整文，排除於熱度與情緒之外。
    #
    # PTT Stock 板每個交易日都有「上市外資買賣超排行」這類貼文，一次列出 100 檔
    # 股票的代號與名稱。它們形式上是高信心命中，實質上完全不是討論，卻天天為
    # 大型股墊高基準。實測 30 天資料中這類文章佔了全部提及的 73%。
    # 每篇提及檔數的分佈在 12 附近有明顯斷層，故以此為界。
    listing_post_threshold: int = 12

    # 一篇文章的注意力有限，同時談 6 檔時每檔分到的份量少於專講 1 檔。
    # 以 n^attention_exponent 稀釋，0 為不稀釋、1 為完全均分。
    attention_exponent: float = 0.5

    baseline_days: int = 30
    # 基準期樣本不足時不輸出 z-score，避免用兩天資料算標準差。
    min_baseline_days: int = 7
    zscore_epsilon: float = 0.5

    # 平滑常數讓「推 1 噓 0」不等同於「推 100 噓 0」。
    sentiment_smoothing: float = 5.0
    # 提及數低於此值時，情緒標記為「樣本不足」。
    sentiment_min_mentions: int = 3
    weight_pushratio: float = 0.65
    weight_lexicon: float = 0.35


@dataclass(frozen=True)
class TrendsConfig:
    """Google Trends 預設關閉。

    pytrends 已於 2025 年 4 月封存，替代品 trendspyg 需要 Chrome 且極易觸發 429，
    無法涵蓋全市場，因此僅對自選清單與當日熱度前 N 名執行。
    """

    enabled: bool = False
    top_n: int = 20
    geo: str = "TW"
    timeframe: str = "today 3-m"
    # 每組共用的錨定關鍵字，用來把多組 0-100 相對值校準到同一尺度。
    anchor_keyword: str = "台積電"
    group_size: int = 5


@dataclass(frozen=True)
class Settings:
    backfill_days: int = 30
    ptt: PttConfig = field(default_factory=PttConfig)
    news: NewsConfig = field(default_factory=NewsConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    trends: TrendsConfig = field(default_factory=TrendsConfig)


settings = Settings()


def ensure_dirs() -> None:
    for path in (DATA_DIR, CACHE_DIR, LOG_DIR, DB_PATH.parent):
        path.mkdir(parents=True, exist_ok=True)
