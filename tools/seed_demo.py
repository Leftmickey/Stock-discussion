"""產生示範資料，寫入獨立的 data/demo.db。

用途有二：
  1. PTT 回補需要十幾分鐘，先用示範資料就能確認儀表板長什麼樣、要不要調整
  2. 開發時驗證計分邏輯，不必依賴外部網站

文章內容是合成的，但刻意複製了真實 PTT 貼文的結構特徵：標題分類標籤、
代號與名稱的寫法、推噓分佈，以及兩類會考驗系統的貼文——
會觸發誤判的干擾文，以及一次列出上百檔的買賣超排行彙整文。

    python tools/seed_demo.py
    STOCKHEAT_DB=data/demo.db streamlit run app/dashboard.py
"""

from __future__ import annotations

import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stockheat.config import TAIPEI  # noqa: E402
from stockheat.matching import load_engine, rematch_all  # noqa: E402
from stockheat.scoring import compute_scores  # noqa: E402
from stockheat.storage import db, repo  # noqa: E402
from stockheat.universe import refresh_universe  # noqa: E402

DEMO_DB = Path(__file__).resolve().parents[1] / "data" / "demo.db"

# (代號, 名稱, 基準每日文章數, 是否在最後一天製造爆量事件)
# 小於 1 的基準值代表「平常好幾天才被提到一次」的冷門股，
# 異常竄升榜要抓的就是這種標的突然被大量討論。
PROFILES = [
    ("2330", "台積電", 14, False),
    ("2317", "鴻海", 6, False),
    ("2454", "聯發科", 5, False),
    ("2382", "廣達", 4, False),
    ("3017", "奇鋐", 3, False),
    ("2345", "智邦", 3, False),
    ("2303", "聯電", 3, False),
    ("2891", "中信金", 2, False),
    ("6223", "旺矽", 1, False),
    ("5347", "世界先進", 0.5, False),
    ("3443", "創意電子", 0.4, False),
    ("8046", "南電", 0.6, False),
    ("7769", "鴻勁", 0.3, True),
    ("6515", "穎崴", 0.4, True),
    ("2408", "南亞科", 1.5, True),
]

BULL_BODIES = [
    "法說會展望上修，訂單能見度看到明年，先進製程產能吃緊。",
    "外資連續買超，站上季線，成交量溫和放大，續強格局。",
    "營收創新高，超預期，目標價調升，法人買超。",
    "產能滿載，報價調漲，毛利率有機會續揚，我加碼了。",
]
BEAR_BODIES = [
    "庫存去化不如預期，法人賣超，跌破月線，我認賠停損了。",
    "報價鬆動，砍單傳聞不斷，營收下修，感覺要住套房。",
    "高檔爆量，主力倒貨，別接刀，我先下車。",
    "毛利率衰退，展望保守，跌停一根，畢業了。",
]
NEUTRAL_BODIES = [
    "想請問大家怎麼看這檔的評價，本益比目前算合理嗎？",
    "整理一下最近的營收數字，提供板友參考，沒有推薦之意。",
    "盤後籌碼觀察，投信小買，自營商小賣，量能持平。",
]

# 干擾文：正確的系統應該一檔都不比對出來。
# 每一則都對應一種真實發生過的誤判。
NOISE_POSTS = [
    ("[閒聊] 這個世界真的很不公平", "每天上班都好累，只想早點財富自由，跟大家分享心情。"),
    ("[請益] 2026 年的總體經濟怎麼看", "想請教大家對明年的看法，2026 年會不會進入衰退循環？"),
    ("[心得] 資料日期 20260807 的統計", "整理了一份市場成交統計，日期是 20260807，給大家參考。"),
    ("[新聞] SK海力士 ADR 選擇權登場", "工商時報報導，SK海力士的散戶交易熱度創高，股價續強。"),
    ("[閒聊] 作業系統又更新了", "公司的供應鏈系統昨天大改版，整合晶片相關的流程都變了。"),
    ("[心得] 盤中閒聊", "大盤衝到 1783 點附近，成交量放大，個股表現分歧。"),
]


