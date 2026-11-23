"""Cơ sở dữ liệu RIÊNG của backtest (GĐ6 bước 2 — thiết kế 39 mục 4).

- Mọi lệnh backtest đọc / ghi **chỉ** ``GT_BACKTEST_DATABASE_URL``. Thiếu → dừng.
- **Trùng** cơ sở dữ liệu của hệ thống đang chạy (``DATABASE_URL``) → **từ chối**. So theo
  (máy, cổng, tên DB) sau khi chuẩn hóa — khác người dùng / mật khẩu / trình điều khiển vẫn là
  trùng; SQLite so theo đường dẫn tuyệt đối. Không có cờ nào bỏ qua kiểm tra này.
- Khởi tạo schema: PostgreSQL / TimescaleDB → đúng Alembic của backend (tạo DB nếu chưa có);
  SQLite (chỉ dùng thử / test) → ``create_all``.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ENV_URL = "GT_BACKTEST_DATABASE_URL"
LIVE_ENV_URL = "DATABASE_URL"


class BacktestDbError(RuntimeError):
    pass


def _key(url: str) -> tuple:
    u = make_url(url)
    backend = u.get_backend_name()
    if backend == "sqlite":
        db = u.database or ""
        if db in ("", ":memory:"):
            return ("sqlite", ":memory:", object())          # bộ nhớ: không bao giờ trùng
        return ("sqlite", str(Path(db).expanduser().resolve()))
    host = (u.host or "localhost").lower()
    if host in ("127.0.0.1", "::1"):
        host = "localhost"
    port = u.port or {"postgresql": 5432}.get(backend)
    return (backend, host, port, u.database)


def same_database(a: str, b: str) -> bool:
    return _key(a) == _key(b)


def resolve_url(env: Mapping[str, str] | None = None) -> str:
    """URL cơ sở dữ liệu backtest, đã kiểm không trùng cơ sở dữ liệu đang chạy."""
    env = os.environ if env is None else env
    url = (env.get(ENV_URL) or "").strip()
    if not url:
        raise BacktestDbError(f"Chưa đặt {ENV_URL} (cơ sở dữ liệu RIÊNG cho backtest)")
    live = (env.get(LIVE_ENV_URL) or "").strip()
    if live and same_database(url, live):
        raise BacktestDbError(
            f"{ENV_URL} trỏ vào CÙNG cơ sở dữ liệu với hệ thống đang chạy — từ chối "
            "(backtest không bao giờ ghi vào cơ sở dữ liệu thật)")
    return url


def alembic_dir() -> Path:
    """Thư mục chứa ``alembic.ini`` (``backend/`` khi phát triển, ``/app`` trong container)."""
    here = Path(__file__).resolve()
    for p in here.parents:
        if (p / "alembic.ini").is_file():
            return p
    raise BacktestDbError("không tìm thấy alembic.ini")


def init_db(url: str, *, env: Mapping[str, str] | None = None,
            run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> str:
    """Tạo schema cho cơ sở dữ liệu backtest. Kiểm lại không trùng DB thật **trước** mọi việc.
    Trả mô tả việc đã làm."""
    env = dict(os.environ if env is None else env)
    live = (env.get(LIVE_ENV_URL) or "").strip()
    if live and same_database(url, live):
        raise BacktestDbError("từ chối khởi tạo: trùng cơ sở dữ liệu đang chạy")
    u = make_url(url)
    if u.get_backend_name() == "sqlite":
        from gold_trading.storage.schema import metadata
        eng = create_engine(url)
        metadata.create_all(eng)
        return "SQLite: create_all"
    created = False
    admin = create_engine(u.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        exists = c.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"),
                           {"n": u.database}).first()
        if not exists:
            name = u.database or ""
            if not name.replace("_", "").isalnum():
                raise BacktestDbError("tên cơ sở dữ liệu chỉ được chữ, số, gạch dưới")
            c.execute(text(f'CREATE DATABASE "{name}"'))
            created = True
    admin.dispose()
    env[LIVE_ENV_URL] = url                       # alembic (migrations/env.py) đọc DATABASE_URL
    r = run(["alembic", "upgrade", "head"], cwd=alembic_dir(), env=env, capture_output=True,
            text=True)
    if r.returncode != 0:
        raise BacktestDbError(f"alembic lỗi: {(r.stderr or r.stdout)[-2000:]}")
    return ("tạo cơ sở dữ liệu + " if created else "") + "alembic upgrade head"
