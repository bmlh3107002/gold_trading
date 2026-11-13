"""Nạp nến từ CSV vào database.

    python -m gold_trading.ingestion.cli import-csv FILE --server-tz Europe/Athens

Trong Docker:

    docker compose cp XAUUSD_M15.csv backend:/tmp/data.csv
    docker compose exec backend python -m gold_trading.ingestion.cli import-csv /tmp/data.csv \\
        --server-tz Europe/Athens

Dữ liệu nạp có nguồn CSV; muốn Dashboard dùng nó thì đặt GT_DATA_SOURCE=CSV.

Tải lịch FOMC của Fed một lần (bước 8b, ING-09) và in các mốc sắp tới:

    docker compose exec backend python -m gold_trading.ingestion.cli fomc

Tải lịch BEA (GDP, PCE) + số actual qua API BEA (bước 8c, ING-09/ING-17; số actual cần
GT_BEA_API_KEY trong .env):

    docker compose exec backend python -m gold_trading.ingestion.cli bea
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from gold_trading.common.time import utcnow
from gold_trading.contracts.candle import DataSource
from gold_trading.ingestion.candles import CandleIngestor
from gold_trading.ingestion.sources import csv_file
from gold_trading.market.timeframes import Timeframe
from gold_trading.storage.candles import SqlCandleStore
from gold_trading.storage.repository import SqlRepository


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="gold_trading.ingestion.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    imp = sub.add_parser("import-csv", help="Nạp nến từ file CSV (thường xuất từ MT5)")
    imp.add_argument("file", type=Path)
    imp.add_argument(
        "--server-tz",
        help="Múi giờ server của broker (IANA), ví dụ Europe/Athens. Bắt buộc nếu file không "
        "ghi múi giờ — MT5 xuất theo giờ server, không phải UTC.",
    )
    imp.add_argument("--symbol", default="XAUUSD")
    # H4 trở lên được broker căn theo giờ server (ví dụ 00:00 GMT+2 = 22:00 UTC), chưa hỗ trợ.
    imp.add_argument("--timeframe", default="M15", choices=["M1", "M5", "M15", "M30", "H1"])
    imp.add_argument("--dry-run", action="store_true", help="Chỉ đọc và kiểm tra, không ghi DB")
    fomc = sub.add_parser("fomc", help="Tải lịch FOMC từ trang Fed một lần (ING-09)")
    fomc.add_argument("--dry-run", action="store_true", help="Chỉ tải và in, không ghi DB")
    bea = sub.add_parser("bea", help="Tải lịch BEA + số actual GDP, PCE một lần (ING-09/17)")
    bea.add_argument("--dry-run", action="store_true", help="Chỉ tải và in, không ghi DB")
    args = p.parse_args(argv)
    if args.cmd == "fomc":
        return _fomc(args.dry_run)
    if args.cmd == "bea":
        return _bea(args.dry_run)

    try:
        text = args.file.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        text = args.file.read_text(encoding="utf-16")  # MT5 đôi khi xuất UTF-16
    try:
        bars, rejects = csv_file.parse(text, server_tz=args.server_tz)
    except (csv_file.CsvFormatError, KeyError) as e:
        print(f"Lỗi định dạng: {e}", file=sys.stderr)
        return 2

    print(f"Đọc được {len(bars)} nến, {len(rejects)} dòng lỗi.")
    if bars:
        print(f"Khoảng thời gian (UTC): {bars[0].open_time} → {bars[-1].open_time}")

    # R1: khai báo sai múi giờ làm mọi nến lệch giờ mà không có lỗi định dạng nào -> chặn cả file
    tf = Timeframe(args.timeframe)
    chk = csv_file.check_sessions(bars, int(tf.delta.total_seconds() // 60))
    if not chk.ok:
        print(
            f"TỪ CHỐI: {chk.outside_fraction:.1%} số nến rơi vào giờ thị trường đóng cửa "
            f"(cho phép tối đa {csv_file.SESSION_MISMATCH_MAX:.0%}). Nhiều khả năng múi giờ "
            f"--server-tz chưa đúng.",
            file=sys.stderr,
        )
        if chk.best_shift_hours != 0 and chk.best_outside_fraction <= csv_file.SESSION_MISMATCH_MAX:
            print(
                f"Gợi ý: dữ liệu khớp lịch nhất khi lệch thêm {chk.best_shift_hours:+d} giờ "
                f"(còn {chk.best_outside_fraction:.1%} nến ngoài giờ). Kiểm tra lại múi giờ server "
                "của broker.",
                file=sys.stderr,
            )
        return 3
    if args.dry_run:
        for r in rejects[:20]:
            print(f"  dòng {r.line}: {r.reason}")
        return 0

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("Chưa đặt DATABASE_URL", file=sys.stderr)
        return 2
    store = SqlCandleStore(SqlRepository.from_url(url).engine)
    result = CandleIngestor(store).ingest(
        bars,
        symbol=args.symbol,
        timeframe=tf,
        source=DataSource.CSV,
        ingested_at=utcnow(),
        backfill=True,
        rejected=[(r.reason, r.raw | {"line": r.line}) for r in rejects],
    )
    print(
        f"Kết quả: thêm {result.accepted}, trùng {result.duplicates}, "
        f"sửa đổi {result.revised}, cách ly {result.quarantined} {result.reasons or ''}"
    )
    return 0



def _fomc(dry_run: bool) -> int:
    import httpx

    from gold_trading.ingestion.point_in_time import PointInTimeStore
    from gold_trading.ingestion.source_status import SourceCheckLog, SourceRegistry
    from gold_trading.ingestion.sources import fed_fomc
    from gold_trading.storage.external_records import SqlExternalRecordStore
    from gold_trading.storage.source_checks import SqlSourceCheckLog

    now = utcnow()
    if dry_run:
        store, log = PointInTimeStore(), SourceCheckLog()
    else:
        url = os.environ.get("DATABASE_URL")
        if not url:
            print("Thiếu DATABASE_URL", file=sys.stderr)
            return 2
        engine = SqlRepository.from_url(url).engine
        store, log = SqlExternalRecordStore(engine), SqlSourceCheckLog(engine)
    with httpx.Client(headers={"User-Agent": "gold-trading-personal/0.1"}) as client:
        check = fed_fomc.run_once(store=store, log=log, get=fed_fomc.http_getter(client),
                                  now=now, registry=SourceRegistry([fed_fomc.fomc_spec()]))
    print(f"Kết quả: {check.outcome.value} {check.error_code or ''} — thêm {check.inserted}, "
          f"trùng/không đổi {check.duplicate}")
    for r in store.as_of(now, source=fed_fomc.SOURCE):
        if r.event_time < now or r.payload.get("status") == "REMOVED":
            continue
        p = r.payload
        when = r.event_time.strftime("%Y-%m-%d %H:%M UTC") if p["time_confirmed"] \
            else r.event_time.strftime("%Y-%m-%d (chưa có giờ)")
        print(f"  {when}  {p['event']}{'  [dự kiến]' if p.get('tentative') else ''}"
              f"{'  [' + p['note'] + ']' if p.get('note') else ''}")
    return 0 if check.outcome.value == "OK" else 1


def _bea(dry_run: bool, env=None, client_factory=None) -> int:
    import httpx

    from gold_trading.ingestion.api_keys import load_api_key
    from gold_trading.ingestion.point_in_time import PointInTimeStore
    from gold_trading.ingestion.source_status import SourceCheckLog, SourceRegistry
    from gold_trading.ingestion.sources import bea
    from gold_trading.storage.external_records import SqlExternalRecordStore
    from gold_trading.storage.source_checks import SqlSourceCheckLog

    env = os.environ if env is None else env
    now = utcnow()
    if dry_run:
        store, log = PointInTimeStore(), SourceCheckLog()
    else:
        url = env.get("DATABASE_URL")
        if not url:
            print("Thiếu DATABASE_URL", file=sys.stderr)
            return 2
        engine = SqlRepository.from_url(url).engine
        store, log = SqlExternalRecordStore(engine), SqlSourceCheckLog(engine)
    registry = SourceRegistry([bea.schedule_spec(), bea.values_spec()])
    make = client_factory or (lambda: httpx.Client(
        headers={"User-Agent": "gold-trading-personal/0.1"}))
    with make() as client:
        get = bea.http_getter(client)
        sched = bea.run_schedule_once(store=store, log=log, get=get, now=now, registry=registry)
        print(f"Lịch BEA: {sched.outcome.value} {sched.error_code or ''} — thêm {sched.inserted}")
        vals = bea.run_values_once(store=store, log=log, get=get, now=now, registry=registry,
                                   key_lookup=load_api_key("bea", env))
        print(f"Số actual BEA: {vals.outcome.value} {vals.error_code or ''} — thêm "
              f"{vals.inserted}")
    upcoming = [r for r in store.as_of(now, source=bea.SCHEDULE_SOURCE)
                if r.event_time >= now and r.payload.get("status") != "REMOVED"]
    for r in sorted(upcoming, key=lambda r: r.event_time)[:12]:
        p = r.payload
        when = r.event_time.strftime("%Y-%m-%d %H:%M UTC") if p["time_confirmed"] \
            else r.event_time.strftime("%Y-%m-%d (chưa chắc giờ)")
        print(f"  {when}  {r.logical_key}{'  ' + str(p['flags']) if p['flags'] else ''}")
    latest: dict[str, object] = {}
    for r in store.as_of(now, source=bea.VALUES_SOURCE):
        cur = latest.get(r.payload["series"])
        if cur is None or r.event_time > cur.event_time:
            latest[r.payload["series"]] = r
    for code, r in sorted(latest.items()):
        p = r.payload
        print(f"  {code} {p['period']}: {p['value'] if p['value'] is not None else 'không có số'}"
              f"  ({p['label']})")
    print("This product uses the Bureau of Economic Analysis (BEA) Data API but is not "
          "endorsed or certified by BEA.")
    ok = sched.outcome.value == "OK" and vals.outcome.value == "OK"
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
