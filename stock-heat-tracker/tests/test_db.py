from pathlib import Path

from src.db import ensure_ready, list_stocks, seed_stocks


def test_seed_and_aliases(tmp_path: Path):
    db_path = tmp_path / "test.db"
    conn = ensure_ready(db_path)
    stocks = list_stocks(conn)
    assert len(stocks) == 30
    guo = next(s for s in stocks if s["code"] == "2327")
    assert "國巨" in guo["aliases"]
    zhen = next(s for s in stocks if s["code"] == "4958")
    assert any("臻鼎" in a for a in zhen["aliases"])
    # 第二次 seed 不重複插入
    assert seed_stocks(conn) == 0
