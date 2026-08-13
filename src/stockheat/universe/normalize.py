"""股票名稱正規化與別名生成。

全市場約 2,400 檔，光靠交易所給的簡稱去比對網路文本會產生大量誤判，
因為不少簡稱本身就是日常用語（「世界」「創意」「數字」）。這裡做三件事：

1. 從公司全名衍生出高辨識度的長別名。交易所同時提供簡稱與全名，
   「世界」的全名是「世界先進積體電路股份有限公司」，可以自動推出
   「世界先進」這個幾乎不可能誤判的別名。

2. 為每個別名標定信心層級，交給比對層決定要不要額外佐證。

3. 偵測跨公司撞名，把指向多家公司的別名一律降級。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from stockheat.resources import load_generic_names

# 交易所簡稱的後綴標記，比對時要拿掉但顯示時保留。
#   *      公司名稱標記
#   -KY    外國企業來台第一上市
#   -DR    台灣存託憑證
NAME_SUFFIX_RE = re.compile(r"(\*+|-KY|-DR|-U|-N)$", re.IGNORECASE)

# 公司全名的組織型態尾綴，由長到短依序剝除。
LEGAL_SUFFIXES = (
    "股份有限公司",
    "(股)公司",
    "（股）公司",
    "有限公司",
    "公司",
)

# 從全名核心逐層往下剝的業別詞，每剝一層都產生一個候選別名。
#   「世界先進積體電路」→「世界先進」、「聯亞光電工業」→「聯亞光電」
# 剝過頭不要緊：候選必須比簡稱長且以簡稱開頭才會被採用。
BUSINESS_SUFFIXES = (
    "投資控股",
    "金融控股",
    "生物科技",
    "積體電路",
    "半導體",
    "熱處理",
    "控股",
    "工業",
    "實業",
    "企業",
    "集團",
    "國際",
    "開發",
    "建設",
    "生技",
    "製藥",
    "電子",
    "光電",
    "科技",
    "材料",
    "精密",
    "製造",
    "化學",
    "化工",
    "電機",
    "機械",
    "通訊",
    "資訊",
    "電腦",
    "醫療",
    "食品",
    "紡織",
    "鋼鐵",
    "水泥",
    "塑膠",
    "橡膠",
    "航運",
    "銀行",
    "保險",
    "證券",
)

# 交易所簡稱本身的字尾，網路上習慣省略。
#   日月光投控 → 日月光、台積電 → 台積、華邦電 → 華邦
# 剝出來的短形式容易與別家撞名，交給全域撞名偵測統一降級。
SHORT_NAME_SUFFIXES = ("投控", "金控", "控股", "控", "電", "科", "金")

# 別名信心層級
CONTEXT_NONE = 0  # 專有名稱，單獨命中即可採信
CONTEXT_NEARBY = 1  # 需鄰近有金融語境詞
CONTEXT_CODE = 2  # 需同篇出現該股代號，或命中更長的別名

# 進入比對範圍的證券類別。權證、特別股、REIT 與 TDR 數量龐大或鮮少被以名稱討論。
MATCHABLE_TYPES = frozenset({"stock", "etf"})


@dataclass(frozen=True)
class Alias:
    symbol: str
    alias: str
    alias_type: str
    requires_context: int


def clean_name(name: str) -> str:
    """去掉交易所簡稱的後綴標記：國巨* → 國巨、臻鼎-KY → 臻鼎。"""
    out = name.strip()
    while True:
        stripped = NAME_SUFFIX_RE.sub("", out).strip()
        if stripped == out:
            return out
        out = stripped


def company_core(full_name: str | None) -> str | None:
    """從公司全名剝掉組織型態尾綴：台灣積體電路製造股份有限公司 → 台灣積體電路製造。"""
    if not full_name:
        return None
    core = full_name.strip()
    for suffix in LEGAL_SUFFIXES:
        if core.endswith(suffix):
            core = core[: -len(suffix)]
            break
    return core.strip() or None


def derive_long_aliases(core: str | None, short: str) -> list[str]:
    """由公司全名核心推導長別名。

    只保留「以簡稱開頭、且比簡稱更長」的形式。這個條件同時擋掉兩類雜訊：
    改名或簡稱與全名無關的公司（避免張冠李戴），以及過度剝除產生的短詞。
    """
    if not core or not short:
        return []

    candidates: list[str] = []
    if core != short:
        candidates.append(core)

    trimmed = core
    for _ in range(len(BUSINESS_SUFFIXES)):
        for suffix in BUSINESS_SUFFIXES:
            if trimmed.endswith(suffix) and len(trimmed) - len(suffix) >= 2:
                trimmed = trimmed[: -len(suffix)]
                candidates.append(trimmed)
                break
        else:
            break

    out: list[str] = []
    for cand in candidates:
        cand = cand.strip()
        if len(cand) <= len(short) or not cand.startswith(short) or cand in out:
            continue
        out.append(cand)
    return out


def derive_prefix_alias(short: str) -> str | None:
    """剝掉簡稱字尾得到網路慣用寫法：日月光投控 → 日月光。

    只剝一層，且結果至少 2 字，避免「南電」被剝成單字。
    """
    for suffix in SHORT_NAME_SUFFIXES:
        if short.endswith(suffix) and len(short) - len(suffix) >= 2:
            return short[: -len(suffix)]
    return None


def context_level(alias: str, alias_type: str, generic_names: frozenset[str]) -> int:
    """判定別名需要多強的佐證。

    只爬 PTT Stock 板意味著「這篇在談股票」是既定前提，所以語境判斷必須
    比板級更細，看的是命中位置附近有沒有金融語彙。
    """
    if alias_type == "code":
        # 純 4 碼數字會撞到年份（2024/2025/2026 都是真實代號）與價格，
        # 一律要求鄰近語境，另有專門的年份排除規則。
        return CONTEXT_NEARBY
    if alias in generic_names:
        return CONTEXT_CODE
    if len(alias) <= 2:
        return CONTEXT_NEARBY
    return CONTEXT_NONE


def build_aliases(
    symbol: str,
    display_name: str,
    full_name: str | None = None,
    extra: list[str] | None = None,
    generic_names: frozenset[str] | None = None,
) -> list[Alias]:
    """產生單一標的的完整別名集合。"""
    generic = generic_names if generic_names is not None else load_generic_names()
    short = clean_name(display_name)

    out: list[Alias] = [Alias(symbol, symbol, "code", context_level(symbol, "code", generic))]
    seen = {symbol}

    def add(alias: str, alias_type: str) -> None:
        alias = alias.strip()
        if not alias or alias in seen or len(alias) < 2:
            return
        seen.add(alias)
        out.append(Alias(symbol, alias, alias_type, context_level(alias, alias_type, generic)))

    add(short, "short")
    if display_name.strip() != short:
        add(display_name.strip(), "name")

    for long_alias in derive_long_aliases(company_core(full_name), short):
        add(long_alias, "name")

    prefix = derive_prefix_alias(short)
    if prefix:
        add(prefix, "short")

    for alias in extra or []:
        add(alias, "manual")

    return out


def resolve_collisions(aliases: list[Alias]) -> list[Alias]:
    """把指向多家公司的別名一律升到最嚴格層級。

    全市場的別名空間必然重疊（「南亞」同時是 1303 南亞與 2408 南亞科的別名，
    剝字尾又會製造更多碰撞）。與其逐一人工處理，不如自動偵測：
    同一字串對應到兩個以上代號時，它就不足以單獨識別任何一家。
    """
    owners: dict[str, set[str]] = {}
    for a in aliases:
        owners.setdefault(a.alias, set()).add(a.symbol)

    out: list[Alias] = []
    for a in aliases:
        if a.alias_type == "code":
            out.append(a)
            continue
        level = CONTEXT_CODE if len(owners[a.alias]) > 1 else a.requires_context
        out.append(Alias(a.symbol, a.alias, a.alias_type, level))
    return out


def classify_security(code: str) -> str:
    """依代號型態判斷有價證券類別。

    櫃買中心的日行情端點回傳一萬多筆，其中約九成是權證，必須先濾掉，
    否則搜尋「世界」會被「世界群益5B售01」這類認售權證洗版。
    權證代號有純數字（715001）與帶認售字尾（72713U）兩種寫法，都要涵蓋。
    """
    if re.fullmatch(r"00\d{2,4}[A-Z]?", code):
        return "etf"
    if re.fullmatch(r"\d{4}", code):
        return "stock"
    if re.fullmatch(r"\d{4}[A-Z]\d?", code):  # 2887Z1、1101B 特別股
        return "preferred"
    if re.fullmatch(r"0[12]\d{3}T", code):  # 01001T 不動產投資信託
        return "reit"
    if re.fullmatch(r"9\d{5}", code):  # 910322 存託憑證
        return "tdr"
    if re.fullmatch(r"[07]\d{4}[0-9A-Z]", code):
        return "warrant"
    return "other"
