"""Khung nạp tin (GĐ1 bước 10a — ING-10; 1D-C01..C04, C06; 1D-C05 phần backoff).

Thiết kế + lý do: ``docs/thiet-ke/21-khung-tin.md``. Tóm tắt:

- **Danh sách nguồn cấu hình được** (DEC-02): file JSON (mặc định ``news_sources.json`` cạnh
  module này, đổi bằng ``GT_NEWS_SOURCES_FILE``). Thêm/bật/tắt nguồn RSS không sửa code; mỗi nguồn
  bắt buộc có ghi chú giấy phép, và chỉ bật được khi điều khoản nhà cung cấp ``VERIFIED`` (ING-32).
  File sai bất kỳ chỗ nào → từ chối cả file (không bật nửa vời).
- **Đọc RSS 2.0 / Atom** an toàn: giới hạn cỡ + số mục; từ chối mọi ``<!DOCTYPE`` / ``<!ENTITY``
  (chặn XXE, "billion laughs"). Nội dung tin chỉ là **dữ liệu**: lưu nguyên văn (đã cắt độ dài),
  không bao giờ thực thi / làm theo (1D-C04).
- **Thời gian** (1D-C03): ``published_at`` thiếu / sai / không múi giờ / ở tương lai → dùng
  ``ingested_at`` + cờ. Không bao giờ đoán múi giờ.
- **Lưu**: mỗi mục tin là một dữ kiện ``kind="news"`` trong store point-in-time (7a). Bài bị sửa
  (khác tiêu đề / tóm tắt / URL) → **revision mới**, giữ bản cũ (1D-C02). Gửi lại y hệt → không ghi.
- **Gộp tin** (1D-C01, 1D-C06): đọc tại ``as_of``, các mục có cùng *dấu vân tay nội dung* (tiêu đề +
  tóm tắt đã chuẩn hóa) thành **một tin gốc + các liên kết**; thời điểm của tin = lần đầu hệ thống
  thấy nội dung đó. Tin cũ đăng lại (khác guid/URL, cùng nội dung) → nằm trong tin gốc cũ, **không**
  là tin mới.
"""

from __future__ import annotations

import email.utils
import hashlib
import html
import json
import os
import re
import unicodedata
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from xml.parsers import expat

from gold_trading.ingestion.source_status import SOURCE_NAME_RE

POLICY_VERSION = "news-2026.11.13"
PAYLOAD_VERSION = "news-v1"
KIND = "news"

MAX_CONFIG_BYTES = 256 * 1024
MAX_FEED_BYTES = 5 * 1024 * 1024
MAX_ITEMS = 300               # mục đọc mỗi lần tải; thừa → bỏ (cờ FEED_TRUNCATED trên kết quả)
MAX_TITLE = 500               # ký tự sau khi làm sạch
MAX_SUMMARY = 20_000
MAX_URL = 2048
MAX_GUID = 1024
MAX_PUBLISHED_RAW = 200
MAX_LICENSE_NOTE = 500
MAX_REVISIONS = 20            # một mục sửa quá số lần này → không ghi thêm (chống nguồn "nhảy")
FUTURE_TOLERANCE = timedelta(minutes=5)   # lệch đồng hồ nhỏ của nguồn: kẹp về now, có cờ
OLD_ON_ARRIVAL = timedelta(days=7)        # lần đầu thấy mà giờ đăng đã cũ hơn → cờ
MIN_YEAR = 1990
POLL_MINUTES = (5, 1440)      # chu kỳ tải cho phép (phút)
FETCH_TTL_HOURS = (1, 168)
MAX_BACKOFF = timedelta(hours=6)
STORY_LOOKBACK = timedelta(days=90)       # cửa sổ tìm tin gốc khi gộp (1D-C06)

_ATOM = "{http://www.w3.org/2005/Atom}"
_DC_DATE = "{http://purl.org/dc/elements/1.1/}date"
_CONTENT_ENCODED = "{http://purl.org/rss/1.0/modules/content/}encoded"
_DTD_RE = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]{0,2000}>")
# Ký tự điều khiển (trừ \t \n), C1, ký tự ẩn hướng chữ / độ rộng 0 → thay bằng khoảng trắng.
_CTRL_RE = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e"
                      "\u2060-\u2069\ufeff]")
