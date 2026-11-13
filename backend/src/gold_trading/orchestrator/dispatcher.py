"""Bộ điều phối job (GĐ2 bước 2 — ORC-02, ORC-04, ORC-05, ORC-06; 2-C01..C05).

Thiết kế: ``docs/thiet-ke/25-event-orchestrator.md`` mục 5. Tóm tắt:

- **Bảng định tuyến** sự kiện → loại job (theo mô hình, đặc tả 03). Loại job chưa có bộ xử lý
  (analyst GĐ3) → ghi ``NO_HANDLER`` — không giả kết quả.
- **Debounce** (ORC-04, 2-C03): chỉ áp cho sự kiện "dồn được" (nến, số vĩ mô cập nhật): cùng loại
  job + cùng chủ thể có sự kiện mới hơn → job cũ ``SUPERSEDED``. Sự kiện công bố / lịch / tin
  **không bao giờ** bị debounce.
- **Chạy theo thứ tự nhân quả** của sự kiện (2-C02). Deadline, retry giới hạn, backoff mũ, hết lượt
  → ``DEAD`` (dead-letter) (ORC-05, 2-C04). Lỗi chỉ ghi **mã ngắn** (tên loại lỗi), không bao giờ
  ghi thông điệp.
- **Khởi động lại** (2-C05): job ``RUNNING`` quá deadline (backend tắt giữa chừng) → coi là lần thử
  thất bại ``DEADLINE_EXCEEDED`` rồi xét retry; job đã kết thúc không chạy lại.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from gold_trading.orchestrator.model import (
    TERMINAL,
    Attempt,
    Event,
    EventType,
    Job,
    JobState,
    job_key_for,
)

ROUTER_VERSION = "router-2026.11.14b"
LOOKBACK = timedelta(days=2)          # sự kiện / job xét lại khi khởi động (idempotent)
OVERLAP = timedelta(minutes=15)


@dataclass(frozen=True)
class Route:
    job_type: str
    debounce: bool = False


def routes_for(e: Event) -> tuple[Route, ...]:
    """Bảng định tuyến (đặc tả 03). Đổi bảng → đổi ``ROUTER_VERSION``."""
    t = e.event_type
    if t is EventType.CANDLE_CLOSED:
        # Chủ thể "nguồn:feed:SYMBOL:khung". Vàng M15 → Technical → Regime; cặp USD → Macro.
        parts = e.subject.split(":")
        symbol, tf = (parts[2], parts[3]) if len(parts) == 4 else ("", "")
        if tf != "M15":
            return ()
        if symbol.upper().startswith("XAU"):
            return (Route("TECHNICAL", debounce=True), Route("REGIME", debounce=True))
        return (Route("MACRO", debounce=True),)
    if t is EventType.ACTUAL_RELEASED:
        return (Route("FAST_LANE"), Route("EVENT_CALENDAR"))
    if t is EventType.CALENDAR_UPDATED:
        return (Route("EVENT_CALENDAR"),)
    if t is EventType.MACRO_UPDATED:
        return (Route("MACRO", debounce=True),)
    if t is EventType.POSITIONING_UPDATED:
        return (Route("POSITIONING"),)
    if t is EventType.NEWS_PUBLISHED:
        return (Route("FAST_LANE"), Route("NEWS"))
    if t is EventType.OUTPUT_EXPIRED:
        # ORC-07: kết quả hết hạn mà chưa có kết quả mới → vô hiệu MarketView (GĐ4) + tính lại.
        analyst = e.subject.split(":", 1)[0].upper()
        recompute = (Route(analyst, debounce=True),) if analyst == "TECHNICAL" else ()
        return (Route("INVALIDATE_MARKETVIEW"), *recompute)
    return ()


@dataclass(frozen=True)
class Handler:
    """Bộ xử lý một loại job. ``run(event, now) -> output_ref | None``; ném lỗi = thất bại."""

    version: str
    run: Callable[[Event, datetime], str | None]
    deadline: timedelta = timedelta(seconds=30)
    max_attempts: int = 3
    retry_base: timedelta = timedelta(seconds=10)
    retry_cap: timedelta = timedelta(minutes=5)
    # Lỗi không thử lại (vd. dữ liệu hỏng) → DEAD ngay.
    fatal: tuple[type[BaseException], ...] = ()


UNHANDLED_VERSION = "none"


def error_code(exc: BaseException) -> str:
    """Mã ngắn từ **loại** lỗi (không đọc thông điệp — có thể chứa khóa / URL)."""
    name = re.sub(r"(?<!^)(?=[A-Z])", "_", type(exc).__name__).upper()
    name = re.sub(r"[^A-Z0-9_]", "", name) or "ERROR"
    return name[:64] if name[0].isalpha() else f"E_{name}"[:64]


def backoff(h: Handler, failures: int) -> timedelta:
    return min(h.retry_base * (2 ** max(failures - 1, 0)), h.retry_cap)


@dataclass
class TickResult:
    events: int = 0
    created: int = 0
    superseded: int = 0
    ran: dict[str, int] = field(default_factory=dict)   # trạng thái → số lần


class Dispatcher:
    def __init__(self, orch, handlers: dict[str, Handler], *,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.orch = orch
        self.handlers = handlers
        self._clock = clock
        self._event_mark: datetime | None = None   # known_at lớn nhất đã tạo job (trong RAM)
        self._open: dict[str, Job] = {}             # job chưa kết thúc (khôi phục khi khởi động)
        self._events_by_id: dict[str, Event] = {}
        self._restored = False

    # ---------------------------------------------------------------- tạo job
    def _version(self, job_type: str) -> str:
        h = self.handlers.get(job_type)
        return h.version if h is not None else UNHANDLED_VERSION

    def create_jobs(self, now: datetime, since: datetime | None = None) -> TickResult:
        """Tạo job cho sự kiện mới (thứ tự nhân quả). Route ``debounce``: trong lô này chỉ sự kiện
        **mới nhất** của mỗi (loại job, chủ thể) được tạo job — sự kiện cũ hơn đếm vào
        ``superseded`` mà không tạo job (nạp bù hàng nghìn nến không sinh hàng nghìn job).
        Route không debounce (công bố, lịch, tin) luôn có job."""
        res = TickResult()
        lo = since if since is not None else (
            self._event_mark - OVERLAP if self._event_mark else now - LOOKBACK)
        events = self.orch.events(since=lo, until=now)
        res.events = len(events)
        newest: dict[tuple[str, str], tuple] = {}
        for e in events:
            for r in routes_for(e):
                if r.debounce:
                    k, rank = (r.job_type, e.subject), (e.occurred_at, e.event_version)
                    if k not in newest or rank > newest[k]:
                        newest[k] = rank
        jobs: list[Job] = []
        firsts: list[Attempt] = []
        for e in events:                      # thứ tự nhân quả (2-C02)
            for r in routes_for(e):
                if r.debounce and (e.occurred_at, e.event_version) < newest[
                        (r.job_type, e.subject)]:
                    res.superseded += 1
                    continue
                ver = self._version(r.job_type)
                j = Job(job_key_for(e, r.job_type, ver), e.event_id, r.job_type, ver,
                        e.correlation_id, now)
                jobs.append(j)
                firsts.append(Attempt(j.job_key, JobState.PENDING, 0, now))
                self._events_by_id[e.event_id] = e
            if self._event_mark is None or e.known_at > self._event_mark:
                self._event_mark = e.known_at
        made = set(self.orch.create_jobs_bulk(jobs, firsts))
        res.created = len(made)
        for j in jobs:
            if j.job_key in made:
                self._open[j.job_key] = j
        return res

    def _restore(self, now: datetime) -> None:
        """Khởi động lại: nạp job chưa kết thúc tạo trong ``LOOKBACK`` (2-C05)."""
        for j in self.orch.jobs_created_since(now - LOOKBACK):
            last = self.orch.latest(j.job_key)
            if last is None or last.state not in TERMINAL:
                self._open[j.job_key] = j
        if self._open:
            ids = {j.event_id for j in self._open.values()}
            for e in self.orch.events(since=now - LOOKBACK - timedelta(days=60), until=now):
                if e.event_id in ids:
                    self._events_by_id[e.event_id] = e
        self._restored = True

    # ---------------------------------------------------------------- debounce
    def _supersede(self, now: datetime, res: TickResult) -> None:
        """ORC-04: cùng loại job + cùng chủ thể, sự kiện mới hơn (theo thời điểm xảy ra rồi phiên
        bản) → job cũ chưa chạy SUPERSEDED. Chỉ cho route có ``debounce``."""
        newest: dict[tuple[str, str], tuple] = {}
        for j in self._open.values():
            e = self._events_by_id.get(j.event_id)
            if e is None or not any(r.debounce and r.job_type == j.job_type
                                    for r in routes_for(e)):
                continue
            k = (j.job_type, e.subject)
            rank = (e.occurred_at, e.event_version)
            if k not in newest or rank > newest[k]:
                newest[k] = rank
        for key, j in list(self._open.items()):
            e = self._events_by_id.get(j.event_id)
            if e is None:
                continue
            k = (j.job_type, e.subject)
            if k in newest and (e.occurred_at, e.event_version) < newest[k]:
                last = self.orch.latest(key)
                if last is not None and last.state is JobState.PENDING:
                    self.orch.append_attempt(Attempt(key, JobState.SUPERSEDED, last.attempt,
                                                     now))
                    del self._open[key]
                    res.superseded += 1

    # ---------------------------------------------------------------- chạy job
    def _record(self, res: TickResult, a: Attempt) -> None:
        self.orch.append_attempt(a)
        res.ran[a.state.value] = res.ran.get(a.state.value, 0) + 1
        if a.state in TERMINAL:
            self._open.pop(a.job_key, None)

    def run_due(self, now: datetime, res: TickResult) -> None:
        order = sorted(self._open.values(), key=lambda j: (
            self._events_by_id[j.event_id].order_key() if j.event_id in self._events_by_id
            else (j.created_at,), j.job_type))
        for j in order:
            last = self.orch.latest(j.job_key)
            if last is None or last.state in TERMINAL:
                self._open.pop(j.job_key, None)
                continue
            h = self.handlers.get(j.job_type)
            if h is None or h.version != j.analyzer_version:
                # Chưa có bộ xử lý / đổi phiên bản bộ xử lý (job phiên bản cũ không chạy bằng
                # code mới — job mới mang phiên bản mới được tạo khi sự kiện quét lại).
                self._record(res, Attempt(j.job_key, JobState.NO_HANDLER, last.attempt, now))
                continue
            attempt = last.attempt
            if last.state is JobState.RUNNING:
                if last.deadline_at is not None and now <= last.deadline_at:
                    continue                      # đang chạy ở nơi khác / chưa quá hạn
                last = Attempt(j.job_key, JobState.FAILED, attempt, now,
                               error_code="DEADLINE_EXCEEDED")
                self._record(res, self._after_failure(h, last, now))
                continue
            if last.state is JobState.FAILED:
                if now - last.at < backoff(h, attempt):
                    continue
            e = self._events_by_id.get(j.event_id)
            if e is None:
                self._record(res, Attempt(j.job_key, JobState.DEAD, attempt, now,
                                          error_code="EVENT_MISSING"))
                continue
            attempt += 1
            deadline = now + h.deadline
            self.orch.append_attempt(Attempt(j.job_key, JobState.RUNNING, attempt, now,
                                             deadline_at=deadline))
            t0 = self._clock()
            try:
                out = h.run(e, now)
            except Exception as exc:  # noqa: BLE001 — mọi lỗi của bộ xử lý đều thành mã ngắn
                fail = Attempt(j.job_key, JobState.FAILED, attempt, now,
                               error_code=error_code(exc))
                if isinstance(exc, h.fatal):
                    self._record(res, Attempt(j.job_key, JobState.DEAD, attempt, now,
                                              error_code=fail.error_code))
                else:
                    self._record(res, self._after_failure(h, fail, now))
                continue
            if timedelta(seconds=self._clock() - t0) > h.deadline:
                # Chạy xong nhưng quá deadline → không dùng kết quả (2-C04).
                fail = Attempt(j.job_key, JobState.FAILED, attempt, now,
                               error_code="DEADLINE_EXCEEDED")
                self._record(res, self._after_failure(h, fail, now))
                continue
            self._record(res, Attempt(j.job_key, JobState.SUCCEEDED, attempt, now,
                                      output_ref=(out[:256] if out else None)))

    def _after_failure(self, h: Handler, fail: Attempt, now: datetime) -> Attempt:
        if fail.attempt >= h.max_attempts:
            return Attempt(fail.job_key, JobState.DEAD, fail.attempt, now,
                           error_code=fail.error_code)
        return fail

    # ---------------------------------------------------------------- một nhịp
    def tick(self, now: datetime, since: datetime | None = None) -> TickResult:
        if not self._restored:
            self._restore(now)
        res = self.create_jobs(now, since)
        self._supersede(now, res)
        self.run_due(now, res)
        # Chỉ giữ sự kiện của job chưa kết thúc (chạy nhiều tháng không phình bộ nhớ).
        keep = {j.event_id for j in self._open.values()}
        self._events_by_id = {k: v for k, v in self._events_by_id.items() if k in keep}
        return res

    def state(self, job_key: str) -> JobState | None:
        last = self.orch.latest(job_key)
        return last.state if last else None
