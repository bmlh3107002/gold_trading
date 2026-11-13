"""Bảng sửa số kỳ trước (ING-19) + cờ "sửa lớn" (1C-C08) — GĐ1 bước 8g-3.

Bộ nạp BEA / DOL đã lưu mỗi lần nguồn đổi số thành một **revision mới** (không viết lại quá
khứ). Mô-đun này chỉ **đọc**: tại ``as_of``, liệt kê các số có revision > 0 đã biết, so với
revision ngay trước, gắn cờ ``LARGE_REVISION`` khi độ lệch tuyệt đối ≥ ngưỡng của series.

Ngưỡng là **chính sách có phiên bản** (``REVISION_POLICY_VERSION``), giá trị khởi đầu chưa hiệu
chỉnh, lý do ở ``docs/thiet-ke/17-lich-kinh-te-hop-nhat.md`` mục 5. Cờ chỉ để **cảnh báo** —
GĐ1 không dùng cờ này để chặn hay cho phép giao dịch. Series không có ngưỡng → không gắn cờ,
ghi ``NO_THRESHOLD`` (không đoán ngưỡng). Giá trị không phải số / không có số → không tính độ
lệch (``NOT_COMPARABLE``), không bao giờ coi "không có số" là 0 (1C-C01).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

REVISION_POLICY_VERSION = "revision-policy-2026.11.13"

# Ngưỡng tuyệt đối theo đơn vị của series.
LARGE_REVISION: dict[str, Decimal] = {
    "A191RL": Decimal("1.0"),     # GDP thực % năm hóa (điểm %)
    "DPCERGM": Decimal("0.2"),    # PCE % tháng (điểm %)
    "DPCCRGM": Decimal("0.2"),    # PCE lõi % tháng (điểm %)
    "ICSA": Decimal("10000"),     # đơn lần đầu (người)
    "IC4WSA": Decimal("5000"),    # trung bình 4 tuần (người)
    "CCSA": Decimal("30000"),     # đơn tiếp tục (người)
}
VALUE_SOURCES = ("bea_nipa", "dol_claims")


def _num(v) -> Decimal | None:
    if v is None:
        return None
    try:
        d = Decimal(str(v).replace(",", ""))
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


@dataclass(frozen=True)
class Revision:
    source: str
    logical_key: str
    series: str | None
    revision: int
    previous_value: str | None
    value: str | None
    delta: str | None             # chuỗi thập phân, None nếu không so được
    known_at: datetime
    flag: str                     # LARGE_REVISION / SMALL_REVISION / NO_THRESHOLD / NOT_COMPARABLE
    threshold: str | None
    policy_version: str = REVISION_POLICY_VERSION


def classify(series: str | None, prev, cur) -> tuple[str, Decimal | None]:
    a, b = _num(prev), _num(cur)
    if a is None or b is None:
        return "NOT_COMPARABLE", None
    delta = b - a
    th = LARGE_REVISION.get(series or "")
    if th is None:
        return "NO_THRESHOLD", delta
    return ("LARGE_REVISION" if abs(delta) >= th else "SMALL_REVISION"), delta


def revisions(store, as_of: datetime, *, since: timedelta = timedelta(days=60),
              sources=VALUE_SOURCES) -> list[Revision]:
    """Các lần sửa số đã biết tại ``as_of`` mà bản sửa được biết trong ``since`` gần nhất."""
    if as_of.tzinfo is None:
        raise ValueError("as_of phải có múi giờ (UTC)")
    as_of = as_of.astimezone(UTC)
    out: list[Revision] = []
    for src in sources:
        for r in store.as_of(as_of, source=src, kind="macro"):
            if r.revision == 0:
                continue
            hist = [h for h in store.history(src, r.logical_key, as_of) if h.known_at <= as_of]
            hist.sort(key=lambda h: h.revision)
            for prev, cur in zip(hist, hist[1:], strict=False):
                if cur.known_at < as_of - since:
                    continue
                series = cur.payload.get("series")
                flag, delta = classify(series, prev.payload.get("value"),
                                       cur.payload.get("value"))
                th = LARGE_REVISION.get(series or "")
                out.append(Revision(
                    source=src, logical_key=cur.logical_key, series=series,
                    revision=cur.revision, previous_value=prev.payload.get("value"),
                    value=cur.payload.get("value"),
                    delta=None if delta is None else format(delta, "f"),
                    known_at=cur.known_at, flag=flag,
                    threshold=None if th is None else str(th)))
    return sorted(out, key=lambda x: (x.known_at, x.source, x.logical_key, x.revision))