_WS_RE = re.compile(r"\s+")
# Câu có dạng "ra lệnh cho AI" — chỉ GẮN CỜ để tầng sau thận trọng; không chặn, không làm theo.
_SUSPECT_RE = re.compile(
    r"ignore (all |any )?(the )?(previous|prior|above) (instructions|prompts?)"
    r"|disregard (all |any )?(the )?(previous|prior|above)"
    r"|system prompt|you are now|act as (an? )?(ai|assistant|admin)"
    r"|<\s*/?\s*(system|assistant|instructions?)\s*>"
    r"|\b(buy|sell) (gold|xauusd) now\b",
    re.IGNORECASE)


# ================================================================ 1. Cấu hình nguồn (DEC-02)

class NewsConfigError(ValueError):
    pass


_CONFIG_KEYS = {"name", "provider", "url", "enabled", "license_note", "poll_minutes",
                "fetch_ttl_hours"}


@dataclass(frozen=True)
class NewsSourceConfig:
    name: str
    provider: str
    url: str
    enabled: bool
    license_note: str
    poll_minutes: int
    fetch_ttl_hours: int

    @property
    def host(self) -> str:
        return urlsplit(self.url).hostname or ""

    @property
    def poll(self) -> timedelta:
        return timedelta(minutes=self.poll_minutes)

    def spec(self):
        from gold_trading.ingestion.source_status import SourceSpec

        # Không data_ttl: nguồn tin có thể im lặng nhiều ngày mà vẫn khỏe (không có thông cáo).
        return SourceSpec(self.name, KIND, timedelta(hours=self.fetch_ttl_hours),
                          enabled=self.enabled, provider=self.provider)


def _int_in(v: Any, lo: int, hi: int, what: str) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise NewsConfigError(f"{what} phải là số nguyên trong [{lo}, {hi}]: {v!r}")
    return v


def _check_url(u: Any, what: str) -> str:
    if not isinstance(u, str) or len(u) > MAX_URL or _CTRL_RE.search(u) or " " in u:
        raise NewsConfigError(f"{what}: URL không hợp lệ")
    p = urlsplit(u)
    if p.scheme != "https" or not p.hostname:
        raise NewsConfigError(f"{what}: chỉ nhận URL https có tên máy: {u!r}")
    if p.username or p.password:
        raise NewsConfigError(f"{what}: URL không được chứa tài khoản/mật khẩu")
    if re.search(r"(key|token|secret|password)=", p.query, re.IGNORECASE):
        raise NewsConfigError(f"{what}: URL không được chứa khóa (khóa chỉ để trong .env)")
    return u


