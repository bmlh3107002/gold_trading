"""Chạy tự động các nguồn lịch kinh tế trong backend (GĐ1 bước 8g, ING-09 / ING-17).

Thiết kế: ``docs/thiet-ke/16-chay-tu-dong-nguon-lich.md``. Tóm tắt:

- Mỗi nguồn là một **việc** (``Job``): việc *lịch* (FOMC, lịch BEA, lịch DOL) và việc *số liệu*
  (số BEA, số DOL). Census **không** có ở đây (tạm hoãn 2026-11-13: Census chặn Việt Nam).
- Mỗi nhịp (30 giây) hỏi từng việc "có đến hạn không" bằng hàm thuần ``schedule_due`` /
  ``values_job_due`` — chỉ dựa trên nhật ký lần kiểm đã lưu (ING-30) + lịch đã biết, nên khởi
  động lại backend không làm mất nhịp và không gọi dồn.
- Việc lịch trước, việc số sau (số BEA/DOL cần lịch để gắn lần công bố).
- Đồng hồ máy chủ bị chặn (``ClockMonitor``) → **không chạy** (giờ sai làm sai ``ingested_at``).
- Lỗi bất ngờ trong một việc → ghi lần kiểm ``ERROR / INTERNAL_ERROR`` (nguồn thành STALE theo
  TTL như mọi lỗi khác), không làm chết các việc khác.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from gold_trading.common.time import utcnow
from gold_trading.ingestion.source_status import (
    CheckOutcome,
    CheckSummary,
    SourceCheck,
    SourceRegistry,
)

log = logging.getLogger(__name__)

TICK = timedelta(seconds=30)
# Lịch: tải lại khi lần OK cuối cũ hơn 20 giờ (TTL lịch là 26 giờ → còn 6 giờ cho lỗi tạm).
SCHEDULE_REFRESH = timedelta(hours=20)
# Lần thử lỗi gần nhất mới hơn mức này thì chưa thử lại (không gọi dồn khi nguồn lỗi).
SCHEDULE_RETRY = timedelta(minutes=30)
# Trong cửa sổ công bố: gọi lại sau ít nhất 60 giây (BEA cho 100 lượt/phút; mỗi lần 2 lượt).
RELEASE_POLL = timedelta(seconds=60)
# Tuần lễ DOL (không biết ngày nào trong thứ Tư–Sáu): gọi thưa hơn.
RELEASE_DAY_POLL = timedelta(minutes=5)
# Đối chiếu ngoài giờ công bố (hoặc khi thiếu khóa): thử lại sau ít nhất 6 giờ.
RECONCILE_RETRY = timedelta(hours=6)

# "news": mọi nguồn tin đang bật trong file cấu hình nguồn tin (bước 10b, ``ingestion/news.py``).
DEFAULT_SOURCES = ("fed_fomc", "bea", "dol", "bls", "fed_h15", "cftc_cot", "news")
KNOWN_SOURCES = frozenset(DEFAULT_SOURCES)


def parse_sources(raw: str | None) -> tuple[str, ...]:
    """``GT_EXTERNAL_SOURCES``: trống / không đặt → mặc định; ``0`` / ``off`` → tắt hết; còn lại
    là danh sách cách nhau bởi dấu phẩy. Tên lạ (vd. ``census`` đang hoãn) → lỗi cấu hình, không
    âm thầm bỏ qua."""
    if raw is None or not raw.strip():
        return DEFAULT_SOURCES
    v = raw.strip().lower()
    if v in {"0", "off", "none", "false"}:
        return ()
    names = tuple(dict.fromkeys(s.strip() for s in v.split(",") if s.strip()))
    bad = [n for n in names if n not in KNOWN_SOURCES]
    if bad:
        raise ValueError(f"GT_EXTERNAL_SOURCES có nguồn không hỗ trợ: {', '.join(bad)} "
                         f"(hỗ trợ: {', '.join(DEFAULT_SOURCES)})")
    return names


def _since(now: datetime, t: datetime | None) -> timedelta | None:
    return None if t is None else now - t


def schedule_due(now: datetime, summary: CheckSummary) -> str | None:
    """Việc lịch có đến hạn không. ``REFRESH`` / ``RETRY`` / None."""
    last_try = summary.last_check.checked_at if summary.last_check else None
    ok_age = _since(now, summary.last_ok_at)
    if ok_age is not None and ok_age < SCHEDULE_REFRESH:
        return None
    if last_try is None:
        return "REFRESH"
    if summary.last_check.outcome is CheckOutcome.OK:
        return "REFRESH"  # lần cuối OK nhưng đã cũ hơn SCHEDULE_REFRESH
    return "RETRY" if now - last_try >= SCHEDULE_RETRY else None


def values_job_due(now: datetime, summary: CheckSummary, reason: str | None) -> str | None:
    """Việc số liệu có đến hạn không, từ lý do của nguồn (``values_due``: RELEASE_WINDOW /
    RELEASE_DAY / RECONCILE / None). Nguồn tự trả None khi lần công bố đã có số (dựa trên dữ
    liệu đã lưu), nên ở đây chỉ giãn cách giữa các lần gọi."""
    if reason is None:
        return None
    gap = {"RELEASE_WINDOW": RELEASE_POLL, "RELEASE_DAY": RELEASE_DAY_POLL}.get(
        reason, RECONCILE_RETRY)
    last_try = summary.last_check.checked_at if summary.last_check else None
    return reason if last_try is None or now - last_try >= gap else None


@dataclass
class Job:
    source: str                                   # tên nguồn trong nhật ký (ING-30)
    run: Callable[[datetime], SourceCheck]
    due: Callable[[datetime, CheckSummary], str | None]
    is_values: bool = False


def build_jobs(sources: Sequence[str], *, store, check_log, env: Mapping[str, str],
               client) -> tuple[list[Job], SourceRegistry]:
    """Dựng danh sách việc theo thứ tự chạy (lịch trước, số sau)."""
    from gold_trading.ingestion.api_keys import load_api_key
    from gold_trading.ingestion.sources import bea, bls, cftc_cot, dol, fed_fomc, fed_h15

    specs = []
    sched: list[Job] = []
    vals: list[Job] = []
    if "fed_fomc" in sources:
        specs.append(fed_fomc.fomc_spec())
        get_fed = fed_fomc.http_getter(client)
        sched.append(Job(fed_fomc.SOURCE, lambda now: fed_fomc.run_once(
            store=store, log=check_log, get=get_fed, now=now, registry=registry),
            schedule_due))
    if "bea" in sources:
        specs += [bea.schedule_spec(), bea.values_spec()]
        get_bea = bea.http_getter(client)
        sched.append(Job(bea.SCHEDULE_SOURCE, lambda now: bea.run_schedule_once(
            store=store, log=check_log, get=get_bea, now=now, registry=registry),
            schedule_due))
        vals.append(Job(bea.VALUES_SOURCE, lambda now: bea.run_values_once(
            store=store, log=check_log, get=get_bea, now=now, registry=registry,
            key_lookup=load_api_key("bea", env)),
            lambda now, s: bea.values_due(now, store, s.last_ok_at), is_values=True))
    if "dol" in sources:
        specs += [dol.schedule_spec(), dol.values_spec()]
        get_dol = dol.http_getter(client)
        sched.append(Job(dol.SCHEDULE_SOURCE, lambda now: dol.run_schedule_once(
            store=store, log=check_log, now=now, registry=registry), schedule_due))
        vals.append(Job(dol.VALUES_SOURCE, lambda now: dol.run_values_once(
            store=store, log=check_log, get=get_dol, now=now, registry=registry),
            lambda now, s: dol.values_due(now, store, s.last_ok_at), is_values=True))
    if "bls" in sources:  # bước 8e: lịch chép tay (không gọi mạng) + số CPI / NFP / PPI qua API
        specs += [bls.schedule_spec(), bls.values_spec()]
        post_bls = bls.http_poster(client)
        sched.append(Job(bls.SCHEDULE_SOURCE, lambda now: bls.run_schedule_once(
            store=store, log=check_log, now=now, registry=registry), schedule_due))
        vals.append(Job(bls.VALUES_SOURCE, lambda now: bls.run_values_once(
            store=store, log=check_log, post=post_bls, now=now, registry=registry,
            key_lookup=load_api_key("bls", env)),
            lambda now, s: bls.values_due(now, store, s.last_ok_at), is_values=True))
    if "fed_h15" in sources:  # bước 9b: lãi suất H.15 (số vĩ mô, không theo lịch công bố)
        specs.append(fed_h15.spec())
        get_h15 = fed_h15.http_getter(client)
        vals.append(Job(fed_h15.SOURCE, lambda now: fed_h15.run_once(
            store=store, log=check_log, get=get_h15, now=now, registry=registry),
            fed_h15.due))
    if "cftc_cot" in sources:  # bước 9e: COT vàng (báo cáo tuần)
        specs.append(cftc_cot.spec())
        get_cot = cftc_cot.http_getter(client)
        vals.append(Job(cftc_cot.SOURCE, lambda now: cftc_cot.run_once(
            store=store, log=check_log, get=get_cot, now=now, registry=registry),
            cftc_cot.due))
    news_jobs: list[Job] = []
    if "news" in sources:  # bước 10b: tin RSS chính thức (danh sách trong file cấu hình)
        from gold_trading.ingestion import news
        try:
            cfgs, _ = news.load_news_config(env=env)
        except news.NewsConfigError as e:
            # Cấu hình tin sai → KHÔNG bật nguồn tin nào (không bật nửa vời), các nguồn khác vẫn
            # chạy; lỗi ghi rõ trong log để người dùng sửa file.
            log.error("Không bật nguồn tin: cấu hình nguồn tin sai — %s", e)
            cfgs = ()
        get_news = {}
        for c in cfgs:
            specs.append(c.spec())
            if not c.enabled:
                continue
            get_news[c.name] = news.http_getter(client, c)
            news_jobs.append(Job(c.name, lambda now, c=c: news.run_once(
                c, store=store, log=check_log, get=get_news[c.name], now=now,
                registry=registry), lambda now, s, c=c: news.due(c, now, s)))
    registry = SourceRegistry(specs)
    return sched + vals + news_jobs, registry


class ExternalSourceRunner:
    """Luồng nền gọi các nguồn lịch kinh tế khi đến hạn. ``tick(now)`` dùng được trực tiếp
    trong test (không cần luồng)."""

    def __init__(self, jobs: Sequence[Job], check_log, *,
                 blocked: Callable[[], str | None] = lambda: None,
                 now: Callable[[], datetime] = utcnow, tick: timedelta = TICK,
                 on_close: Callable[[], None] | None = None,
                 registry: SourceRegistry | None = None, store=None) -> None:
        # httpx ghi URL đầy đủ ở mức INFO — URL của BEA chứa khóa (UserID). Bộ che log JSON đã
        # che theo giá trị (ING-31); đây là lớp thứ hai: không ghi URL request ra log.
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        self._jobs = list(jobs)
        self._log = check_log
        # Cho trang "Nguồn dữ liệu" (DSH-09): đọc cùng registry / store / nhật ký với bộ chạy.
        self.registry = registry
        self.store = store
        self.check_log = check_log
        self._blocked = blocked
        self._now = now
        self._tick = tick
        self._on_close = on_close
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._blocked_logged = False

    @property
    def sources(self) -> list[str]:
        return [j.source for j in self._jobs]

    def tick(self, now: datetime | None = None) -> list[SourceCheck]:
        """Một nhịp: chạy các việc đến hạn, trả các lần kiểm vừa ghi."""
        reason = self._blocked()
        if reason:
            if not self._blocked_logged:
                log.warning("Tạm dừng nạp lịch kinh tế: %s", reason)
                self._blocked_logged = True
            return []
        self._blocked_logged = False
        done: list[SourceCheck] = []
        for job in self._jobs:
            now_j = now or self._now()  # mỗi việc lấy giờ riêng (việc trước có thể chạy lâu)
            try:
                summary = self._log.summary(job.source, now_j)
                why = job.due(now_j, summary)
                if job.is_values:
                    why = values_job_due(now_j, summary, why)
                if why is None:
                    continue
                check = job.run(now_j)
            except Exception:
                log.exception("Nguồn %s: lỗi khi chạy", job.source)
                check = SourceCheck(job.source, now_j, CheckOutcome.ERROR, "INTERNAL_ERROR")
                try:
                    self._log.record(check)
                except Exception:
                    log.exception("Nguồn %s: không ghi được nhật ký lần kiểm", job.source)
                done.append(check)
                continue
            lvl = logging.INFO if check.outcome is CheckOutcome.OK else logging.WARNING
            log.log(lvl, "Nguồn %s (%s): %s %s — thêm %d, trùng %d", job.source, why,
                    check.outcome.value, check.error_code or "", check.inserted,
                    check.duplicate)
            done.append(check)
        return done

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("Bộ nạp lịch kinh tế lỗi")
            if self._stop.wait(self._tick.total_seconds()):
                return

    def start(self) -> None:
        if self._thread is None and self._jobs:
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="external-sources",
                                            daemon=True)
            self._thread.start()
            log.info("Bật nạp lịch kinh tế tự động: %s", ", ".join(self.sources))

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)
            self._thread = None
        if self._on_close:
            self._on_close()
            self._on_close = None


def runner_from_env(engine, env: Mapping[str, str], *,
                    blocked: Callable[[], str | None] = lambda: None
                    ) -> ExternalSourceRunner | None:
    """Dựng bộ chạy theo ``GT_EXTERNAL_SOURCES``. ``engine`` None (repo trong bộ nhớ) → dùng
    store trong bộ nhớ (chỉ để chạy thử, mất khi tắt)."""
    import httpx

    from gold_trading.ingestion.point_in_time import PointInTimeStore
    from gold_trading.ingestion.source_status import SourceCheckLog

    sources = parse_sources(env.get("GT_EXTERNAL_SOURCES"))
    if not sources:
        return None
    if engine is not None:
        from gold_trading.storage.external_records import SqlExternalRecordStore
        from gold_trading.storage.source_checks import SqlSourceCheckLog
        store, check_log = SqlExternalRecordStore(engine), SqlSourceCheckLog(engine)
    else:
        store, check_log = PointInTimeStore(), SourceCheckLog()
    client = httpx.Client(headers={"User-Agent": "gold-trading-personal/0.1"})
    jobs, registry = build_jobs(sources, store=store, check_log=check_log, env=env,
                                client=client)
    return ExternalSourceRunner(jobs, check_log, blocked=blocked, on_close=client.close,
                                registry=registry, store=store)
