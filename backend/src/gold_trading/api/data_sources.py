"""API trang "Nguồn dữ liệu" (GĐ1 bước 10e, DSH-09). Chỉ đọc; mọi người dùng đã đăng nhập.

Không có thông tin tài khoản / khóa API: chỉ tên nguồn, trạng thái, thời điểm, mã lỗi ngắn (ING-30
đã bảo đảm mã lỗi không chứa URL / khóa) và số cách ly.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from gold_trading.common.time import utcnow
from gold_trading.ingestion.source_overview import QUARANTINE_WINDOW, overview


class DataSourceOut(BaseModel):
    name: str
    kind: Literal["calendar", "news", "macro", "positioning"]
    provider: str
    terms_status: str
    enabled: bool
    status: Literal["HEALTHY", "STALE", "MISSING", "INVALID"]
    reason: str = Field(description="Mã lý do trạng thái (OK, FETCH_TTL_EXPIRED, NEVER_CHECKED…)")
    flags: list[str]
    last_check_at: datetime | None
    last_ok_at: datetime | None
    last_error_code: str | None
    failures_since_ok: int
    latest_event_at: datetime | None
    fetch_ttl_seconds: int
    data_ttl_seconds: int | None
    receive_age_seconds: int | None = Field(description="Từ lần nhận OK cuối tới as_of (giây)")
    data_age_seconds: int | None = Field(description="Từ event_time mới nhất tới as_of (giây)")
    quarantine_7d: int
    quarantine_total: int


class DataSourcesResponse(BaseModel):
    as_of: datetime
    runner_enabled: bool = Field(description="False: GT_EXTERNAL_SOURCES=0, không nạp nguồn ngoài")
    quarantine_window_days: int
    sources: list[DataSourceOut]


def data_sources_router(runner_getter: Callable[[], object | None],
                        now: Callable[[], datetime] | None = None) -> APIRouter:
    r = APIRouter(prefix="/api/data-sources", tags=["data-sources"])

    @r.get("", response_model=DataSourcesResponse)
    def data_sources() -> DataSourcesResponse:
        as_of = (now or utcnow)()
        runner = runner_getter()
        reg = getattr(runner, "registry", None)
        if runner is None or reg is None:
            return DataSourcesResponse(as_of=as_of, runner_enabled=False,
                                       quarantine_window_days=QUARANTINE_WINDOW.days, sources=[])
        rows = overview(reg, runner.store, runner.check_log, as_of)
        return DataSourcesResponse(
            as_of=as_of, runner_enabled=True, quarantine_window_days=QUARANTINE_WINDOW.days,
            sources=[DataSourceOut(**{**r.__dict__, "flags": list(r.flags)}) for r in rows])

    return r