def parse_news_config(text: str | bytes, terms=None):
    """Đọc + kiểm file cấu hình. Trả ``(configs, registry)``. Sai bất kỳ chỗ nào → lỗi cả file."""
    from gold_trading.ingestion.source_status import SourceRegistry

    if isinstance(text, bytes):
        if len(text) > MAX_CONFIG_BYTES:
            raise NewsConfigError("file cấu hình nguồn tin quá lớn")
        text = text.decode("utf-8")
    if len(text) > MAX_CONFIG_BYTES:
        raise NewsConfigError("file cấu hình nguồn tin quá lớn")
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as e:
        raise NewsConfigError(f"file cấu hình nguồn tin không phải JSON: dòng {e.lineno}") from None
    if not isinstance(doc, dict) or doc.get("version") != 1 or set(doc) - {"version", "sources",
                                                                           "_comment"}:
        raise NewsConfigError('cấu hình phải là {"version": 1, "sources": [...]}')
    raw = doc.get("sources")
    if not isinstance(raw, list):
        raise NewsConfigError("thiếu danh sách sources")
    out: list[NewsSourceConfig] = []
    for i, s in enumerate(raw):
        what = f"sources[{i}]"
        if not isinstance(s, dict):
            raise NewsConfigError(f"{what} phải là object")
        if (extra := set(s) - _CONFIG_KEYS - {"_comment"}):
            raise NewsConfigError(f"{what}: khóa lạ {sorted(extra)} (gõ nhầm?)")
        if (missing := _CONFIG_KEYS - set(s)):
            raise NewsConfigError(f"{what}: thiếu {sorted(missing)}")
        name, provider, note = s["name"], s["provider"], s["license_note"]
        if not isinstance(name, str) or not SOURCE_NAME_RE.match(name):
            raise NewsConfigError(f"{what}: tên nguồn không hợp lệ: {name!r}")
        if not isinstance(provider, str) or not SOURCE_NAME_RE.match(provider):
            raise NewsConfigError(f"{what}: provider không hợp lệ: {provider!r}")
        if not isinstance(s["enabled"], bool):
            raise NewsConfigError(f"{what}: enabled phải là true/false")
        if not isinstance(note, str) or not note.strip() or len(note) > MAX_LICENSE_NOTE:
            raise NewsConfigError(f"{what}: license_note bắt buộc (≤ {MAX_LICENSE_NOTE} ký tự)")
        poll = _int_in(s["poll_minutes"], *POLL_MINUTES, f"{what}.poll_minutes")
        ttl = _int_in(s["fetch_ttl_hours"], *FETCH_TTL_HOURS, f"{what}.fetch_ttl_hours")
        if timedelta(hours=ttl) <= timedelta(minutes=poll):
            raise NewsConfigError(f"{what}: fetch_ttl_hours phải dài hơn chu kỳ tải")
        out.append(NewsSourceConfig(name, provider, _check_url(s["url"], what), s["enabled"],
                                    note.strip(), poll, ttl))
    try:
        registry = SourceRegistry([c.spec() for c in out], terms=terms)
    except ValueError as e:  # trùng tên / điều khoản chưa VERIFIED
        raise NewsConfigError(str(e)) from None
    return tuple(out), registry


DEFAULT_CONFIG = Path(__file__).with_name("news_sources.json")


def load_news_config(path: str | os.PathLike | None = None, terms=None):
    """``path`` > ``GT_NEWS_SOURCES_FILE`` > file mặc định. File chỉ định mà không có → lỗi."""
    p = Path(path or os.environ.get("GT_NEWS_SOURCES_FILE") or DEFAULT_CONFIG)
    try:
        data = p.read_bytes()
    except OSError:
        raise NewsConfigError(f"không đọc được file cấu hình nguồn tin: {p}") from None
    return parse_news_config(data, terms=terms)


# ================================================================ 2. Đọc RSS / Atom

class FeedParseError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class FeedItem:
    """Một mục như nguồn đưa (chuỗi thô, chưa làm sạch)."""

    title: str = ""
    link: str = ""
    guid: str = ""
    summary: str = ""
    published: str = ""


@dataclass(frozen=True)
class FeedResult:
    items: tuple[FeedItem, ...]
    truncated: bool = False


def _text(el: ET.Element | None) -> str:
    return "" if el is None else "".join(el.itertext())


def _rss_item(it: ET.Element) -> FeedItem:
    summary = _text(it.find("description")) or _text(it.find(_CONTENT_ENCODED))
    return FeedItem(_text(it.find("title")), _text(it.find("link")).strip(),
                    _text(it.find("guid")).strip(), summary,
                    (_text(it.find("pubDate")) or _text(it.find(_DC_DATE))).strip())


def _atom_entry(e: ET.Element) -> FeedItem:
    link = ""
    for ln in e.findall(f"{_ATOM}link"):
        if ln.get("rel", "alternate") == "alternate" and ln.get("href"):
            link = ln.get("href", "")
            break
    summary = _text(e.find(f"{_ATOM}summary")) or _text(e.find(f"{_ATOM}content"))
    pub = _text(e.find(f"{_ATOM}published")) or _text(e.find(f"{_ATOM}updated"))
    return FeedItem(_text(e.find(f"{_ATOM}title")), link.strip(),
                    _text(e.find(f"{_ATOM}id")).strip(), summary, pub.strip())


class _DtdForbidden(Exception):
    pass


