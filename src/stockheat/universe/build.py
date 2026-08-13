"""建立／更新標的主檔與別名表。"""

from __future__ import annotations

import logging
import sqlite3

from stockheat.resources import load_default_watchlist, load_generic_names
from stockheat.storage import repo
from stockheat.universe.normalize import build_aliases, clean_name, resolve_collisions
from stockheat.universe.sources import fetch_all

logger = logging.getLogger(__name__)


def refresh_universe(conn: sqlite3.Connection, seed_watchlist: bool = True) -> dict[str, int]:
    securities, quotes = fetch_all()
    if not securities:
        raise RuntimeError("無法取得任何標的資料，請確認網路或交易所 API 狀態")

    repo.upsert_stocks(
        conn,
        (
            {
                "symbol": s.symbol,
                "name": s.name,
                "clean_name": clean_name(s.name),
                "market": s.market,
                "security_type": s.security_type,
                "is_active": 1,
            }
            for s in securities
        ),
    )

    generic = load_generic_names()
    aliases = []
    for sec in securities:
        aliases.extend(build_aliases(sec.symbol, sec.name, sec.full_name, generic_names=generic))
    aliases = resolve_collisions(aliases)

    repo.replace_aliases(
        conn,
        (
            {
                "symbol": a.symbol,
                "alias": a.alias,
                "alias_type": a.alias_type,
                "requires_context": a.requires_context,
            }
            for a in aliases
        ),
    )

    repo.upsert_prices(
        conn,
        (
            {
                "date": q.date.isoformat(),
                "symbol": q.symbol,
                "open": q.open,
                "high": q.high,
                "low": q.low,
                "close": q.close,
                "change": q.change,
                "volume": q.volume,
            }
            for q in quotes
        ),
    )

    if seed_watchlist and not repo.get_watchlist(conn):
        known = {s.symbol for s in securities}
        missing = [s for s in load_default_watchlist() if s not in known]
        if missing:
            logger.warning("預設自選中有 %s 未出現在交易所主檔，已略過", missing)
        repo.set_watchlist(conn, [s for s in load_default_watchlist() if s in known])

    conn.commit()
    stats = {"securities": len(securities), "aliases": len(aliases), "quotes": len(quotes)}
    logger.info("標的主檔更新完成：%s", stats)
    return stats
