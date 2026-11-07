"""MT-12 + GW-09: ảnh chụp danh tính terminal, tài khoản và symbol, đọc TRỰC TIẾP mỗi nhịp tim.

Chỉ dùng hàm đọc (``terminal_info``, ``account_info``, ``symbol_info`` — đã có trong
``READ_ONLY_FUNCTIONS``). Không cache từ lúc ``check``: người dùng có thể đổi tài khoản trong
terminal khi Gateway đang chạy, nhịp tim phải báo đúng tài khoản ĐANG đăng nhập (MT-14 dựa vào đó).

Nguyên tắc "không bịa số liệu":
- Đọc lỗi / chưa đăng nhập (``login`` ≤ 0) → phần đó là ``None``; không dùng giá trị cũ.
- Số không hữu hạn (NaN/Inf) hoặc sai kiểu → ``None`` cho đúng trường đó.
- ``margin_level`` khi ``margin`` = 0 (không có vị thế): MT5 trả 0 nhưng thực chất không xác định
  → ``None``.
- Phí commission: thư viện MT5 không cung cấp qua ``symbol_info`` → không gửi (không đoán).
"""

from __future__ import annotations

import math
from typing import Any

from mt5_gateway.reader import ACCOUNT_TYPES, Mt5Reader

MAX_TEXT = 256


def _num(x: Any) -> float | None:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    v = float(x)
    return v if math.isfinite(v) else None


def _int(x: Any, *, min_value: int | None = None) -> int | None:
    if isinstance(x, bool) or not isinstance(x, int):
        return None
    if min_value is not None and x < min_value:
        return None
    return int(x)


def _text(x: Any) -> str | None:
    if not isinstance(x, str):
        return None
    s = x.strip()
    return s[:MAX_TEXT] if s else None


def identity(reader: Mt5Reader) -> dict[str, Any] | None:
    """Danh tính MT5 = ``(login, server)`` do terminal báo. ``None`` nếu không đọc được."""
    try:
        acc = reader.mt5.account_info()
    except Exception:
        return None
    if acc is None:
        return None
    login = _int(getattr(acc, "login", None), min_value=1)
    server = _text(getattr(acc, "server", None))
    if login is None or server is None:
        return None  # chưa đăng nhập / dữ liệu lạ: không có danh tính
    try:
        term = reader.mt5.terminal_info()
    except Exception:
        term = None
    return {
        "login": login,
        "server": server,
        "company": _text(getattr(acc, "company", None)),
        "account_type": ACCOUNT_TYPES.get(getattr(acc, "trade_mode", -1), "UNKNOWN"),
        "terminal_name": _text(getattr(term, "name", None)),
        "terminal_path": _text(getattr(term, "path", None)),
    }


def account(reader: Mt5Reader) -> dict[str, Any] | None:
    """GW-09: số liệu tài khoản (chỉ đọc). ``None`` nếu không đọc được."""
    try:
        acc = reader.mt5.account_info()
    except Exception:
        return None
    if acc is None or _int(getattr(acc, "login", None), min_value=1) is None:
        return None
    margin = _num(getattr(acc, "margin", None))
    level = _num(getattr(acc, "margin_level", None))
    return {
        "currency": _text(getattr(acc, "currency", None)),
        "balance": _num(getattr(acc, "balance", None)),
        "equity": _num(getattr(acc, "equity", None)),
        "margin": margin,
        "margin_free": _num(getattr(acc, "margin_free", None)),
        "margin_level": level if margin is not None and margin > 0 else None,
        "leverage": _int(getattr(acc, "leverage", None), min_value=1),
        "trade_allowed": getattr(acc, "trade_allowed", None)
        if isinstance(getattr(acc, "trade_allowed", None), bool)
        else None,
    }


def symbol(reader: Mt5Reader, broker_symbol: str) -> dict[str, Any] | None:
    """Thông số symbol (gồm GW-09: stops/freeze level, swap). ``None`` nếu không đọc được."""
    try:
        info = reader.symbol_info()
    except Exception:
        return None
    if info is None:
        return None
    digits = _int(getattr(info, "digits", None), min_value=0)
    point = _num(getattr(info, "point", None))
    base = {
        "contract_size": _num(getattr(info, "trade_contract_size", None)),
        "volume_min": _num(getattr(info, "volume_min", None)),
        "volume_max": _num(getattr(info, "volume_max", None)),
        "volume_step": _num(getattr(info, "volume_step", None)),
    }
    if digits is None or point is None or point <= 0 or any(v is None for v in base.values()):
        return None  # thiếu thông số cốt lõi: không gửi nửa vời
    return {
        "broker_symbol": broker_symbol,
        "digits": digits,
        "point": point,
        **base,
        "currency_profit": _text(getattr(info, "currency_profit", None)),
        "stops_level": _int(getattr(info, "trade_stops_level", None), min_value=0),
        "freeze_level": _int(getattr(info, "trade_freeze_level", None), min_value=0),
        "swap_mode": _int(getattr(info, "swap_mode", None), min_value=0),
        "swap_long": _num(getattr(info, "swap_long", None)),
        "swap_short": _num(getattr(info, "swap_short", None)),
        "swap_rollover3days": _int(getattr(info, "swap_rollover3days", None), min_value=0),
    }