def _forbid_dtd(*_a) -> None:
    raise _DtdForbidden


def parse_feed(data: bytes) -> FeedResult:
    if len(data) > MAX_FEED_BYTES:
        raise FeedParseError("FEED_TOO_LARGE")
    if _DTD_RE.search(data):
        raise FeedParseError("FEED_DTD_FORBIDDEN")
    # Chặn thêm ở tầng bộ phân tích (lượt quét riêng bằng expat): bộ lọc byte ở trên không thấy
    # DOCTYPE mã hóa UTF-16. Dừng ngay tại khai báo DOCTYPE, trước khi có thực thể nào được mở.
    scan = expat.ParserCreate()
    scan.StartDoctypeDeclHandler = _forbid_dtd
    scan.EntityDeclHandler = _forbid_dtd
    try:
        scan.Parse(data, True)
    except _DtdForbidden:
        raise FeedParseError("FEED_DTD_FORBIDDEN") from None
    except (expat.ExpatError, ValueError, LookupError):  # ValueError: bảng mã expat không hỗ trợ
        raise FeedParseError("FEED_NOT_XML") from None
    try:
        root = ET.fromstring(data)
    except (ET.ParseError, ValueError, LookupError):
        raise FeedParseError("FEED_NOT_XML") from None
    if root.tag == "rss":
        channel = root.find("channel")
        if channel is None:
            raise FeedParseError("FEED_FORMAT_UNKNOWN")
        els, conv = channel.findall("item"), _rss_item
    elif root.tag == f"{_ATOM}feed":
        els, conv = root.findall(f"{_ATOM}entry"), _atom_entry
    else:
        raise FeedParseError("FEED_FORMAT_UNKNOWN")
    return FeedResult(tuple(conv(e) for e in els[:MAX_ITEMS]), len(els) > MAX_ITEMS)


# ================================================================ 3. Chuẩn hóa

def clean_text(s: str, limit: int) -> tuple[str, bool]:
    """Bỏ thẻ HTML, giải mã ký tự HTML, bỏ ký tự điều khiển/ẩn, gộp khoảng trắng, cắt độ dài.
    Kết quả chỉ để hiển thị/so khớp — **không bao giờ** đưa vào trình duyệt dưới dạng HTML."""
    s = _CTRL_RE.sub(" ", s)
    s = _TAG_RE.sub(" ", s)
    s = html.unescape(s)
    s = _TAG_RE.sub(" ", s)          # thẻ được mã hóa (&lt;b&gt;) lộ ra sau unescape
    s = _CTRL_RE.sub(" ", s)         # &#0; … sau unescape
    s = _WS_RE.sub(" ", s).strip()
    if len(s) > limit:
        return s[:limit], True
    return s, False


def content_fingerprint(title: str, summary: str) -> str | None:
    """Dấu vân tay nội dung để gộp tin (1D-C01, C06): chữ thường, NFKC, chỉ giữ chữ + số.
    Rỗng → None (không gộp các tin rỗng với nhau)."""
    def norm(s: str) -> str:
        s = unicodedata.normalize("NFKC", s).casefold()
        return " ".join(re.findall(r"\w+", s))
    t, b = norm(title), norm(summary)
    if not t and not b:
        return None
    return hashlib.sha256(f"{t}\n{b}".encode()).hexdigest()


def parse_published(raw: str) -> tuple[datetime | None, str | None]:
    """``(giờ UTC, None)`` hoặc ``(None, cờ)``. Không múi giờ → không đoán (1D-C03)."""
    raw = raw.strip()
    if not raw:
        return None, "PUBLISHED_AT_MISSING"
    dt: datetime | None = None
    try:
        dt = email.utils.parsedate_to_datetime(raw)          # RSS: RFC 822
    except (TypeError, ValueError, IndexError):
        try:
            dt = datetime.fromisoformat(raw)                   # Atom: RFC 3339
        except ValueError:
            return None, "PUBLISHED_AT_INVALID"
    if dt.tzinfo is None or dt.utcoffset() is None:
        return None, "PUBLISHED_AT_NO_TZ"   # gồm "-0000" (RFC 2822: múi giờ không rõ)
    if dt.year < MIN_YEAR:
        return None, "PUBLISHED_AT_INVALID"
    return dt.astimezone(UTC), None


