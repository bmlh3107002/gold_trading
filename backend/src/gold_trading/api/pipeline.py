"""API trang "Pipeline" (GĐ2 bước 5 — DSH-08). Chỉ đọc; mọi người dùng đã đăng nhập (như trang
"Nguồn dữ liệu"). Không có thông tin tài khoản / khóa: loại job, sự kiện (mã nguồn giá đã băm),
trạng thái, mã lỗi ngắn."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from gold_trading.common.time import utcnow
from gold_trading.orchestrator import overview as OV

JobStateOut = Literal["PENDING", "RUNNING", "SUCCEEDED", "FAILED", "DEAD", "NO_HANDLER",
                      "SUPERSEDED"]


class JobOut(BaseModel):
    job_type: str
    analyzer_version: str
    event_type: str
    subject: str
    created_at: datetime
    state: JobStateOut
    state_at: datetime
    attempts: int = Field(description="Số lần đã chạy thật")
    error_code: str | None = Field(description="Mã lỗi ngắn (tên loại lỗi), không có thông điệp")
    output_ref: str | None


class JobCountOut(BaseModel):
    job_type: str
    state: JobStateOut
    count: int


class LaneOut(BaseModel):
    lane: str = Field(description="spread | events")
    started_at: datetime | None
    last_ok_at: datetime | None
    backlog_since: datetime | None = Field(description="Sự kiện làn nhanh chờ sớm nhất")
    ok: bool = Field(description="Chạy xong trong ngân sách 10 giây và không tồn đọng quá hạn")


class PipelineResponse(BaseModel):
    as_of: datetime
    orchestrator_enabled: bool = Field(description="False: GT_ORCHESTRATOR=0 hoặc không chạy "
                                                   "analyst")
    window_hours: int
    dead_window_days: int
    counts: list[JobCountOut]
    open_jobs: list[JobOut]
    stuck_jobs: int = Field(description="Job chưa xong quá 2 phút")
    dead_letter: list[JobOut]
    recent: list[JobOut]
    lanes: list[LaneOut]
    budget_breaches: int = Field(description="Số lần ghi lệnh cấm chậm hơn 10 giây từ khi bật")
    last_latency_ms: int | None


def _job(r) -> JobOut:
    return JobOut(job_type=r.job.job_type, analyzer_version=r.job.analyzer_version,
                  event_type=r.event_type, subject=r.subject, created_at=r.job.created_at,
                  state=r.last.state.value, state_at=r.last.at, attempts=r.attempts,
                  error_code=r.last.error_code, output_ref=r.last.output_ref)


def pipeline_router(orch_getter: Callable[[], object | None],
                    monitor_getter: Callable[[], object | None],
                    now: Callable[[], datetime] | None = None) -> APIRouter:
    r = APIRouter(prefix="/api/pipeline", tags=["pipeline"])

    @r.get("", response_model=PipelineResponse)
    def pipeline() -> PipelineResponse:
        as_of = (now or utcnow)()
        orch = orch_getter()
        mon = monitor_getter()
        ov = OV.build(orch, as_of) if orch is not None else OV.PipelineOverview(as_of)
        return PipelineResponse(
            as_of=as_of, orchestrator_enabled=orch is not None,
            window_hours=int(OV.WINDOW.total_seconds() // 3600),
            dead_window_days=OV.DEAD_WINDOW.days,
            counts=[JobCountOut(job_type=t, state=s, count=n)
                    for (t, s), n in sorted(ov.counts.items())],
            open_jobs=[_job(x) for x in ov.open], stuck_jobs=ov.stuck,
            dead_letter=[_job(x) for x in ov.dead], recent=[_job(x) for x in ov.recent],
            lanes=[LaneOut(**x) for x in (mon.snapshot(as_of) if mon is not None else [])],
            budget_breaches=getattr(mon, "budget_breaches", 0),
            last_latency_ms=getattr(mon, "last_latency_ms", None))

    return r
