"""MT-05: nguồn giá (feed) = một (server broker, symbol broker). DEC-14: mỗi tài khoản phân tích
theo giá broker của chính mình; cùng server + symbol thì dùng chung một nguồn; KHÔNG BAO GIỜ trộn
giá giữa hai nguồn.

``feed_id`` tính được từ chính danh tính (không phụ thuộc thứ tự tạo) nên hai Gateway của cùng
broker luôn ghi vào cùng một nguồn mà không cần khóa.
"""

from __future__ import annotations

import hashlib

from gold_trading.storage.schema import LEGACY_FEED

__all__ = ["LEGACY_FEED", "feed_id_for"]


def feed_id_for(server: str, broker_symbol: str) -> str:
    """Server không phân biệt hoa/thường (cùng MT5, xem MT-13); symbol broker giữ nguyên chữ."""
    for v in (server, broker_symbol):
        # Ký tự điều khiển (vd. NUL dùng làm dấu phân cách) / khoảng trắng đầu-cuối có thể làm
        # hai nguồn khác nhau ra cùng một mã → không chấp nhận.
        if not v or v != v.strip() or not v.isprintable():
            raise ValueError("Nguồn giá cần server và symbol broker hợp lệ")
    key = f"{server.lower()}\0{broker_symbol}".encode()
    return "pf_" + hashlib.sha256(key).hexdigest()[:24]