def _safe_url(u: str) -> tuple[str, str | None]:
    if not u:
        return "", None
    u2, _ = clean_text(u, MAX_URL + 1)
    p = urlsplit(u2)
    if len(u2) > MAX_URL or p.scheme not in ("http", "https") or not p.hostname:
        return "", "URL_INVALID"   # vd. javascript:, data: — không lưu làm liên kết
    return u2, None


@dataclass(frozen=True)
class NormalizedItem:
    logical_key: str
    title: str
    summary: str
    url: str
    guid: str
    published_raw: str
    published_at: datetime | None
    event_time: datetime
    content_fp: str | None
    flags: frozenset[str]

    def content(self) -> dict[str, str]:
        """Các trường quyết định "bài có bị sửa không" (1D-C02)."""
        return {"title": self.title, "summary": self.summary, "url": self.url}


def normalize(item: FeedItem, now: datetime) -> NormalizedItem:
    flags: set[str] = set()
    title, t_cut = clean_text(item.title, MAX_TITLE)
    summary, s_cut = clean_text(item.summary, MAX_SUMMARY)
    if t_cut or s_cut:
        flags.add("CONTENT_TRUNCATED")
    if not title and not summary:
        flags.add("CONTENT_EMPTY")
    # Soi trên văn bản đã giải mã nhưng CHƯA bỏ thẻ (thẻ giả "<system>" bị bỏ khi làm sạch).
    if _SUSPECT_RE.search(html.unescape(f"{item.title}\n{item.summary}")[:MAX_SUMMARY * 4]):
        flags.add("SUSPECT_INSTRUCTIONS")
    url, f = _safe_url(item.link)
    if f:
        flags.add(f)
    guid, g_cut = clean_text(item.guid, MAX_GUID)
    if g_cut:
        flags.add("GUID_TRUNCATED")
    pub_raw, _ = clean_text(item.published, MAX_PUBLISHED_RAW)
    pub, f = parse_published(pub_raw)
    if f:
        flags.add(f)
    if pub is not None and pub > now + FUTURE_TOLERANCE:
        flags.add("PUBLISHED_AT_FUTURE")
        pub = None
    if pub is not None and now - pub > OLD_ON_ARRIVAL:
        flags.add("OLD_ON_ARRIVAL")
    # Giờ đăng tin được (kẹp về now nếu lệch nhỏ) → event_time; không tin được → ingested_at.
    event_time = min(pub, now) if pub is not None else now
    fp = content_fingerprint(title, summary)
    basis = (f"guid:{guid}" if guid else f"url:{url}" if url
             else f"content:{fp}" if fp else None)
    if basis is None:
        raise FeedParseError("ITEM_NO_IDENTITY")
    key = "n:" + hashlib.sha256(basis.encode()).hexdigest()[:40]
    return NormalizedItem(key, title, summary, url, guid, pub_raw, pub, event_time, fp,
                          frozenset(flags))


# ================================================================ 4. Ghi (point-in-time)

def _record(source: str, n: NormalizedItem, now: datetime, rev: int,
            event_time: datetime, first_seen: datetime, flags: Iterable[str], raw_ref: str):
    from gold_trading.common.enums import SourceStatus
    from gold_trading.contracts.records import NormalizedRecord

    fl = sorted(set(flags))
    payload = {
        "title": n.title, "summary": n.summary, "url": n.url, "guid": n.guid,
        "published_raw": n.published_raw,
        "published_at": n.published_at.isoformat() if n.published_at else None,
        "first_seen_at": first_seen.isoformat(), "content_fingerprint": n.content_fp,
        "policy_version": POLICY_VERSION, "flags": fl}
    return NormalizedRecord(
        record_id=f"{source}:{n.logical_key}:r{rev}", source=source, kind=KIND,
        logical_key=n.logical_key, revision=rev, event_time=event_time, ingested_at=now,
        source_status=SourceStatus.HEALTHY, payload_version=PAYLOAD_VERSION,
        raw_ref=raw_ref[:1024], quality_flags=frozenset(fl), payload=payload)


