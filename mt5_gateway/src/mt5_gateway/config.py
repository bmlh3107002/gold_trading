"""Cấu hình Gateway: đọc từ file ``gateway.env`` (cạnh nơi chạy lệnh) và biến môi trường."""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from pathlib import Path

MIN_TOKEN_LEN = 24


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


def load(env_file: Path = Path("gateway.env")) -> Config:
    file_vals = read_env_file(env_file)

    def get(key: str, default: str = "") -> str:
        return os.environ.get(key, file_vals.get(key, default))

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
        gateway_id=get("GT_GATEWAY_ID", socket.gethostname()[:64] or "gateway"),
    )
