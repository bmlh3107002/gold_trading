"""Mức quan trọng sự kiện lịch kinh tế + cửa sổ rủi ro cơ bản — có phiên bản (ING-20, GĐ1 8g-2).

Thiết kế + lý do: ``docs/thiet-ke/17-lich-kinh-te-hop-nhat.md``. Đây là **chính sách**, không
phải dữ liệu nguồn: không ghi vào bản ghi của nguồn; bảng lịch hợp nhất tính ra khi đọc và
ghi kèm ``POLICY_VERSION`` để biết quyết định nào dùng bảng nào. Đổi bất kỳ con số / mức nào ở
đây → **đổi ``POLICY_VERSION``** + ghi lý do vào file thiết kế (test chặn quên).

Các con số cửa sổ là **giá trị khởi đầu chưa hiệu chỉnh** trên dữ liệu thật; hiệu chỉnh khi có
dữ liệu giá quanh các lần công bố (GĐ2 / GĐ6). Sự kiện lạ → HIGH (hướng an toàn).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

POLICY_VERSION = "event-policy-2026.11.13-bls"


class Importance(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass(frozen=True)
class Window:
    before: timedelta
    after: timedelta


# Cửa sổ quanh giờ công bố đã xác nhận. Sự kiện chưa chắc giờ → cả ngày (giờ New York).
WINDOWS: dict[Importance, Window] = {
    Importance.HIGH: Window(timedelta(minutes=15), timedelta(minutes=15)),
    Importance.MEDIUM: Window(timedelta(minutes=5), timedelta(minutes=10)),
    Importance.LOW: Window(timedelta(0), timedelta(minutes=5)),
}

# (event, biến thể) → (mức, lý do). Biến thể None = mọi biến thể chưa liệt kê riêng.
_TABLE: dict[tuple[str, str | None], tuple[Importance, str]] = {
    ("FOMC_STATEMENT", None): (Importance.HIGH, "quyết định lãi suất của Fed"),
    ("FOMC_PRESS_CONFERENCE", None): (Importance.HIGH, "họp báo sau quyết định lãi suất"),
    ("FOMC_MINUTES", None): (Importance.MEDIUM, "biên bản họp: thông tin cũ 3 tuần, ít bất ngờ"),
    ("BEA_PIO", None): (Importance.HIGH, "chứa PCE — thước đo lạm phát Fed đặt mục tiêu"),
    ("BEA_GDP", "ADVANCE"): (Importance.HIGH, "ước tính GDP đầu tiên của quý"),
    ("BEA_GDP", "SECOND"): (Importance.MEDIUM, "ước tính GDP lần 2: thường sửa nhỏ"),
    ("BEA_GDP", "THIRD"): (Importance.MEDIUM, "ước tính GDP lần 3: thường sửa nhỏ"),
    ("DOL_JOBLESS_CLAIMS", None): (Importance.MEDIUM, "số tuần, biến động nhiều, ít bất ngờ"),
    # Bước 8e (BLS): hai số tác động mạnh nhất tới vàng; PPI thường ít bất ngờ hơn CPI.
    ("BLS_CPI", None): (Importance.HIGH, "lạm phát tiêu dùng — tác động mạnh tới kỳ vọng lãi suất"),
    ("BLS_EMPSIT", None): (Importance.HIGH, "việc làm phi nông nghiệp (NFP) + thất nghiệp"),
    ("BLS_PPI", None): (Importance.MEDIUM, "lạm phát phía sản xuất, thường ít bất ngờ hơn CPI"),
}
UNKNOWN_REASON = "sự kiện chưa có trong bảng → coi là quan trọng cao (an toàn)"


@dataclass(frozen=True)
class Rating:
    importance: Importance
    reason: str
    known: bool
    policy_version: str = POLICY_VERSION


def rate(event: str | None, variant: str | None = None) -> Rating:
    """Mức quan trọng của một sự kiện. Biến thể lạ của sự kiện có bảng riêng theo biến thể
    (vd. GDP ``INITIAL``/``UPDATED``/không rõ) → HIGH (an toàn), không lấy mức thấp hơn."""
    if event is not None:
        if (event, variant) in _TABLE:
            imp, why = _TABLE[(event, variant)]
            return Rating(imp, why, True)
        if (event, None) in _TABLE:
            imp, why = _TABLE[(event, None)]
            return Rating(imp, why, True)
    return Rating(Importance.HIGH, UNKNOWN_REASON, False)


def table_snapshot() -> dict:
    """Toàn bộ chính sách dạng dữ liệu (test dùng để chặn đổi chính sách mà quên đổi phiên bản)."""
    return {
        "windows": {k.value: [w.before.total_seconds(), w.after.total_seconds()]
                    for k, w in WINDOWS.items()},
        "table": {f"{e}|{v}": [i.value, why] for (e, v), (i, why) in sorted(
            _TABLE.items(), key=lambda kv: (kv[0][0], kv[0][1] or ""))},
    }
