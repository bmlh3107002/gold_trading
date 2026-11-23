"""Lệnh backtest (GĐ6). Mọi lệnh ghi / đọc **chỉ** cơ sở dữ liệu backtest riêng
(``GT_BACKTEST_DATABASE_URL``; trùng ``DATABASE_URL`` → từ chối).

    python -m gold_trading.backtest.cli init-db
    python -m gold_trading.backtest.cli import FILE --timeframe M15 --server-tz Europe/Athens
    python -m gold_trading.backtest.cli import FILE --timeframe D1 --server-tz Europe/Athens \
        --dry-run
    python -m gold_trading.backtest.cli data-report --timeframe M15 --holidays

``--dry-run`` chỉ đọc + kiểm file, không mở cơ sở dữ liệu nào.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from gold_trading.backtest import data as BD
from gold_trading.backtest.db import BacktestDbError, init_db, resolve_url
from gold_trading.market.timeframes import Timeframe


def main(argv: list[str] | None = None, env=None) -> int:
    p = argparse.ArgumentParser(prog="gold_trading.backtest.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db", help="Tạo schema cho cơ sở dữ liệu backtest riêng")
    imp = sub.add_parser("import", help="Nạp nến CSV (MT5) vào cơ sở dữ liệu backtest riêng")
    imp.add_argument("file", type=Path)
    imp.add_argument("--timeframe", default="M15", choices=BD.TIMEFRAMES)
    imp.add_argument("--server-tz", help="Múi giờ server broker (IANA), ví dụ Europe/Athens")
    imp.add_argument("--symbol", default="XAUUSD")
    imp.add_argument("--dry-run", action="store_true", help="Chỉ đọc + kiểm, không mở DB")
    rep = sub.add_parser("data-report", help="Báo cáo dữ liệu đã nạp (chỉ đọc)")
    rep.add_argument("--timeframe", default="M15", choices=BD.TIMEFRAMES)
    rep.add_argument("--symbol", default="XAUUSD")
    rep.add_argument("--holidays", action="store_true",
                     help="Đối chiếu bảng ngày lễ 2020–2027 với chỗ hở nến M15 thật")
    args = p.parse_args(argv)
    try:
        if args.cmd == "import" and args.dry_run:
            return _import(args, None)
        url = resolve_url(env)
        if args.cmd == "init-db":
            print(f"Khởi tạo cơ sở dữ liệu backtest: {init_db(url, env=env)}")
            return 0
        if args.cmd == "import":
            return _import(args, url)
        return _report(args, url)
    except BacktestDbError as e:
        print(f"TỪ CHỐI: {e}", file=sys.stderr)
        return 2


def _store(url: str):
    from gold_trading.storage.candles import SqlCandleStore
    from gold_trading.storage.repository import SqlRepository
    return SqlCandleStore(SqlRepository.from_url(url).engine)


def _import(args, url: str | None) -> int:
    from gold_trading.common.time import utcnow
    tf = Timeframe(args.timeframe)
    if tf.server_aligned and not args.server_tz:
        print(f"Khung {tf} cần --server-tz", file=sys.stderr)
        return 2
    try:
        text = BD.read_text(args.file.read_bytes())
        parsed = BD.parse(text, tf, args.server_tz)
    except (ValueError, KeyError) as e:
        print(f"Lỗi định dạng: {e}", file=sys.stderr)
        return 2
    print(f"Đọc được {len(parsed.bars)} nến {tf}, {len(parsed.rejects)} dòng lỗi.")
    if parsed.bars:
        print(f"Khoảng thời gian (UTC): {parsed.bars[0].open_time} → {parsed.bars[-1].open_time}")
    if not parsed.ok:
        c = parsed.check
        print(f"TỪ CHỐI: {c.outside_fraction:.1%} số nến rơi vào giờ đóng cửa — nhiều khả năng "
              f"--server-tz sai (khớp nhất khi lệch thêm {c.best_shift_hours:+d} giờ).",
              file=sys.stderr)
        return 3
    if url is None:
        for r in parsed.rejects[:20]:
            print(f"  dòng {r.line}: {r.reason}")
        return 0
    res = BD.ingest(_store(url), parsed, tf, symbol=args.symbol, server_tz=args.server_tz,
                    ingested_at=utcnow())
    print(f"Kết quả (DB backtest): thêm {res.accepted}, trùng {res.duplicates}, sửa đổi "
          f"{res.revised}, cách ly {res.quarantined} {res.reasons or ''}")
    return 0


def _report(args, url: str) -> int:
    from datetime import UTC, datetime

    from gold_trading.contracts.candle import DataSource
    tf = Timeframe(args.timeframe)
    store = _store(url)
    st = store.stats(args.symbol, tf, DataSource.CSV)
    if not st.count or st.first_open_time is None or st.last_open_time is None:
        print("Chưa có nến nào trong cơ sở dữ liệu backtest cho khung này.")
        return 0
    lo, hi = st.first_open_time, st.last_open_time
    cs = list(store.latest_by_open_time(args.symbol, tf, DataSource.CSV, lo, hi).values())
    rep = BD.report(cs, tf, BD.backtest_calendar(), quarantined=st.quarantined)
    print("\n".join(BD.render(rep)))
    if args.holidays:
        if tf is not Timeframe.M15:
            print("Đối chiếu ngày lễ chỉ dùng khung M15", file=sys.stderr)
            return 2
        mism = BD.holiday_check(cs)
        print(f"Đối chiếu ngày lễ (bảng backtest) với dữ liệu: {len(mism)} chỗ lệch")
        for m in mism:
            print(f"  {m.day.isoformat()} ({m.day:%a}) {m.kind}: {m.detail}")
    print(f"(chỉ đọc, {datetime.now(UTC):%Y-%m-%d %H:%M} UTC)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