def _content_of(rec) -> dict[str, str]:
    p = rec.payload
    return {"title": p.get("title", ""), "summary": p.get("summary", ""), "url": p.get("url", "")}


def sync_feed(store, source: str, feed: FeedResult, now: datetime, *, raw_ref: str = ""):
    """Ghi các mục của một lần tải. Trả ``AppendCounts``.

    - Mục mới → revision 0. Nội dung y hệt bản mới nhất → không ghi (đếm ``duplicate``).
    - Nội dung khác (bài bị sửa) → revision mới, giữ ``event_time`` + ``first_seen_at`` của
      revision 0, cờ ``EDITED`` (1D-C02).
    - Hai mục cùng định danh trong một lần tải mà khác nội dung → giữ mục đầu, mục sau ``conflict``.
    - Mục không có định danh (không guid, URL, nội dung) / sửa quá ``MAX_REVISIONS`` lần →
      ``invalid`` / ``conflict``, không ghi.
    """
    from gold_trading.ingestion.point_in_time import AppendCounts, AppendOutcome, AppendResult

    counts = AppendCounts()
    seen: dict[str, dict[str, str]] = {}
    for it in feed.items:
        try:
            n = normalize(it, now)
        except FeedParseError as e:
            counts.add(AppendResult(AppendOutcome.INVALID, e.code))
            continue
        if n.logical_key in seen:
            same = seen[n.logical_key] == n.content()
            counts.add(AppendResult(AppendOutcome.DUPLICATE if same else AppendOutcome.CONFLICT,
                                    None if same else "ITEM_DUPLICATED_IN_FEED"))
            continue
        seen[n.logical_key] = n.content()
        hist = store.history(source, n.logical_key, now)
        # Nguyên văn (cắt độ dài); NUL → U+FFFD vì Postgres không lưu được NUL.
        raw = {k: v[:lim].replace("\x00", "\ufffd") for k, v, lim in (
            ("title", it.title, MAX_TITLE * 2), ("link", it.link, MAX_URL),
            ("guid", it.guid, MAX_GUID), ("published", it.published, MAX_PUBLISHED_RAW),
            ("summary", it.summary, MAX_SUMMARY * 2))}
        if not hist:
            rec = _record(source, n, now, 0, n.event_time, now, n.flags, raw_ref)
            counts.add(store.append(rec, raw))
            continue
        last = max(hist, key=lambda r: r.revision)
        if _content_of(last) == n.content():
            counts.add(AppendResult(AppendOutcome.DUPLICATE))
            continue
        if last.revision + 1 > MAX_REVISIONS:
            counts.add(AppendResult(AppendOutcome.CONFLICT, "REVISION_LIMIT"))
            continue
        first = min(hist, key=lambda r: r.revision)
        first_seen = datetime.fromisoformat(first.payload["first_seen_at"])
        rec = _record(source, n, now, last.revision + 1, first.event_time, first_seen,
                      n.flags | {"EDITED"}, raw_ref)
        counts.add(store.append(rec, raw))
    return counts


# ================================================================ 5. Tải + lịch tải (1D-C05)

class FetchError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def http_getter(client, cfg: NewsSourceConfig, timeout: float = 30.0) -> Callable[[], bytes]:
    import httpx

    from gold_trading.ingestion.api_keys import error_code_for_exception, error_code_for_http

    def get() -> bytes:
        try:
            r = client.get(cfg.url, timeout=timeout, follow_redirects=True)
        except httpx.HTTPError as e:
            raise FetchError(error_code_for_exception(e)) from None
        if r.url.host != cfg.host:
            raise FetchError("UNEXPECTED_REDIRECT")
        if r.status_code != 200:
            raise FetchError(error_code_for_http(r.status_code))
        if len(r.content) > MAX_FEED_BYTES:
            raise FetchError("RESPONSE_TOO_LARGE")
        return r.content

    return get


