"""Trạng thái pipeline / job / dead-letter cho trang web (GĐ2 bước 5 — DSH-08).

Chỉ đọc nhật ký job (chỉ-thêm) + trạng thái làn nhanh trong bộ nhớ. Không có thông tin tài khoản /
khóa: chỉ loại job, loại + chủ thể sự kiện (mã nguồn giá đã băm, khóa bản ghi), trạng thái, mã lỗi
ngắn (bộ điều phối chỉ ghi tên loại lỗi, không ghi thông điệp).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from gold_trading.orchestrator.model import TERMINAL, JobRow, JobState

WINDOW = timedelta(hours=24)        # đếm + danh sách gần đây
DEAD_WINDOW = timedelta(days=7)     # dead-letter
RECENT_LIMIT = 50
DEAD_LIMIT = 100
OPEN_LIMIT = 100
STUCK_AFTER = timedelta(minutes=2)  # job chưa xong quá chừng này → "kẹt" (cảnh báo)


@dataclass
class PipelineOverview:
    as_of: datetime
    counts: dict[tuple[str, str], int] = field(default_factory=dict)
    recent: list[JobRow] = field(default_factory=list)
    dead: list[JobRow] = field(default_factory=list)
    open: list[JobRow] = field(default_factory=list)
    stuck: int = 0


def build(orch, now: datetime) -> PipelineOverview:
    rows = orch.job_rows(now - WINDOW)
    ov = PipelineOverview(as_of=now)
    ov.counts = dict(Counter((r.job.job_type, r.last.state.value) for r in rows))
    ov.recent = rows[:RECENT_LIMIT]
    ov.dead = orch.job_rows(now - DEAD_WINDOW, states=[JobState.DEAD], limit=DEAD_LIMIT)
    opened = [r for r in rows if r.last.state not in TERMINAL]
    ov.open = opened[:OPEN_LIMIT]
    ov.stuck = sum(1 for r in opened if now - r.job.created_at > STUCK_AFTER)
    return ov
