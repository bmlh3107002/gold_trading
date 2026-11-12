"""Cấu hình Gateway: đọc từ file ``gateway.env`` (cạnh nơi chạy lệnh) và biến môi trường."""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from pathlib import Path

MIN_TOKEN_LEN = 24
# ING-14: khung được đồng bộ. M15 bắt buộc (R1 kiểm múi giờ trên M15); H1/H4/D1 đọc thẳng từ MT5,
# không tự ghép từ M15 (nến H4/D1 căn theo giờ server broker).
SUPPORTED_TIMEFRAMES = ("M15", "H1", "H4", "D1")
DEFAULT_TIMEFRAMES = "M15,H1,H4,D1"
# Số nến lịch sử tối đa cho khung lớn. Xin quá nhiều (vd 5.000 nến D1 ≈ 20 năm) làm MT5 đứng rất
# lâu để tải từ server (phát hiện 2026-11-07 trên máy người dùng). Đủ cho bối cảnh khung lớn.
HIGHER_HISTORY_BARS = {"H1": 2000, "H4": 1000, "D1": 500}


def history_bars_for(cfg: Config, tf: str) -> int:
    """M15 dùng ``GT_HISTORY_BARS``; khung lớn dùng mức trần riêng (không vượt GT_HISTORY_BARS)."""
    if tf == "M15":
        return cfg.history_bars
    return min(cfg.history_bars, HIGHER_HISTORY_BARS[tf])


@dataclass(frozen=True)
class Config:
    backend_url: str
    token: str
    broker_symbol: str
    symbol: str  # symbol chuẩn của hệ thống
    server_tz: str
    terminal_path: str | None
    history_bars: int
    poll_seconds: float
    heartbeat_seconds: float
    gateway_id: str
    timeframes: tuple[str, ...] = ("M15",)


def read_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def parse_timeframes(raw: str) -> tuple[str, ...]:
    """``"M15,H1,H4,D1"`` → tuple theo thứ tự chuẩn. Sai tên thì báo lỗi, không đoán."""
    names = {x.strip().upper() for x in raw.split(",") if x.strip()}
    bad = names - set(SUPPORTED_TIMEFRAMES)
    if bad:
        raise ValueError(
            f"GT_TIMEFRAMES có khung không hỗ trợ: {', '.join(sorted(bad))} "
            f"(chỉ dùng {', '.join(SUPPORTED_TIMEFRAMES)})"
        )
    names.add("M15")
    return tuple(t for t in SUPPORTED_TIMEFRAMES if t in names)


def default_gateway_id(name: str | None = None) -> str:
    """Tên máy (một terminal) hoặc ``<tên máy>-<tên terminal>`` (nhiều terminal, MT-15)."""
    host = socket.gethostname() or "gateway"
    return (f"{host}-{name}" if name else host)[:64]


def load(
    env_file: Path = Path("gateway.env"), *, use_environ: bool = True, name: str | None = None
) -> Config:
    """``use_environ=False`` (chế độ nhiều terminal): CHỈ đọc file của terminal đó — một biến
    ``GT_INGEST_TOKEN`` đặt chung trong môi trường sẽ đè lên mọi terminal (chung token)."""
    file_vals = read_env_file(env_file)

    def get(key: str, default: str = "") -> str:
        if use_environ:
            return os.environ.get(key, file_vals.get(key, default))
        return file_vals.get(key, default)

    return Config(
        backend_url=get("GT_BACKEND_URL", "http://localhost:8080"),
        token=get("GT_INGEST_TOKEN"),
        broker_symbol=get("GT_BROKER_SYMBOL", "XAUUSD"),
        symbol=get("GT_SYMBOL", "XAUUSD"),
        server_tz=get("GT_SERVER_TZ"),
        terminal_path=get("GT_MT5_PATH") or None,
        history_bars=int(get("GT_HISTORY_BARS", "5000")),
        poll_seconds=float(get("GT_POLL_SECONDS", "5")),
        heartbeat_seconds=float(get("GT_HEARTBEAT_SECONDS", "10")),
        gateway_id=get("GT_GATEWAY_ID", default_gateway_id(name)),
        timeframes=parse_timeframes(get("GT_TIMEFRAMES", DEFAULT_TIMEFRAMES)),
    )