def run_once(cfg: NewsSourceConfig, *, store, log, get: Callable[[], bytes], now: datetime,
             registry):
    """Một lần tải một nguồn tin; ghi một dòng nhật ký lần kiểm (ING-30)."""
    from gold_trading.ingestion.source_status import CheckOutcome, SourceCheck

    sp = registry.get(cfg.name)
    if sp is None or not sp.enabled:
        raise ValueError(f"nguồn tin {cfg.name} chưa được bật")
    try:
        feed = parse_feed(get())
    except FetchError as e:
        check = SourceCheck(cfg.name, now, CheckOutcome.ERROR, e.code)
    except FeedParseError as e:
        check = SourceCheck(cfg.name, now, CheckOutcome.INVALID, e.code)
    else:
        check = SourceCheck.from_counts(cfg.name, now,
                                        sync_feed(store, cfg.name, feed, now, raw_ref=cfg.url))
    log.record(check)
    return check


def backoff(cfg: NewsSourceConfig, failures: int, fatal: bool) -> timedelta:
    """Chờ sau lỗi: chu kỳ × 2^số lần lỗi liên tiếp, tối đa 6 giờ; lỗi "chết" → 6 giờ."""
    if fatal:
        return MAX_BACKOFF
    return min(cfg.poll * (2 ** min(max(failures, 1), 16)), MAX_BACKOFF)


def due(cfg: NewsSourceConfig, now: datetime, summary) -> str | None:
    """``REFRESH`` / ``RETRY`` / None — chỉ dựa trên nhật ký lần kiểm (khởi động lại không gọi dồn).
    Bị giới hạn tần suất / lỗi → giãn dần (1D-C05)."""
    from gold_trading.ingestion.source_status import CheckOutcome

    last = summary.last_check
    if last is None:
        return "REFRESH"
    if last.outcome is CheckOutcome.OK:
        return "REFRESH" if now - last.checked_at >= cfg.poll else None
    wait = backoff(cfg, summary.failures_since_ok, summary.fatal_code_since_ok is not None)
    return "RETRY" if now - last.checked_at >= wait else None


# ================================================================ 6. Đọc: gộp tin (1D-C01, C06)

@dataclass(frozen=True)
class NewsStory:
    """Một tin = mục gốc (thấy sớm nhất) + các mục cùng nội dung (nguồn khác / đăng lại)."""

    root: Any
    links: tuple[Any, ...] = field(default_factory=tuple)

    @property
    def first_seen_at(self) -> datetime:
        return first_seen_at(self.root)

    @property
    def sources(self) -> tuple[str, ...]:
        return tuple(sorted({self.root.source, *(r.source for r in self.links)}))


def first_seen_at(rec) -> datetime:
    return datetime.fromisoformat(rec.payload["first_seen_at"])


def news_stories(store, as_of: datetime, *, lookback: timedelta = STORY_LOOKBACK
                 ) -> list[NewsStory]:
    """Tin đã biết tại ``as_of`` (bản mới nhất của mỗi mục), gộp theo dấu vân tay nội dung.
    Sắp theo lúc hệ thống thấy lần đầu. Tin rỗng nội dung không gộp."""
    recs = store.as_of(as_of, kind=KIND, event_from=as_of - lookback)
    groups: dict[str, list[Any]] = {}
    alone: list[Any] = []
    for r in recs:
        fp = r.payload.get("content_fingerprint")
        (groups.setdefault(fp, []) if fp else alone).append(r)

    def order(r):
        return (first_seen_at(r), r.source, r.logical_key)

    stories = [NewsStory(r) for r in alone]
    for members in groups.values():
        members.sort(key=order)
        stories.append(NewsStory(members[0], tuple(members[1:])))
    stories.sort(key=lambda s: order(s.root))
    return stories


def new_stories(store, since: datetime, as_of: datetime) -> list[NewsStory]:
    """Tin **mới** trong ``(since, as_of]``: tin gốc thấy lần đầu trong khoảng này. Tin cũ đăng lại
    / tin trùng nguồn khác thuộc tin gốc cũ → không mới (1D-C06)."""
    return [s for s in news_stories(store, as_of) if since < s.first_seen_at <= as_of]
