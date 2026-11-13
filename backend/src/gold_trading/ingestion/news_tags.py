"""Nhận diện ngôn ngữ + thực thể cơ bản của tin (GĐ1 bước 10d — ING-23).

Thiết kế: ``docs/thiet-ke/21-khung-tin.md`` mục 10. Tóm tắt:

- **Tính khi đọc, không lưu**: đầu vào là bản tin đã biết tại ``as_of`` (point-in-time) → kết quả
  tính lại được, đổi luật thì đổi ``TAGGER_VERSION`` mà không phải sửa DB.
- **Chỉ là nhãn**: không phải tín hiệu, không phải cảm xúc thị trường, không có "xác suất". Việc
  hiểu nghĩa tin (tác động, chiều hướng) là của News analyst ở GĐ3 (NEWS-01, NEWS-02).
- **Luật đơn giản, công khai**: từ khóa có ranh giới từ; tên riêng / viết tắt phân biệt hoa thường
  ("Fed" ≠ "fed up", "Cook" ≠ "cook").
- Ngôn ngữ: ``en`` / ``other`` / ``und`` (không đủ chữ để biết). Không đoán ngôn ngữ cụ thể
  khác tiếng Anh — nguồn hiện tại đều là thông cáo tiếng Anh; ``other`` → cờ để tầng sau thận trọng.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

TAGGER_VERSION = "news-tags-2026.11.13"

MIN_LETTERS = 20          # ít chữ hơn → "und"
MIN_LATIN_SHARE = 0.8     # tỉ lệ chữ Latin tối thiểu để có thể là tiếng Anh
MIN_STOPWORD_HITS = 2
MIN_STOPWORD_SHARE = 0.08  # tỉ lệ từ chức năng tiếng Anh trên tổng số từ
MIN_WORDS_FOR_OTHER = 12   # chữ Latin, không đủ từ chức năng: dưới số từ này → "und", không "other"

_EN_STOPWORDS = frozenset("""
a an and are as at be been but by for from has have in into is it its not of on or our
that the their this to was were which will with we
""".split())

_WORD_RE = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?")


def _ci(*words: str) -> re.Pattern[str]:
    """Từ khóa không phân biệt hoa thường, có ranh giới từ (cho phép số nhiều -s)."""
    alt = "|".join(re.escape(w).replace(r"\ ", r"\s+") for w in words)
    return re.compile(rf"(?<![\w-])(?:{alt})s?(?![\w-])", re.IGNORECASE)


def _cs(*words: str) -> re.Pattern[str]:
    """Tên riêng / viết tắt: phân biệt hoa thường."""
    alt = "|".join(re.escape(w).replace(r"\ ", r"\s+") for w in words)
    return re.compile(rf"(?<![\w-])(?:{alt})(?![\w-])")


# Nhóm thực thể → các mẫu. Đổi danh sách = đổi TAGGER_VERSION + ghi lý do ở tài liệu thiết kế.
ENTITY_RULES: dict[str, tuple[re.Pattern[str], ...]] = {
    "FED": (
        _ci("Federal Reserve", "Federal Open Market Committee", "Board of Governors"),
        _cs("Fed", "FOMC", "Powell", "Jefferson", "Bowman", "Waller", "Barr", "Cook", "Miran"),
    ),
    "RATES": (
        _ci("interest rate", "federal funds", "funds rate", "rate cut", "rate hike",
            "basis point", "monetary policy", "policy rate", "yield", "discount rate",
            "balance sheet"),
    ),
    "INFLATION": (
        _ci("inflation", "disinflation", "deflation", "consumer price", "price stability",
            "personal consumption expenditures"),
        _cs("CPI", "PCE", "PPI"),
    ),
    "LABOR": (
        _ci("employment", "unemployment", "payroll", "labor market", "jobless", "jobs report"),
    ),
    "GOLD": (
        _ci("gold", "bullion", "precious metal"),
        _cs("XAU", "XAUUSD"),
    ),
    "USD": (
        _ci("dollar", "greenback", "exchange rate", "currency", "currencies"),
        _cs("USD", "DXY"),
    ),
    "FISCAL": (
        _ci("debt limit", "debt ceiling", "deficit", "quarterly refunding", "fiscal",
            "Treasury auction", "Treasury securities", "national debt"),
    ),
    "GEOPOLITICS": (
        _ci("sanction", "war", "conflict", "tariff", "geopolitical", "terrorist", "terrorism",
            "missile", "invasion", "embargo"),
        _cs("China", "Chinese", "Russia", "Russian", "Iran", "Iranian", "Ukraine", "Israel",
            "Gaza", "Hizballah", "Hezbollah", "Hamas", "North Korea", "OFAC", "Middle East",
            "Venezuela", "Taiwan"),
    ),
}


@dataclass(frozen=True)
class NewsTags:
    language: str                                  # "en" / "other" / "und"
    entities: dict[str, tuple[str, ...]] = field(default_factory=dict)  # nhóm → từ khớp
    flags: frozenset[str] = frozenset()
    version: str = TAGGER_VERSION

    @property
    def groups(self) -> tuple[str, ...]:
        return tuple(sorted(self.entities))


def detect_language(text: str) -> str:
    letters = [c for c in text if c.isalpha()]
    if len(letters) < MIN_LETTERS:
        return "und"
    latin = sum(1 for c in letters if "LATIN" in unicodedata.name(c, ""))
    if latin / len(letters) < MIN_LATIN_SHARE:
        return "other"
    words = [w.casefold() for w in _WORD_RE.findall(text)]
    hits = sum(1 for w in words if w in _EN_STOPWORDS)
    if words and hits >= MIN_STOPWORD_HITS and hits / len(words) >= MIN_STOPWORD_SHARE:
        return "en"
    # Tiêu đề ngắn (vd. "Federal Reserve issues FOMC statement") ít / không có từ chức năng:
    # quá ít từ để kết luận → "und" (không đoán), trừ khi có ≥ 1 từ chức năng và toàn ASCII.
    if len(words) < MIN_WORDS_FOR_OTHER:
        return "en" if hits >= 1 and all(ord(c) < 128 for c in letters) else "und"
    return "other"


def find_entities(text: str) -> dict[str, tuple[str, ...]]:
    out: dict[str, tuple[str, ...]] = {}
    for group, pats in ENTITY_RULES.items():
        found: dict[str, None] = {}
        for p in pats:
            for m in p.finditer(text):
                found.setdefault(re.sub(r"\s+", " ", m.group(0)), None)
        if found:
            out[group] = tuple(found)
    return out


def tag_text(title: str, summary: str) -> NewsTags:
    text = f"{title}\n{summary}"
    lang = detect_language(text)
    flags = set()
    if lang == "other":
        flags.add("NON_ENGLISH")
    elif lang == "und":
        flags.add("LANGUAGE_UNKNOWN")
    return NewsTags(lang, find_entities(text), frozenset(flags))


def tag_record(rec) -> NewsTags:
    """Nhãn của một bản ghi tin (``kind="news"``) — chỉ đọc ``title`` + ``summary`` đã làm sạch."""
    p = rec.payload
    return tag_text(str(p.get("title", "")), str(p.get("summary", "")))
