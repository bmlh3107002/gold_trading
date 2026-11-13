"""Proxy kỳ vọng lãi suất Fed (GĐ1 bước 9c — ING-27, DEC-04).

Thiết kế + lý do: ``docs/thiet-ke/18-h15-lai-suat.md`` mục 9.

``chênh lệch = lợi suất 2 năm (UST_CMT_2Y) − lãi suất Fed hiệu dụng (EFFR)``, cùng **một ngày
quan sát**, từ H.15 (``fed_h15``). Theo DEC-04 (người dùng chốt 2026-11-07):

- chênh lệch < 0 → ``LEANS_CUT`` (thị trường nghiêng về Fed cắt lãi);
- chênh lệch > 0 → ``LEANS_HOLD_OR_HIKE`` (nghiêng về giữ / tăng);
- = 0 → ``FLAT``.

Đây là **proxy**, không phải xác suất: không quy đổi ra "% khả năng cắt lãi" (chưa hiệu chỉnh).
Tính khi đọc từ bản ghi point-in-time (không lưu) → replay tại cùng ``as_of`` cho cùng kết quả.

An toàn:
- Chỉ ghép hai số **cùng ngày**; ngày gần nhất có cả hai số (thị trường trái phiếu đóng mà EFFR
  vẫn có → lùi về ngày trước). Không bao giờ trộn ngày.
- Không có ngày chung, hoặc ngày chung cũ hơn ``MAX_AGE`` so với ``as_of`` → ``INSUFFICIENT_DATA``
  (không đưa số cũ ra như số mới).
- Số học bằng ``Decimal`` trên chuỗi H.15 (không sai số dấu phẩy động).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation

PROXY_VERSION = "fed-proxy-2026.11.13"
SOURCE = "fed_h15"
TWO_YEAR, EFFR = "UST_CMT_2Y", "EFFR"
# Số mới nhất bình thường là ngày làm việc trước (H.15 trễ 1 ngày); lễ + cuối tuần ~4–5 ngày.
# Cùng mức với data_ttl của nguồn (7 ngày).
MAX_AGE = timedelta(days=7)
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True)
class FedProxy:
    as_of: datetime
    status: str                    # OK / INSUFFICIENT_DATA
    reason: str | None             # lý do khi INSUFFICIENT_DATA
    observation_date: date | None
    two_year: str | None           # % năm, đúng chuỗi H.15
    effr: str | None
    spread_pp: str | None          # điểm phần trăm, vd. "0.85"
    spread_bp: int | None          # điểm cơ bản, vd. 85
    lean: str | None               # LEANS_CUT / LEANS_HOLD_OR_HIKE / FLAT
    version: str = PROXY_VERSION
    label: str = ("proxy kỳ vọng lãi suất Fed: lợi suất 2 năm − lãi suất Fed hiệu dụng "
                  "(không phải xác suất)")


def _num(v) -> Decimal | None:
    if v is None:
        return None
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def _insufficient(as_of: datetime, reason: str, day: date | None = None) -> FedProxy:
    return FedProxy(as_of, INSUFFICIENT_DATA, reason, day, None, None, None, None, None)


def fed_expectation_proxy(store, as_of: datetime) -> FedProxy:
    if as_of.tzinfo is None:
        raise ValueError("as_of phải có múi giờ (UTC)")
    as_of = as_of.astimezone(UTC)
    by: dict[str, dict[str, tuple[Decimal, str]]] = {TWO_YEAR: {}, EFFR: {}}
    for r in store.as_of(as_of, source=SOURCE, kind="macro",
                         event_from=as_of - timedelta(days=60)):
        p = r.payload
        s = p.get("series")
        if s not in by or r.event_time > as_of:
            continue
        v = _num(p.get("value")) if p.get("value_status") == "AVAILABLE" else None
        if v is not None:
            by[s][p["date"]] = (v, p["value"])
    common = sorted(set(by[TWO_YEAR]) & set(by[EFFR]))
    if not common:
        return _insufficient(as_of, "NO_COMMON_DAY")
    day = date.fromisoformat(common[-1])
    # Hết ngày quan sát (New York) phải trong MAX_AGE; dùng ngày lịch (UTC) là đủ thô cho 7 ngày.
    if as_of.date() - day > MAX_AGE:
        return _insufficient(as_of, "STALE", day)
    (y2, y2s), (ff, ffs) = by[TWO_YEAR][common[-1]], by[EFFR][common[-1]]
    spread = y2 - ff
    lean = "LEANS_CUT" if spread < 0 else ("LEANS_HOLD_OR_HIKE" if spread > 0 else "FLAT")
    return FedProxy(as_of, "OK", None, day, y2s, ffs, format(spread, "f"),
                    int((spread * 100).to_integral_value()), lean)