def build_posts(days: int, rng: random.Random) -> list[dict]:
    now = datetime.now(TAIPEI).replace(hour=13, minute=0, second=0, microsecond=0)
    posts: list[dict] = []
    counter = 0

    def make(ts: datetime, title: str, body: str, push: int, boo: int, prefix: str = "") -> dict:
        nonlocal counter
        counter += 1
        sid = f"M.{int(ts.timestamp())}.A.{prefix}{counter:04X}"
        return {
            "source": "ptt",
            "source_id": sid,
            "board": "Stock",
            "title": title,
            "author": f"demo{rng.randint(1, 400):03d}",
            "url": f"https://www.ptt.cc/bbs/Stock/{sid}.html",
            "posted_at": ts.isoformat(),
            "push_count": push,
            "boo_count": boo,
            "neutral_count": rng.randint(0, 15),
            "content": body,
        }

    for day_offset in range(days, -1, -1):
        day = now - timedelta(days=day_offset)
        # 爆量只放在最後一天。若連續多天爆量，第二天起就會被自己的基準吸收，
        # 異常倍數反而變小——這正是 z-score 該有的行為。
        spike = day_offset == 0

        for symbol, name, base, has_spike in PROFILES:
            if spike and has_spike:
                count = rng.randint(22, 32)
            elif base < 1:
                count = 1 if rng.random() < base else 0  # 冷門股大多數日子沒人提
            else:
                count = max(0, int(rng.gauss(base, max(1, base * 0.35))))

            for _ in range(count):
                weights = [0.7, 0.15, 0.15] if (spike and has_spike) else [0.45, 0.3, 0.25]
                mood = rng.choices(["bull", "bear", "neutral"], weights=weights)[0]
                if mood == "bull":
                    tag, body = "標的", rng.choice(BULL_BODIES)
                    push, boo = rng.randint(8, 90), rng.randint(0, 6)
                elif mood == "bear":
                    tag, body = "標的", rng.choice(BEAR_BODIES)
                    push, boo = rng.randint(2, 25), rng.randint(5, 40)
                else:
                    tag = rng.choice(["請益", "新聞", "心得"])
                    body = rng.choice(NEUTRAL_BODIES)
                    push, boo = rng.randint(0, 20), rng.randint(0, 5)

                ts = day - timedelta(minutes=rng.randint(0, 600))
                posts.append(
                    make(
                        ts,
                        f"[{tag}] {symbol} {name}",
                        f"標的：{symbol} {name}\n\n{body}",
                        push,
                        boo,
                    )
                )

        for title, body in NOISE_POSTS:
            if rng.random() < 0.5:
                continue
            ts = day - timedelta(minutes=rng.randint(0, 600))
            posts.append(make(ts, title, body, rng.randint(0, 12), rng.randint(0, 4), "N"))

        # 每個平日一篇買賣超排行，模擬真實板上天天出現的彙整文。
        if day.weekday() < 5:
            listed = "\n".join(f"{s}　　{n}　　{rng.randint(-90000, 90000)}" for s, n, _, _ in PROFILES)
            ts = day.replace(hour=17)
            posts.append(
                make(
                    ts,
                    f"[情報] {day:%m%d} 上市外資買賣超排行",
                    f"外資買賣超排行如下：\n{listed}",
                    rng.randint(0, 20),
                    rng.randint(0, 3),
                    "L",
                )
            )
    return posts


def main() -> int:
    rng = random.Random(20260808)
    DEMO_DB.parent.mkdir(parents=True, exist_ok=True)
    DEMO_DB.unlink(missing_ok=True)

    conn = db.init_db(DEMO_DB)
    print(f"示範資料庫：{DEMO_DB}")

    print("抓取全市場標的主檔…")
    print(" ", refresh_universe(conn))

    posts = build_posts(days=32, rng=rng)
    print(f"寫入 {len(posts)} 篇合成文章…")
    for p in posts:
        repo.upsert_post(conn, p)
    conn.commit()

    print("比對標的…")
    print(" ", rematch_all(conn, load_engine(conn)))

    print("計算熱度與情緒…")
    print(" ", compute_scores(conn))

    latest = repo.latest_score_date(conn)
    print(f"\n最新資料日：{latest}")
    print("\n異常竄升榜：")
    print(f"  {'代號':<7}{'名稱':<9}{'排名':>4}{'熱度':>7}{'異常倍數':>9}  情緒")
    for r in conn.execute(
        """
        SELECT h.symbol, s.name, h.rank, h.heat_score, h.z_score,
               h.sentiment_label, h.mention_count
        FROM heat_scores h JOIN stocks s ON s.symbol = h.symbol
        WHERE h.date = ? AND h.mention_count >= 3
        ORDER BY h.z_score DESC LIMIT 8
        """,
        (latest,),
    ):
        z = f"{r['z_score']:+.2f}" if r["z_score"] is not None else "—"
        print(
            f"  {r['symbol']:<8}{r['name']:<10}{r['rank']:>3}{r['heat_score']:>7.0f}{z:>9}  "
            f"{r['sentiment_label']}（{r['mention_count']} 則）"
        )

    noise = conn.execute(
        """
        SELECT COUNT(*) FROM mentions m JOIN posts p ON p.id = m.post_id
        WHERE p.author LIKE 'noise%' OR p.source_id LIKE '%.A.N%'
        """
    ).fetchone()[0]
    print(f"\n干擾文誤判數：{noise}（應為 0）")

    print("\n啟動儀表板：")
    print("  STOCKHEAT_DB=data/demo.db streamlit run app/dashboard.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
