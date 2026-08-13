"""內建資源檔（詞典、通用詞清單、預設自選）。以模組層快取，只讀一次。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

RESOURCE_DIR = Path(__file__).parent

# 使用者自行補充的通用詞。放在資料目錄而非套件內，套件更新不會覆蓋。
USER_GENERIC_FILE = "generic_names_user.yaml"


def _load_yaml(name: str) -> dict[str, Any]:
    return yaml.safe_load((RESOURCE_DIR / name).read_text(encoding="utf-8")) or {}


def user_generic_path() -> Path:
    from stockheat.config import DATA_DIR

    return DATA_DIR / USER_GENERIC_FILE


def load_user_generic_names() -> list[str]:
    path = user_generic_path()
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return list(data.get("generic_names", []))


def add_user_generic_name(name: str) -> bool:
    """把誤判的別名加入使用者清單。回傳是否為新增（已存在則為 False）。"""
    builtin = _load_yaml("generic_names.yaml").get("generic_names", [])
    existing = load_user_generic_names()
    if name in existing or name in builtin:
        return False
    existing.append(name)
    path = user_generic_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump({"generic_names": sorted(existing)}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    load_generic_names.cache_clear()
    return True


@lru_cache(maxsize=1)
def load_generic_names() -> frozenset[str]:
    builtin = _load_yaml("generic_names.yaml").get("generic_names", [])
    return frozenset(builtin) | frozenset(load_user_generic_names())


@lru_cache(maxsize=1)
def load_lexicon() -> dict[str, Any]:
    data = _load_yaml("lexicon.yaml")
    return {
        "context_tokens": frozenset(data.get("context_tokens", [])),
        "bullish": dict(data.get("bullish", {})),
        "bearish": dict(data.get("bearish", {})),
        "negations": tuple(data.get("negations", [])),
        "title_tags": data.get("title_tags", {}),
    }


@lru_cache(maxsize=1)
def load_default_watchlist() -> tuple[str, ...]:
    rows = _load_yaml("watchlist.yaml").get("watchlist", [])
    return tuple(str(r["symbol"]) for r in rows)
