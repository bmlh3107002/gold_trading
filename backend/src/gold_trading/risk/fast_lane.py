"""Làn nhanh — luật chặn mở lệnh mới theo công bố số liệu + thông cáo Fed (GĐ2 bước 4b).

Thiết kế + lý do: ``docs/thiet-ke/26-lam-nhanh.md`` mục 3. Ngưỡng: **DEC-20**. Chỉ dùng luật,
không gọi LLM (FAST-02). Tóm tắt:

- **Cửa sổ lịch** (GĐ1, ``economic_calendar``): mỗi sự kiện trên bảng lịch hợp nhất (đã biết tại
  thời điểm xét, có trạng thái nguồn) chặn trong ``[window_start, window_end)`` — đã gồm kéo dài khi
  chưa có số / không tin giờ. Tính khi đọc (point-in-time), không lưu: lịch đổi → cửa sổ đổi theo.
- **Số liệu HIGH vừa nhận** (DEC-20 câu 1): chặn thêm ``RELEASE_HOLD`` (15 phút) **kể từ lúc hệ
  thống biết số**. Số không khớp lần công bố nào trên lịch → coi là HIGH (an toàn).
- **Thông cáo chính sách tiền tệ Fed** (câu 3): khớp sự kiện FOMC HIGH trên lịch → như số liệu
  HIGH; **không có trên lịch** → lệnh cấm ``NEWS`` 15 phút. Phát biểu Fed, tin Bộ Tài chính, tin
  khác → **chỉ gắn cờ** (không chặn).
- **Thị trường đóng** (2-C07): thời gian giữ chặn chỉ đếm **phút thị trường mở** — sự kiện lúc đóng
  cửa vẫn được xử lý, lệnh cấm kéo tới 15 phút sau khi mở cửa.
- **Gộp cửa sổ** (2-C08): các lệnh cấm chồng / nối nhau → một cửa sổ (``merge_windows``).

Đổi bất kỳ con số / luật nào ở đây → đổi ``POLICY_VERSION`` + ghi lý do vào file thiết kế.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from gold_trading.common.time import utcnow
from gold_trading.ingestion.economic_calendar import (
    ACTUAL_SOURCES,
    ET,
    economic_calendar,
    health_map,
)
from gold_trading.ingestion.event_importance import Importance, rate
from gold_trading.orchestrator.dispatcher import Handler
from gold_trading.orchestrator.model import Event, EventType
from gold_trading.risk.blocks import ALL, Block, BlockKind, is_active

POLICY_VERSION = "fast-lane-2026.11.14"
HANDLER_VERSION = "fast-lane-1"

RELEASE_HOLD = timedelta(minutes=15)    # DEC-20 câu 1: từ lúc nhận số HIGH
NEWS_HOLD = timedelta(minutes=15)       # DEC-20 câu 3: thông cáo tiền tệ Fed ngoài lịch
# Thông cáo cách giờ trên lịch quá chừng này → coi là "ngoài lịch".
FED_MATCH_TOLERANCE = timedelta(minutes=60)
# Tin thấy lần đầu khi đã đăng quá lâu (lần tải đầu, nguồn hỏng lâu) → không phải tin "vừa ra":
# chỉ gắn cờ. 36 giờ: rộng hơn một ngày để giờ đăng chỉ có ngày (00:00) vẫn được coi là mới.
NEWS_MAX_AGE = timedelta(hours=36)
# Tìm giờ mở cửa tối đa chừng này (Tết dương / Giáng sinh + cuối tuần < 4 ngày); quá → giữ chặn
# tới hết khoảng tìm (an toàn).
MAX_CLOSED_SEARCH = timedelta(days=8)
STEP = timedelta(minutes=1)
# Cửa sổ lịch tính sẵn cho khoảng này sau lúc tính (bộ nhớ đệm không bỏ sót cửa sổ sắp mở).
CACHE_TTL = timedelta(seconds=5)
LOOKAHEAD = timedelta(minutes=2)

FED_POLICY_SOURCE = "fed_rss_monetary"
FED_CALENDAR_SOURCE = "fed_fomc"
# Nguồn số không gắn ``release_ref`` (gắn theo tuần) → mức theo sự kiện của nguồn.
UNLINKED_VALUE_EVENTS = {"dol_claims": "DOL_JOBLESS_CLAIMS"}


# ============================================================ giờ giữ chặn (2-C07)

def hold_end(start: datetime, hold: timedelta, market_calendar=None) -> datetime:
    """Thời điểm hết ``hold`` **phút thị trường mở** kể từ ``start``.

    Không có lịch thị trường → ``start + hold``. Mỗi phút xét theo trạng thái lúc đầu phút đó.
    Không tìm đủ trong ``MAX_CLOSED_SEARCH`` → hết khoảng tìm (an toàn: chặn lâu hơn)."""
    if market_calendar is None:
        return start + hold
    left = hold
    t = start
    limit = start + MAX_CLOSED_SEARCH
    while t < limit:
        if market_calendar.is_open(t):
            if left <= STEP:
                return t + left
            left -= STEP
        t += STEP
    return limit


# ============================================================ cửa sổ lịch (tính khi đọc)

def calendar_blocks(items, as_of: datetime, market_calendar=None) -> list[Block]:
    """Lệnh cấm suy ra từ bảng lịch hợp nhất đã biết tại ``as_of`` (không lưu).

    - Mỗi sự kiện có cửa sổ → ``CALENDAR_<mức>`` trong ``[window_start, window_end)``.
    - Sự kiện HIGH đã nhận số → thêm ``RELEASE_HIGH_RECEIVED`` từ lúc nhận số, giữ
      ``RELEASE_HOLD`` phút thị trường mở (cùng khóa với lệnh cấm bộ xử lý làn nhanh ghi →
      gộp được, không đếm hai lần)."""
    out: list[Block] = []
    for it in items:
        if it.window_start is not None and it.window_end is not None \
                and it.window_end > it.window_start:
            out.append(Block(BlockKind.RELEASE, ALL, f"CALENDAR_{it.importance}",
                             it.window_start, it.window_end,
                             f"cal:{it.source}:{it.logical_key}"[:256], as_of, POLICY_VERSION))
        if (it.importance == Importance.HIGH.value and it.actual_status == "RECEIVED"
                and it.actual_received_at is not None):
            got = it.actual_received_at
            out.append(Block(BlockKind.RELEASE, ALL, "RELEASE_HIGH_RECEIVED", got,
                             hold_end(got, RELEASE_HOLD, market_calendar),
                             release_cause(it.source, it.logical_key), max(got, as_of),
                             POLICY_VERSION))
    return out


def release_cause(source: str, logical_key: str) -> str:
    return f"release:{source}:{logical_key}"[:256]


class CalendarBlocks:
    """Cửa sổ lịch cho Safety: tính lại tối đa mỗi ``CACHE_TTL`` (một lần cho mọi tài khoản).

    Đọc lỗi → ném lỗi (Safety chặn). Có ``check_log`` → truyền trạng thái nguồn (nguồn không khỏe
    → không tin giờ / số chưa biết → chặn rộng hơn, theo chính sách GĐ1)."""

    def __init__(self, store, check_log=None, market_calendar=None, *,
                 ttl: timedelta = CACHE_TTL) -> None:
        self.store = store
        self.check_log = check_log
        self.market_calendar = market_calendar
        self.ttl = ttl
        self._lock = threading.Lock()
        self._at: datetime | None = None
        self._blocks: list[Block] = []

    def compute(self, as_of: datetime) -> list[Block]:
        health = (health_map(self.check_log, self.store, as_of)
                  if self.check_log is not None else None)
        items = economic_calendar(self.store, as_of, start=as_of - timedelta(days=1),
                                  end=as_of + self.ttl + LOOKAHEAD, health=health)
        return calendar_blocks(items, as_of, self.market_calendar)

    def active(self, now: datetime) -> list[Block]:
        with self._lock:
            if self._at is None or not (self._at <= now < self._at + self.ttl):
                self._blocks = self.compute(now)
                self._at = now
            blocks = self._blocks
        return [b for b in blocks if is_active(b, None, now)]


# ============================================================ gộp cửa sổ (2-C08)

@dataclass(frozen=True)
class MergedWindow:
    start_at: datetime
    end_at: datetime | None          # None: tới khi gỡ
    reason_codes: tuple[str, ...]
    causes: tuple[str, ...]


def merge_windows(blocks) -> list[MergedWindow]:
    """Gộp lệnh cấm chồng hoặc nối nhau thành cửa sổ liền (hai công bố cùng phút → một cửa sổ)."""
    rows = sorted(blocks, key=lambda b: (b.start_at, b.end_at is None,
                                         b.end_at or b.start_at, b.block_id))
    out: list[MergedWindow] = []
    cur: list = []
    end: datetime | None = None

    def flush():
        if cur:
            out.append(MergedWindow(cur[0].start_at, end,
                                    tuple(sorted({b.reason_code for b in cur})),
                                    tuple(sorted({b.cause_ref for b in cur}))))

    for b in rows:
        if cur and (end is None or b.start_at <= end):
            cur.append(b)
            if end is not None:
                end = None if b.end_at is None else max(end, b.end_at)
            continue
        flush()
        cur, end = [b], b.end_at
    flush()
    return out


def dedupe(blocks) -> list[Block]:
    """Cùng ``block_id`` (cùng nguyên nhân) → giữ một (ưu tiên bản đã lưu — đứng trước)."""
    seen: dict[str, Block] = {}
    for b in blocks:
        seen.setdefault(b.block_id, b)
    return sorted(seen.values(), key=lambda b: (b.start_at, b.block_id))


# ============================================================ bộ xử lý job FAST_LANE

@dataclass(frozen=True)
class Decision:
    """Kết quả luật cho một sự kiện: lệnh cấm cần ghi (có thể rỗng) + mã cờ (chỉ cảnh báo)."""

    blocks: tuple[Block, ...] = ()
    flag: str | None = None


def _block(kind: BlockKind, reason: str, start: datetime, hold: timedelta, cause: str,
           now: datetime, market_calendar) -> Block:
    created = max(now, start)
    return Block(kind, ALL, reason, start, hold_end(start, hold, market_calendar), cause[:256],
                 created, POLICY_VERSION,
                 latency_ms=int((created - start).total_seconds() * 1000))


def decide_release(e: Event, record_store, now: datetime, market_calendar=None) -> Decision:
    """Số liệu vừa biết (``ACTUAL_RELEASED``). Lịch đọc tại ``e.known_at`` (replay ra cùng kết quả).

    Khớp lần công bố HIGH → chặn 15 phút thị trường mở từ lúc nhận số. Khớp mức thấp hơn → chỉ cờ
    (cửa sổ lịch vẫn áp). Không khớp lần công bố nào → coi là HIGH (an toàn)."""
    src = str(e.payload.get("source") or "")
    ref = e.payload.get("release_ref")
    if src in UNLINKED_VALUE_EVENTS and not ref:
        imp = rate(UNLINKED_VALUE_EVENTS[src]).importance
        if imp is not Importance.HIGH:
            return Decision(flag=f"RELEASE_{imp.value}")
        return Decision((_block(BlockKind.RELEASE, "RELEASE_HIGH_RECEIVED", e.known_at,
                                RELEASE_HOLD, f"release:{src}:{e.known_at:%Y-%m-%dT%H:%M}",
                                now, market_calendar),))
    if ref:
        items = economic_calendar(record_store, e.known_at, start=e.known_at - timedelta(days=4),
                                  end=e.known_at + timedelta(days=1))
        matched = [i for i in items if i.match_ref == ref and ACTUAL_SOURCES.get(i.event) == src
                   and i.actual_status == "RECEIVED" and i.actual_received_at is not None]
        if matched:
            high = [i for i in matched if i.importance == Importance.HIGH.value]
            if not high:
                return Decision(flag="RELEASE_" + max(i.importance for i in matched))
            return Decision(tuple(_block(BlockKind.RELEASE, "RELEASE_HIGH_RECEIVED",
                                         i.actual_received_at, RELEASE_HOLD,
                                         release_cause(i.source, i.logical_key), now,
                                         market_calendar) for i in high))
    # Số không gắn lần công bố nào trên lịch → chưa biết mức → HIGH. Gộp theo nguồn + phút để
    # nạp bù nhiều số cùng lúc chỉ sinh một lệnh cấm.
    return Decision((_block(BlockKind.RELEASE, "RELEASE_UNMATCHED", e.known_at, RELEASE_HOLD,
                            f"release-unmatched:{src}:{e.known_at:%Y-%m-%dT%H:%M}", now,
                            market_calendar),))


def decide_news(e: Event, record_store, now: datetime, market_calendar=None) -> Decision:
    """Tin vừa thấy (``NEWS_PUBLISHED``). Chỉ thông cáo chính sách tiền tệ Fed mới chặn."""
    src = str(e.payload.get("source") or "")
    if e.event_version != "r0":
        return Decision(flag="NEWS_REVISION")         # bài sửa: đã xét ở bản đầu
    if src != FED_POLICY_SOURCE:
        return Decision(flag=f"NEWS_{src.upper()}"[:64] if src else "NEWS_UNKNOWN_SOURCE")
    if e.known_at - e.occurred_at > NEWS_MAX_AGE:
        return Decision(flag="FED_POLICY_OLD_ITEM")
    day = e.occurred_at.astimezone(ET).date()
    items = economic_calendar(record_store, e.known_at,
                              start=e.occurred_at - timedelta(days=2),
                              end=e.occurred_at + timedelta(days=2),
                              sources=(FED_CALENDAR_SOURCE,))
    sched = [i for i in items if i.release_date_local == day and (
        i.all_day or abs(e.occurred_at - i.release_at) <= FED_MATCH_TOLERANCE)]
    cause = f"news:{src}:{e.payload.get('logical_key') or e.subject}"
    if any(i.importance == Importance.HIGH.value for i in sched):
        return Decision((_block(BlockKind.RELEASE, "FOMC_RECEIVED", e.known_at, RELEASE_HOLD,
                                cause, now, market_calendar),))
    if sched:
        return Decision(flag="FED_POLICY_SCHEDULED_" + max(i.importance for i in sched))
    return Decision((_block(BlockKind.NEWS, "FED_UNSCHEDULED_POLICY", e.known_at, NEWS_HOLD,
                            cause, now, market_calendar),))


def fast_lane_handler(block_store, record_store, market_calendar=None,
                      clock: Callable[[], datetime] = utcnow, monitor=None) -> Handler:
    """Job ``FAST_LANE``: áp luật, ghi lệnh cấm (idempotent theo nguyên nhân). Kết quả job:
    ``block:<id>,…`` hoặc ``flag:<mã>``. ``created_at`` = lúc ghi thật (đồng hồ hệ thống) →
    lệnh cấm chỉ có hiệu lực từ lúc hệ thống biết; độ trễ ghi ở ``latency_ms``."""

    def run(e: Event, now: datetime) -> str | None:
        t = max(now, clock())
        if e.event_type is EventType.ACTUAL_RELEASED:
            decide = decide_release
        elif e.event_type is EventType.NEWS_PUBLISHED:
            decide = decide_news
        else:
            raise NotFastLaneEvent(e.event_type.value)
        try:
            d = decide(e, record_store, t, market_calendar)
        except Exception:
            # Không áp được luật (đọc lịch lỗi, dữ liệu hỏng…) → mặc định an toàn: chặn 15 phút
            # từ lúc biết sự kiện rồi báo lỗi (job thử lại / dead-letter như mọi job).
            if e.event_type is EventType.ACTUAL_RELEASED or \
                    e.payload.get("source") == FED_POLICY_SOURCE:
                block_store.add(_block(BlockKind.RELEASE, "FAST_LANE_ERROR", e.known_at,
                                       RELEASE_HOLD, f"error:{e.event_id}", t,
                                       market_calendar))
            raise
        for b in d.blocks:
            added = block_store.add(b)
            # > 10 giây → cảnh báo (2-C09). Sự kiện cũ xử lý lại lúc khởi động (lệnh cấm đã hết
            # hạn) không tính — không phải độ trễ của làn nhanh.
            if added and monitor is not None and b.latency_ms is not None \
                    and (b.end_at is None or b.end_at > t):
                monitor.latency(b.latency_ms)
        if d.blocks:
            return ("block:" + ",".join(b.block_id[:12] for b in d.blocks))[:256]
        return f"flag:{d.flag}"

    return Handler(HANDLER_VERSION, run, deadline=timedelta(seconds=10), max_attempts=3,
                   retry_base=timedelta(seconds=2), fatal=(NotFastLaneEvent,))


class NotFastLaneEvent(ValueError):
    """Sự kiện không thuộc làn nhanh (lỗi định tuyến) → dead-letter ngay."""

