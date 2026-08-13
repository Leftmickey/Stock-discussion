-- 台股熱度追蹤器資料表
--
-- 設計原則：原始層（posts / comments / mentions / news / trends_values）永久保留，
-- 聚合層（daily_metrics / heat_scores）每次計分整批重建。
-- 計分與消歧規則一定會反覆調整，留著原始層才不必重爬。

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------- 標的主檔

CREATE TABLE IF NOT EXISTS stocks (
    symbol        TEXT PRIMARY KEY,          -- 股票代號，如 2330
    name          TEXT NOT NULL,             -- 原始名稱（保留 * 與 -KY 等後綴）
    clean_name    TEXT NOT NULL,             -- 去除後綴的比對用名稱
    market        TEXT NOT NULL,             -- TWSE 上市 / TPEX 上櫃
    security_type TEXT NOT NULL DEFAULT 'stock',  -- stock / etf / preferred / reit / tdr
    is_active     INTEGER NOT NULL DEFAULT 1,
    updated_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_stocks_clean_name ON stocks (clean_name);

-- 別名表。requires_context 標定需要多強的佐證才採信：
--   0 專有名稱，單獨命中即可
--   1 需鄰近有金融語境詞
--   2 通用詞，需同篇出現該股代號
CREATE TABLE IF NOT EXISTS aliases (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol           TEXT NOT NULL REFERENCES stocks(symbol) ON DELETE CASCADE,
    alias            TEXT NOT NULL,
    alias_type       TEXT NOT NULL,          -- code / name / short / manual
    requires_context INTEGER NOT NULL DEFAULT 0,
    UNIQUE (symbol, alias)
);

CREATE INDEX IF NOT EXISTS idx_aliases_alias ON aliases (alias);

-- ---------------------------------------------------------------- 原始文本

CREATE TABLE IF NOT EXISTS posts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source        TEXT NOT NULL,             -- ptt
    source_id     TEXT NOT NULL,             -- PTT 文章 ID，如 M.1234567890.A.ABC
    board         TEXT,
    title         TEXT NOT NULL,
    author        TEXT,
    url           TEXT NOT NULL,
    posted_at     TEXT,                      -- ISO8601（台北時間）
    push_count    INTEGER NOT NULL DEFAULT 0,
    boo_count     INTEGER NOT NULL DEFAULT 0,
    neutral_count INTEGER NOT NULL DEFAULT 0,
    content       TEXT,
    sentiment     REAL,                      -- 單篇情緒 -1~1，計分階段回填
    fetched_at    TEXT NOT NULL,
    UNIQUE (source, source_id)
);

CREATE INDEX IF NOT EXISTS idx_posts_posted_at ON posts (posted_at);

-- 推文明細。情緒主訊號來自推噓比，逐則保留才能重算與稽核。
CREATE TABLE IF NOT EXISTS comments (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    seq     INTEGER NOT NULL,
    tag     TEXT NOT NULL,                   -- push / boo / neutral
    author  TEXT,
    text    TEXT,
    UNIQUE (post_id, seq)
);

CREATE TABLE IF NOT EXISTS news (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol       TEXT NOT NULL REFERENCES stocks(symbol) ON DELETE CASCADE,
    title        TEXT NOT NULL,
    url          TEXT NOT NULL,
    publisher    TEXT,
    published_at TEXT,
    fetched_at   TEXT NOT NULL,
    UNIQUE (symbol, url)
);

CREATE INDEX IF NOT EXISTS idx_news_symbol_date ON news (symbol, published_at);

-- Google Trends 搜尋熱度。獨立成表而不放進 daily_metrics，
-- 因為後者屬於可隨時砍掉重算的聚合層，而這是實際採集回來的原始資料。
CREATE TABLE IF NOT EXISTS trends_values (
    date       TEXT NOT NULL,
    symbol     TEXT NOT NULL REFERENCES stocks(symbol) ON DELETE CASCADE,
    value      REAL NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (date, symbol)
);

-- ---------------------------------------------------------------- 匹配結果

CREATE TABLE IF NOT EXISTS mentions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id    INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    symbol     TEXT NOT NULL REFERENCES stocks(symbol) ON DELETE CASCADE,
    match_type TEXT NOT NULL,
    confidence REAL NOT NULL,
    in_title   INTEGER NOT NULL DEFAULT 0,
    evidence   TEXT,
    UNIQUE (post_id, symbol)
);

CREATE INDEX IF NOT EXISTS idx_mentions_symbol ON mentions (symbol);
CREATE INDEX IF NOT EXISTS idx_mentions_post ON mentions (post_id);

-- ---------------------------------------------------------------- 行情

CREATE TABLE IF NOT EXISTS prices (
    date   TEXT NOT NULL,
    symbol TEXT NOT NULL REFERENCES stocks(symbol) ON DELETE CASCADE,
    open   REAL,
    high   REAL,
    low    REAL,
    close  REAL,
    change REAL,
    volume INTEGER,
    PRIMARY KEY (date, symbol)
);

-- ---------------------------------------------------------------- 聚合層
--
-- 以下兩張表完全由原始層推導，compute_scores 每次執行都整批重建。
-- 只做 UPSERT 不刪除會留下孤兒列：例如週末貼文改歸到下一個交易日之後，
-- 舊的週末日期仍會留在表裡，儀表板上就會出現兩筆內容相同的日期。

CREATE TABLE IF NOT EXISTS daily_metrics (
    date             TEXT NOT NULL,
    symbol           TEXT NOT NULL,
    post_count       INTEGER NOT NULL DEFAULT 0,
    title_post_count INTEGER NOT NULL DEFAULT 0,
    push_sum         INTEGER NOT NULL DEFAULT 0,
    boo_sum          INTEGER NOT NULL DEFAULT 0,
    comment_sum      INTEGER NOT NULL DEFAULT 0,
    news_count       INTEGER NOT NULL DEFAULT 0,
    trends_value     REAL,
    raw_heat         REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (date, symbol)
);

CREATE INDEX IF NOT EXISTS idx_daily_metrics_date ON daily_metrics (date);

CREATE TABLE IF NOT EXISTS heat_scores (
    date            TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    raw_heat        REAL NOT NULL,
    heat_score      REAL NOT NULL,           -- 當日全市場百分位 0-100
    z_score         REAL,                    -- 相對自身 30 日基準；樣本不足為 NULL
    rank            INTEGER,
    prev_rank       INTEGER,
    sentiment       REAL,                    -- -1 ~ +1
    sentiment_label TEXT,
    mention_count   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (date, symbol)
);

CREATE INDEX IF NOT EXISTS idx_heat_scores_date ON heat_scores (date);

-- ---------------------------------------------------------------- 運作狀態

CREATE TABLE IF NOT EXISTS fetch_log (
    source     TEXT NOT NULL,
    target     TEXT NOT NULL,
    cursor     TEXT,
    status     TEXT NOT NULL,
    message    TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (source, target)
);

CREATE TABLE IF NOT EXISTS watchlist (
    symbol     TEXT PRIMARY KEY,
    sort_order INTEGER NOT NULL DEFAULT 0,
    added_at   TEXT NOT NULL
);

-- 稽核頁的人工回饋：標記誤判，供日後調整消歧規則。
CREATE TABLE IF NOT EXISTS match_feedback (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id    INTEGER NOT NULL,
    symbol     TEXT NOT NULL,
    verdict    TEXT NOT NULL,                -- correct / wrong
    note       TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (post_id, symbol)
);
