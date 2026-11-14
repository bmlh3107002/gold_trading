"""Chạy lại (replay) nhật ký sự kiện từ dữ liệu đã lưu và so với lúc chạy thật (Gate GĐ2).

Thiết kế: ``docs/thiet-ke/25-event-orchestrator.md`` mục 9. **Chỉ đọc** dữ liệu thật (nến, bản ghi
nguồn ngoài, kết quả analyst, nhật ký sự kiện / job, lệnh cấm); mọi thứ chạy lại nằm trong bộ nhớ →
chạy được khi backend đang chạy, không ghi gì vào DB. Ba phần so:

1. **Sự kiện:** quét lại từ lúc bộ điều phối chạy lần đầu, từng bước (như lúc chạy thật) → tập sự
   kiện (khóa, nội dung, thời điểm) phải trùng nhật ký thật, không thiếu, không thừa.
2. **Làn nhanh:** chạy lại job ``FAST_LANE`` (cùng phiên bản) → cùng kết quả job, mọi lệnh cấm
   ghi thật được tạo lại y hệt (loại, phạm vi, lý do, bắt đầu, hết hạn).
3. **Phân tích kỹ thuật:** tính lại tại đúng thời điểm đã tính → cùng ``output_id`` (gồm dấu vân
   tay dữ liệu đầu vào).

Thêm: không job nào có hơn một lần ``SUCCEEDED`` (không nhân đôi output).

Lệnh (trong container backend): ``python -m gold_trading.orchestrator.replay``.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from gold_trading.common.time import utcnow
from gold_trading.orchestrator import scanner
from gold_trading.orchestrator.dispatcher import Dispatcher
from gold_trading.orchestrator.model import JobState, OrchestratorStore
from gold_trading.risk.blocks import BlockKind, BlockStore

STEP = timedelta(minutes=5)
SETTLE = timedelta(minutes=1)        # bỏ phút cuối: bộ điều phối thật có thể chưa quét tới
JOB_LOOKBACK = timedelta(days=3)


@dataclass
class ReplayReport:
    start: datetime
    end: datetime
    live_events: Counter = field(default_factory=Counter)
    replay_events: Counter = field(default_factory=Counter)
    only_live: list = field(default_factory=list)
    only_replay: list = field(default_factory=list)
    event_diff: list = field(default_factory=list)
    fast_lane_compared: int = 0
    fast_lane_diff: list = field(default_factory=list)
    blocks_compared: int = 0
    blocks_diff: list = field(default_factory=list)
    error_blocks: list = field(default_factory=list)      # FAST_LANE_ERROR lúc chạy thật
    technical_compared: int = 0
    technical_skipped_version: int = 0
    technical_diff: list = field(default_factory=list)
    multi_success: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.only_live or self.only_replay or self.event_diff or self.fast_lane_diff
                    or self.blocks_diff or self.technical_diff or self.multi_success)


def _event_sig(e) -> tuple:
    return (e.event_type.value, e.subject, e.event_version, e.occurred_at, e.known_at,
            sorted(e.payload.items()))


def replay_events(*, candle_store, record_store, analyst_store, start: datetime, end: datetime,
                  step: timedelta = STEP) -> OrchestratorStore:
    """Quét lại vào kho trong bộ nhớ: lần đầu tại ``start`` (nhìn lùi như lần đầu chạy thật),
    rồi từng ``step`` tới ``end``."""
    mem = OrchestratorStore()
    t = start
    scanner.scan(orch=mem, candle_store=candle_store, record_store=record_store,
                 analyst_store=analyst_store, now=t)
    while t < end:
        t = min(t + step, end)
        scanner.scan(orch=mem, candle_store=candle_store, record_store=record_store,
                     analyst_store=analyst_store, now=t)
    return mem


def compare_events(live, mem, end: datetime, rep: ReplayReport) -> None:
    lv = {e.event_id: e for e in live.events(until=end)}
    rp = {e.event_id: e for e in mem.events(until=end)}
    rep.live_events = Counter(e.event_type.value for e in lv.values())
    rep.replay_events = Counter(e.event_type.value for e in rp.values())
    rep.only_live = sorted((lv[k] for k in lv.keys() - rp.keys()), key=lambda e: e.order_key())
    rep.only_replay = sorted((rp[k] for k in rp.keys() - lv.keys()), key=lambda e: e.order_key())
    rep.event_diff = [(lv[k], rp[k]) for k in sorted(lv.keys() & rp.keys())
                      if _event_sig(lv[k]) != _event_sig(rp[k])]


def compare_fast_lane(live, live_blocks, mem, handler_factory: Callable, start: datetime,
                      end: datetime, rep: ReplayReport) -> None:
    from gold_trading.risk.fast_lane import HANDLER_VERSION

    blocks = BlockStore()
    d = Dispatcher(mem, {"FAST_LANE": handler_factory(blocks)})
    d.tick(end, since=start - JOB_LOOKBACK)
    replay_jobs = {r.job.job_key: r for r in mem.job_rows(start - JOB_LOOKBACK)
                   if r.job.job_type == "FAST_LANE"}
    for r in live.job_rows(start - JOB_LOOKBACK):
        if r.job.job_type != "FAST_LANE" or r.job.analyzer_version != HANDLER_VERSION:
            continue
        if r.last.state is not JobState.SUCCEEDED:
            continue                    # chưa xong / lỗi lúc chạy thật: xem lệnh cấm lỗi bên dưới
        if r.job.created_at > end:
            continue
        rep.fast_lane_compared += 1
        x = replay_jobs.get(r.job.job_key)
        if x is None or x.last.state is not JobState.SUCCEEDED \
                or x.last.output_ref != r.last.output_ref:
            rep.fast_lane_diff.append((r.subject, r.last.output_ref,
                                       None if x is None else x.last.output_ref))
    for b in live_blocks.created_between(start - JOB_LOOKBACK, end):
        if b.kind is BlockKind.SPREAD or b.kind is BlockKind.LATENCY:
            continue                    # spread: từ giá theo giây (4c), không qua sự kiện
        if b.reason_code == "FAST_LANE_ERROR":
            rep.error_blocks.append(b)
            continue
        rep.blocks_compared += 1
        got = blocks.get(b.block_id)
        if got is None:
            rep.blocks_diff.append((b, None))
            continue
        x = got[0]
        if (x.kind, x.scope, x.reason_code, x.start_at, x.end_at, x.cause_ref) != (
                b.kind, b.scope, b.reason_code, b.start_at, b.end_at, b.cause_ref):
            rep.blocks_diff.append((b, x))


class _Capture:
    """Kho analyst giả: chỉ ghi lại ``output_id`` vừa tính."""

    def __init__(self) -> None:
        self.ids: list[str] = []

    def append(self, out, **_kw) -> bool:
        self.ids.append(out.output_id)
        return True


def compare_technical(analyst_store, market, start: datetime, end: datetime,
                      rep: ReplayReport) -> None:
    from gold_trading.analysts import technical
    from gold_trading.analysts.runner import TechnicalRunner

    for (aid, feed, _sym, _tf, _src, output_id, computed_at) in \
            analyst_store.computed_between(start, end):
        if aid != technical.ANALYST_ID:
            continue
        if f":{technical.VERSION}:" not in output_id:
            rep.technical_skipped_version += 1     # tính bằng phiên bản cũ → không so được
            continue
        cap = _Capture()
        TechnicalRunner(market, cap, feeds=lambda f=feed: [f]).run_feed(feed, computed_at)
        rep.technical_compared += 1
        if cap.ids != [output_id]:
            rep.technical_diff.append((feed, computed_at, output_id, cap.ids))


def run(*, live, live_blocks, candle_store, record_store, analyst_store, market,
        handler_factory: Callable, now: datetime, step: timedelta = STEP,
        technical_check: bool = True) -> ReplayReport | None:
    start = live.first_recorded_at()
    if start is None:
        return None
    end = now - SETTLE
    rep = ReplayReport(start=start, end=end)
    mem = replay_events(candle_store=candle_store, record_store=record_store,
                        analyst_store=analyst_store, start=start, end=end, step=step)
    compare_events(live, mem, end, rep)
    compare_fast_lane(live, live_blocks, mem, handler_factory, start, end, rep)
    if technical_check and market is not None:
        compare_technical(analyst_store, market, start, end, rep)
    rep.multi_success = live.multi_success_jobs()
    return rep


# ================================================================ in báo cáo

def _fmt_event(e) -> str:
    return (f"{e.event_type.value} {e.subject} {e.event_version} "
            f"(biết lúc {e.known_at:%d/%m %H:%M:%S} UTC)")


def report_text(rep: ReplayReport, limit: int = 10) -> str:
    L = [f"Chạy lại nhật ký sự kiện từ {rep.start:%d/%m/%Y %H:%M} tới {rep.end:%d/%m/%Y %H:%M} "
         "UTC (chỉ đọc, không ghi DB)", ""]
    ok_ev = not (rep.only_live or rep.only_replay or rep.event_diff)
    L.append(f"1. Sự kiện: {'ĐẠT' if ok_ev else 'KHÔNG ĐẠT'} — thật {sum(rep.live_events.values())}"
             f", chạy lại {sum(rep.replay_events.values())}")
    for t in sorted(set(rep.live_events) | set(rep.replay_events)):
        L.append(f"   {t}: thật {rep.live_events[t]}, chạy lại {rep.replay_events[t]}")
    for title, rows in (("   Chỉ có ở nhật ký thật", rep.only_live),
                        ("   Chỉ có khi chạy lại", rep.only_replay)):
        if rows:
            L.append(f"{title}: {len(rows)}")
            L += [f"     - {_fmt_event(e)}" for e in rows[:limit]]
    if rep.event_diff:
        L.append(f"   Cùng khóa nhưng khác nội dung: {len(rep.event_diff)}")
        L += [f"     - {_fmt_event(a)}" for a, _ in rep.event_diff[:limit]]
    ok_fl = not (rep.fast_lane_diff or rep.blocks_diff)
    L.append(f"2. Làn nhanh: {'ĐẠT' if ok_fl else 'KHÔNG ĐẠT'} — {rep.fast_lane_compared} job, "
             f"{rep.blocks_compared} lệnh cấm so khớp")
    L += [f"     - job {s}: thật {a}, chạy lại {b}" for s, a, b in rep.fast_lane_diff[:limit]]
    for b, x in rep.blocks_diff[:limit]:
        L.append(f"     - lệnh cấm {b.reason_code} {b.cause_ref}: "
                 + ("không tạo lại được" if x is None else
                    f"thật {b.start_at:%H:%M:%S}–{b.end_at}, "
                    f"chạy lại {x.start_at:%H:%M:%S}–{x.end_at}"))
    if rep.error_blocks:
        L.append(f"   Lưu ý: {len(rep.error_blocks)} lệnh cấm mặc định do lỗi lúc chạy thật "
                 "(FAST_LANE_ERROR) — không so, xem log")
    ok_t = not rep.technical_diff
    L.append(f"3. Phân tích kỹ thuật: {'ĐẠT' if ok_t else 'KHÔNG ĐẠT'} — {rep.technical_compared} "
             f"kết quả tính lại khớp mã"
             + (f" (bỏ qua {rep.technical_skipped_version} kết quả phiên bản cũ)"
                if rep.technical_skipped_version else ""))
    L += [f"     - {f} lúc {t:%d/%m %H:%M:%S}: thật {o}, chạy lại {g}"
          for f, t, o, g in rep.technical_diff[:limit]]
    L.append(f"4. Không nhân đôi: {'ĐẠT' if not rep.multi_success else 'KHÔNG ĐẠT'} — "
             f"{len(rep.multi_success)} job thành công hơn một lần")
    L += [f"     - {k}" for k in rep.multi_success[:limit]]
    L += ["", "KẾT LUẬN: " + ("ĐẠT — chạy lại cho kết quả giống hệt" if rep.ok
                              else "KHÔNG ĐẠT — gửi toàn bộ nội dung này cho người phát triển")]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m gold_trading.orchestrator.replay")
    ap.add_argument("--step-minutes", type=int, default=5)
    ap.add_argument("--no-technical", action="store_true")
    a = ap.parse_args(argv)
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("Thiếu DATABASE_URL", file=sys.stderr)
        return 2
    from gold_trading.api.app import calendar_from_env, data_source_from_env
    from gold_trading.market.service import MarketDataService
    from gold_trading.risk.fast_lane import fast_lane_handler
    from gold_trading.storage.analyst_outputs import SqlAnalystOutputStore
    from gold_trading.storage.candles import SqlCandleStore
    from gold_trading.storage.external_records import SqlExternalRecordStore
    from gold_trading.storage.orchestrator import SqlOrchestratorStore
    from gold_trading.storage.repository import SqlRepository
    from gold_trading.storage.risk_blocks import SqlBlockStore

    engine = SqlRepository.from_url(url).engine
    source = data_source_from_env()
    cal = calendar_from_env(source)
    candles = SqlCandleStore(engine)
    records = SqlExternalRecordStore(engine)
    market = MarketDataService(candles, source=source, calendar=cal) if source else None
    rep = run(live=SqlOrchestratorStore(engine), live_blocks=SqlBlockStore(engine),
              candle_store=candles, record_store=records,
              analyst_store=SqlAnalystOutputStore(engine), market=market,
              handler_factory=lambda bs: fast_lane_handler(bs, records, cal),
              now=utcnow(), step=timedelta(minutes=max(a.step_minutes, 1)),
              technical_check=not a.no_technical)
    if rep is None:
        print("Nhật ký sự kiện trống — bộ điều phối chưa chạy lần nào.")
        return 2
    print(report_text(rep))
    return 0 if rep.ok else 1


if __name__ == "__main__":
    sys.exit(main())
