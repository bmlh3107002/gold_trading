"""GW-08: gom tick bid/ask thành từng GIÂY đã trọn để gửi backend (ING-08). Chỉ đọc MT5.

- Đọc tick bằng ``copy_ticks_from`` (hàm đọc). Thời gian tick là GIỜ SERVER viết như UTC (như
  nến) → đổi sang UTC bằng múi giờ server; giây mơ hồ do đổi DST → bỏ (không đoán).
- 1A-C13 phía Gateway: tick giá ≤ 0 / không hữu hạn, bid > ask, thời gian đi lùi, tick lặp y hệt
  → bỏ + đếm theo lý do (gửi kèm ``gateway_dropped``). Backend kiểm lại lần nữa.
- Chỉ gửi giây ĐÃ TRỌN: đã có tick của giây sau, hoặc giờ server đã qua giây đó ≥ 3 giây.
- Tự kiểm cách MT5 hiểu mốc thời gian yêu cầu: tick trả về phải nằm trong khoảng đã xin. Sai
  (thư viện hiểu lệch múi giờ) → TẮT giá sống, báo rõ; nến vẫn chạy (không gửi giá sai giờ).
- Không nạp bù giá sống dài: bắt đầu từ 60 giây trước; gián đoạn > 10 phút thì bỏ qua phần cũ
  (nến vẫn đầy đủ qua đường nến).

1A-C08 (``TzWatch``): mỗi vòng so giờ tick MỚI NHẤT với đồng hồ máy — chỉ khi tick đó MỚI xuất
hiện từ lần đọc trước (vừa tới, nên giờ của nó ≈ bây giờ; tick cũ như sau giờ đóng cửa có thể lệch
đúng 1 giờ và bị hiểu nhầm). Lệch khác ``GT_SERVER_TZ`` một lần → TẠM DỪNG gửi nến + giá ngay
(không gửi dữ liệu có thể sai giờ); lệch 3 lần liên tiếp trong ≥ 60 giây → chặn hẳn + báo lỗi,
chỉ gỡ khi khớp lại 3 lần liên tiếp. Tạm dừng mà lần sau khớp → chạy tiếp.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from mt5_gateway.reader import Mt5Error, Mt5Reader
from mt5_gateway.timeconv import detect_offset_hours, server_epoch_to_utc, tz_offset_hours

FETCH_TICKS = 20000
START_BACK_S = 60
MAX_GAP_S = 600
SETTLE_S = 3
MAX_SECONDS_PER_POST = 600
# Tự kiểm mốc thời gian: tick trả về sớm hơn mốc đã xin quá mức này → thư viện hiểu lệch giờ
REQUEST_SKEW_TOLERANCE_S = 60
EMPTY_SKEW_S = 10


class TickRequestMismatch(Mt5Error):
    """MT5 trả tick ngoài khoảng đã xin: không biết chắc giờ → tắt giá sống."""


def server_now(tz: ZoneInfo, now_utc: datetime) -> int:
    """Giờ hiện tại theo "giờ server viết như UTC" (cùng hệ với ``time`` của MT5)."""
    return int(now_utc.astimezone(tz).replace(tzinfo=UTC).timestamp())


@dataclass
class _Sec:
    bid: float
    ask: float
    bid_low: float
    ask_high: float
    spread_max: int
    ticks: int


@dataclass
class Collected:
    seconds: list[dict[str, Any]]
    dropped: dict[str, int]
    next_cursor: int
    skipped_gap_s: int = 0


@dataclass
class QuoteCollector:
    reader: Mt5Reader
    tz: ZoneInfo
    point: float
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    cursor: int | None = None  # giây server đầu tiên chưa gửi

    def collect(self) -> Collected:
        if not (math.isfinite(self.point) and self.point > 0):
            raise Mt5Error("Không có point hợp lệ của symbol: không gom được giá")
        snow = server_now(self.tz, self.now())
        skipped = 0
        cursor = self.cursor if self.cursor is not None else snow - START_BACK_S
        if cursor < snow - MAX_GAP_S:
            skipped = snow - MAX_GAP_S - cursor
            cursor = snow - MAX_GAP_S
        rows = self.reader.ticks_from(cursor, FETCH_TICKS)
        if not rows:
            last = self.reader.last_tick_msc()
            if last is not None and last > (cursor + EMPTY_SKEW_S) * 1000:
                # Có tick sau mốc mà copy_ticks_from trả rỗng: thư viện hiểu mốc lệch giờ.
                raise TickRequestMismatch(
                    "MT5 không trả tick dù có tick sau mốc đã xin: tắt giá sống, nến vẫn chạy"
                )
        dropped: dict[str, int] = {}
        secs: dict[int, _Sec] = {}
        drops_by_sec: dict[int, dict[str, int]] = {}
        prev: tuple[int, float, float] | None = None
        newest = None
        for r in rows:
            msc = int(r["time_msc"])
            if msc < cursor * 1000 - REQUEST_SKEW_TOLERANCE_S * 1000:
                raise TickRequestMismatch(
                    "MT5 trả tick sớm hơn mốc đã xin "
                    f"({(cursor * 1000 - msc) / 1000:.0f} giây): tắt giá sống, nến vẫn chạy"
                )
            if msc < cursor * 1000:
                continue  # trước mốc (cùng giây đã gửi): bỏ qua, không đếm
            s = msc // 1000
            bid, ask = float(r["bid"]), float(r["ask"])
            reason = None
            if not (math.isfinite(bid) and math.isfinite(ask) and bid > 0 and ask > 0):
                reason = "NON_POSITIVE"
            elif bid > ask:
                reason = "CROSSED"
            elif prev is not None and msc < prev[0]:
                reason = "OUT_OF_ORDER"
            elif prev is not None and (msc, bid, ask) == prev:
                reason = "DUPLICATE"
            if reason:
                d = drops_by_sec.setdefault(s, {})
                d[reason] = d.get(reason, 0) + 1
                continue
            prev = (msc, bid, ask)
            newest = s if newest is None else max(newest, s)
            sp = int(round((ask - bid) / self.point))
            cur = secs.get(s)
            if cur is None:
                secs[s] = _Sec(bid, ask, bid, ask, sp, 1)
            else:
                cur.bid, cur.ask = bid, ask
                cur.bid_low = min(cur.bid_low, bid)
                cur.ask_high = max(cur.ask_high, ask)
                cur.spread_max = max(cur.spread_max, sp)
                cur.ticks += 1
        limit = snow - SETTLE_S
        if len(rows) >= FETCH_TICKS and newest is not None:
            limit = min(limit, newest - 1)  # còn tick chưa đọc: chỉ chốt giây chắc chắn đủ
        elif newest is not None:
            limit = max(limit, newest - 1)
        final = [s for s in sorted(set(secs) | set(drops_by_sec)) if s <= limit]
        if len(final) > MAX_SECONDS_PER_POST:
            final = final[:MAX_SECONDS_PER_POST]  # phần còn lại gửi ở vòng sau
            limit = final[-1]
        out: list[dict[str, Any]] = []
        for s in final:
            for k, v in drops_by_sec.get(s, {}).items():
                dropped[k] = dropped.get(k, 0) + v
            q = secs.get(s)
            if q is None:
                continue
            t = server_epoch_to_utc(s, self.tz)
            if t is None:
                dropped["AMBIGUOUS_TIME"] = dropped.get("AMBIGUOUS_TIME", 0) + q.ticks
                continue
            out.append({
                "t": t.isoformat(), "bid": q.bid, "ask": q.ask, "bid_low": q.bid_low,
                "ask_high": q.ask_high, "spread_max_points": q.spread_max, "ticks": q.ticks,
            })
        return Collected(out, dropped, max(cursor, limit + 1), skipped)

@dataclass
class TzWatch:
    """1A-C08: phát hiện độ lệch giờ server đổi khi đang chạy (không chỉ lúc ``check``)."""

    tz: ZoneInfo
    need: int = 3
    min_span_s: float = 60.0
    blocked: bool = False
    last_offset: int | None = None
    # ING-16: lệch đồng hồ server MT5 (giây) ngoài độ lệch giờ chẵn, đo trên tick vừa tới
    last_residual_s: float | None = None
    _bad: list[float] = field(default_factory=list)
    _good: int = 0
    _prev: float | None = None

    @property
    def paused(self) -> bool:
        """Đang nghi (đã thấy lệch, chưa khớp lại) hoặc đã chặn hẳn: không gửi gì."""
        return self.blocked or bool(self._bad)

    def observe(self, tick_server_epoch: float | None, now_utc: datetime) -> None:
        if tick_server_epoch is None:
            return
        prev, self._prev = self._prev, tick_server_epoch
        if prev is None or tick_server_epoch == prev:
            # Không có tick MỚI từ lần đọc trước: không biết tick này cũ bao lâu. So "khác" chứ
            # không "lớn hơn": broker lùi giờ thì tick mới có giờ server NHỎ hơn tick trước.
            return
        off = detect_offset_hours(tick_server_epoch, now_utc.timestamp())
        if off is None:
            return
        self.last_offset = off
        self.last_residual_s = round(tick_server_epoch - now_utc.timestamp() - off * 3600, 1)
        expected = tz_offset_hours(self.tz, now_utc)
        if off == expected:
            self._good += 1
            if not self.blocked or self._good >= self.need:
                self.blocked = False
                self._bad.clear()
            return
        self._good = 0
        self._bad.append(now_utc.timestamp())
        self._bad = self._bad[-self.need:]
        if len(self._bad) >= self.need and self._bad[-1] - self._bad[0] >= self.min_span_s:
            self.blocked = True
