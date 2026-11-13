"""Sinh sự kiện từ dữ liệu đã lưu (GĐ2 bước 1c — ORC-02 phần nguồn, 2-C01, 2-C02).

Thiết kế: ``docs/thiet-ke/25-event-orchestrator.md`` mục 2. Sự kiện **suy ra** từ nến và bản ghi
nguồn ngoài theo lúc hệ thống biết (``known_at``) — không móc vào code nạp. Cùng dữ liệu → cùng
khóa → quét lại / replay không sinh thêm. Dữ liệu có ``known_at`` ở tương lai chỉ thành sự kiện khi
tới giờ.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from gold_trading.orchestrator.model import Event, EventType

OVERLAP = timedelta(minutes=15)       # chồng lấn: bắt bản ghi commit chậm có known_at hơi cũ
FIRST_LOOKBACK = timedelta(days=2)    # lần quét đầu (chưa có sự kiện): không dựng lại cả lịch sử
MAX_CANDLE_OPEN_AGE = timedelta(days=60)  # Gateway nạp bù tối đa 5.000 nến M15 (~52 ngày)

ACTUAL_SOURCES = frozenset({"bea_nipa", "dol_claims", "bls_values", "census_marts"})
EXTERNAL_TYPES = (EventType.CALENDAR_UPDATED, EventType.ACTUAL_RELEASED,
                  EventType.MACRO_UPDATED, EventType.POSITIONING_UPDATED,
                  EventType.NEWS_PUBLISHED)


def external_event_type(source: str, kind: str) -> EventType:
    if kind == "calendar":
        return EventType.CALENDAR_UPDATED
    if kind == "news":
        return EventType.NEWS_PUBLISHED
    if kind == "positioning":
        return EventType.POSITIONING_UPDATED
    if source in ACTUAL_SOURCES:
        return EventType.ACTUAL_RELEASED
    return EventType.MACRO_UPDATED


def candle_event(c) -> Event:
    known = max(c.ingested_at, c.available_at)
    flags = sorted(f.value if hasattr(f, "value") else str(f) for f in c.flags)
    return Event(
        EventType.CANDLE_CLOSED,
        f"{c.source.value}:{c.feed_id}:{c.symbol}:{c.timeframe.value}",
        f"{c.open_time.isoformat()}:r{c.revision}",
        occurred_at=c.close_time, known_at=known,
        payload={"open_time": c.open_time.isoformat(), "revision": c.revision,
                 "flags": flags})


def record_event(r) -> Event:
    p = r.payload
    payload = {"source": r.source, "logical_key": r.logical_key, "revision": r.revision,
               "record_id": r.record_id}
    for k in ("event", "series", "release_ref", "status"):    # tham chiếu nhỏ cho bộ điều phối
        if isinstance(p.get(k), str):
            payload[k] = p[k][:128]
    return Event(external_event_type(r.source, r.kind), f"{r.source}:{r.logical_key}"[:256],
                 f"r{r.revision}", occurred_at=r.event_time, known_at=r.known_at,
                 payload=payload)


@dataclass
class ScanResult:
    window: dict[str, tuple[datetime, datetime]] = field(default_factory=dict)
    seen: dict[str, int] = field(default_factory=dict)
    new: dict[str, int] = field(default_factory=dict)


def _since(orch, types, now: datetime) -> datetime:
    marks = [m for t in types if (m := orch.max_known_at(t, now)) is not None]
    return (max(marks) - OVERLAP) if marks else now - FIRST_LOOKBACK


def scan(*, orch, candle_store, record_store, now: datetime,
         since: datetime | None = None) -> ScanResult:
    """Một lần quét tới ``now``. ``since`` (replay): quét từ mốc chỉ định thay vì mốc tự tính."""
    res = ScanResult()
    if candle_store is not None:
        lo = since if since is not None else _since(orch, (EventType.CANDLE_CLOSED,), now)
        evs = [candle_event(c) for c in candle_store.known_between(
            lo, now, max_open_age=MAX_CANDLE_OPEN_AGE)]
        res.window["candles"] = (lo, now)
        res.seen["candles"] = len(evs)
        res.new["candles"] = orch.record_events(sorted(evs, key=Event.order_key),
                                                recorded_at=now)
    if record_store is not None:
        lo = since if since is not None else _since(orch, EXTERNAL_TYPES, now)
        evs = [record_event(r) for r in record_store.known_between(lo, now)]
        res.window["external"] = (lo, now)
        res.seen["external"] = len(evs)
        res.new["external"] = orch.record_events(sorted(evs, key=Event.order_key),
                                                 recorded_at=now)
    return res
