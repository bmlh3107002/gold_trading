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

Tải lịch + số actual doanh số bán lẻ của Census (bước 8d; số cần GT_CENSUS_API_KEY):

    docker compose exec backend python -m gold_trading.ingestion.cli census

Lịch (theo quy tắc) + số trợ cấp thất nghiệp tuần của DOL (bước 8f, không cần khóa):

    docker compose exec backend python -m gold_trading.ingestion.cli dol

Tải lãi suất H.15 của Fed một lần (bước 9b: EFFR, lợi suất 2 năm, 10 năm, thực 10 năm):

    docker compose exec backend python -m gold_trading.ingestion.cli h15 --dry-run

Vị thế COT vàng của CFTC (bước 9e):

    docker compose exec backend python -m gold_trading.ingestion.cli cot --dry-run

Chỉ số USD tự tính từ giá 6 cặp trên MT5 của từng broker (bước 9d, chỉ đọc DB):

    docker compose exec backend python -m gold_trading.ingestion.cli usd

Tin chính thức qua RSS (bước 10b: thông cáo chính sách tiền tệ + phát biểu Fed; danh sách nguồn
trong file cấu hình nguồn tin), tải một lần rồi in tin mới trong N giờ:

    docker compose exec backend python -m gold_trading.ingestion.cli tin --dry-run --hours 72

Xem bảng lịch kinh tế hợp nhất đã lưu (bước 8g, chỉ đọc DB, không gọi mạng):

    docker compose exec backend python -m gold_trading.ingestion.cli lich --days 14
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

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
    cen = sub.add_parser("census", help="Tải lịch + số actual bán lẻ Census một lần (ING-09/17)")
    cen.add_argument("--dry-run", action="store_true", help="Chỉ tải và in, không ghi DB")
    dol = sub.add_parser("dol", help="Lịch + số trợ cấp thất nghiệp tuần DOL một lần (ING-09/17)")
    dol.add_argument("--dry-run", action="store_true", help="Chỉ tải và in, không ghi DB")
    h15 = sub.add_parser("h15", help="Tải lãi suất H.15 của Fed một lần (ING-25/26)")
    h15.add_argument("--dry-run", action="store_true", help="Chỉ tải và in, không ghi DB")
    cot = sub.add_parser("cot", help="Tải báo cáo COT vàng của CFTC một lần (ING-12)")
    cot.add_argument("--dry-run", action="store_true", help="Chỉ tải và in, không ghi DB")
    usd = sub.add_parser("usd", help="Chỉ số USD tự tính từ 6 cặp MT5 (ING-24, chỉ đọc)")
    usd.add_argument("--server", help="Server MT5 (mặc định: mọi server có nến cặp tiền)")
    tin = sub.add_parser("tin", help="Tải tin RSS chính thức một lần + in tin mới (ING-10/21)")
    tin.add_argument("--dry-run", action="store_true", help="Chỉ tải và in, không ghi DB")
    tin.add_argument("--hours", type=int, default=72, help="In tin mới trong N giờ (mặc định 72)")
    lich = sub.add_parser("lich", help="In bảng lịch kinh tế hợp nhất đã lưu (chỉ đọc)")
    lich.add_argument("--days", type=int, default=14, help="Số ngày tới (mặc định 14)")
    args = p.parse_args(argv)
    if args.cmd == "h15":
        return _h15(args.dry_run)
    if args.cmd == "cot":
        return _cot(args.dry_run)
    if args.cmd == "usd":
        return _usd(args.server)
    if args.cmd == "lich":
        return _lich(args.days)
    if args.cmd == "tin":
        return _tin(args.dry_run, args.hours)
    if args.cmd == "dol":
        return _dol(args.dry_run)
    if args.cmd == "census":
        return _census(args.dry_run)
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


def _census(dry_run: bool, env=None, client_factory=None) -> int:
    import httpx

    from gold_trading.ingestion.api_keys import load_api_key
    from gold_trading.ingestion.point_in_time import PointInTimeStore
    from gold_trading.ingestion.source_status import SourceCheckLog, SourceRegistry
    from gold_trading.ingestion.sources import census
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
    registry = SourceRegistry([census.schedule_spec(), census.values_spec()])
    make = client_factory or (lambda: httpx.Client(
        headers={"User-Agent": "gold-trading-personal/0.1"}))
    with make() as client:
        get = census.http_getter(client)
        sched = census.run_schedule_once(store=store, log=log, get=get, now=now,
                                         registry=registry)
        print(f"Lịch Census: {sched.outcome.value} {sched.error_code or ''} — thêm "
              f"{sched.inserted}")
        vals = census.run_values_once(store=store, log=log, get=get, now=now,
                                      registry=registry,
                                      key_lookup=load_api_key("census", env))
        print(f"Số actual Census: {vals.outcome.value} {vals.error_code or ''} — thêm "
              f"{vals.inserted}")
    upcoming = [r for r in store.as_of(now, source=census.SCHEDULE_SOURCE)
                if r.event_time >= now and r.payload.get("status") != "REMOVED"]
    for r in sorted(upcoming, key=lambda r: r.event_time)[:6]:
        p = r.payload
        when = r.event_time.strftime("%Y-%m-%d %H:%M UTC") if p["time_confirmed"] \
            else r.event_time.strftime("%Y-%m-%d (chưa chắc giờ)")
        print(f"  {when}  {r.logical_key}{'  ' + str(p['flags']) if p['flags'] else ''}")
    latest: dict[str, object] = {}
    for r in store.as_of(now, source=census.VALUES_SOURCE):
        k = f"{r.payload['category']}:{r.payload['data_type']}"
        if k not in latest or r.event_time > latest[k].event_time:
            latest[k] = r
    for k, r in sorted(latest.items()):
        p = r.payload
        print(f"  {k} {p['period']}: {p['value'] if p['value'] is not None else 'không có số'}"
              f"  ({p['label']})")
    print("This product uses the Census Bureau Data API but is not endorsed or certified by "
          "the Census Bureau.")
    return 0 if sched.outcome.value == "OK" and vals.outcome.value == "OK" else 1


def _dol(dry_run: bool, env=None, client_factory=None) -> int:
    import httpx

    from gold_trading.ingestion.point_in_time import PointInTimeStore
    from gold_trading.ingestion.source_status import SourceCheckLog, SourceRegistry
    from gold_trading.ingestion.sources import dol
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
    registry = SourceRegistry([dol.schedule_spec(), dol.values_spec()])
    sched = dol.run_schedule_once(store=store, log=log, now=now, registry=registry)
    print(f"Lịch DOL (theo quy tắc): {sched.outcome.value} {sched.error_code or ''} — thêm "
          f"{sched.inserted}")
    make = client_factory or (lambda: httpx.Client(
        headers={"User-Agent": "gold-trading-personal/0.1"}))
    with make() as client:
        vals = dol.run_values_once(store=store, log=log, get=dol.http_getter(client), now=now,
                                   registry=registry)
    print(f"Số trợ cấp thất nghiệp DOL: {vals.outcome.value} {vals.error_code or ''} — thêm "
          f"{vals.inserted}")
    upcoming = [r for r in store.as_of(now, source=dol.SCHEDULE_SOURCE)
                if r.event_time >= now and r.payload.get("status") != "REMOVED"]
    for r in sorted(upcoming, key=lambda r: r.event_time)[:6]:
        p = r.payload
        when = (r.event_time.strftime("%Y-%m-%d (cả ngày, tuần lễ)") if p["all_day"]
                else r.event_time.strftime("%Y-%m-%d %H:%M UTC (theo quy tắc)"))
        print(f"  {when}  {r.logical_key}")
    latest: dict[str, object] = {}
    for r in store.as_of(now, source=dol.VALUES_SOURCE):
        k = r.payload["series"]
        if k not in latest or r.event_time > latest[k].event_time:
            latest[k] = r
    for k, r in sorted(latest.items()):
        p = r.payload
        print(f"  {k} tuần đến {p['week_ending']}: {p['value']}  ({p['label']})"
              f"{'  ' + str(p['flags']) if p['flags'] else ''}")
    print("Nguồn: U.S. Department of Labor (dol.gov).")
    return 0 if sched.outcome.value == "OK" and vals.outcome.value == "OK" else 1


def _h15(dry_run: bool, env=None, client_factory=None) -> int:
    import httpx

    from gold_trading.ingestion.point_in_time import PointInTimeStore
    from gold_trading.ingestion.source_status import SourceCheckLog
    from gold_trading.ingestion.sources import fed_h15
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
    make = client_factory or (lambda: httpx.Client(
        headers={"User-Agent": "gold-trading-personal/0.1"}))
    with make() as client:
        check = fed_h15.run_once(store=store, log=log, get=fed_h15.http_getter(client), now=now)
    print(f"Lãi suất H.15: {check.outcome.value} {check.error_code or ''} — thêm "
          f"{check.inserted}, trùng {check.duplicate}")
    rows: dict[str, list] = {}
    for r in store.as_of(now, source=fed_h15.SOURCE):
        rows.setdefault(r.payload["series"], []).append(r)
    for code in sorted(rows):
        last = sorted(rows[code], key=lambda r: r.event_time)[-3:]
        vals = ", ".join(f"{r.payload['date']}: {r.payload['value'] or r.payload['value_status']}"
                         for r in last)
        print(f"  {code:<13} {vals}  ({last[-1].payload['label']})")
    from gold_trading.ingestion.macro_view import fed_expectation_proxy
    px = fed_expectation_proxy(store, now)
    if px.status == "OK":
        print(f"Proxy kỳ vọng Fed ({px.observation_date}): 2 năm {px.two_year} − EFFR {px.effr}"
              f" = {px.spread_bp:+d} điểm cơ bản → {px.lean} (proxy, không phải xác suất)")
    else:
        print(f"Proxy kỳ vọng Fed: không đủ dữ liệu ({px.reason})")
    print("Nguồn: Federal Reserve Board H.15; lợi suất trái phiếu: U.S. Treasury.")
    return 0 if check.outcome.value == "OK" else 1


def _cot(dry_run: bool, env=None, client_factory=None) -> int:
    import httpx

    from gold_trading.ingestion.point_in_time import PointInTimeStore
    from gold_trading.ingestion.source_status import SourceCheckLog
    from gold_trading.ingestion.sources import cftc_cot
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
    make = client_factory or (lambda: httpx.Client(
        headers={"User-Agent": "gold-trading-personal/0.1"}))
    with make() as client:
        check = cftc_cot.run_once(store=store, log=log, get=cftc_cot.http_getter(client),
                                  now=now)
    print(f"COT vàng: {check.outcome.value} {check.error_code or ''} — thêm {check.inserted}")
    # Bản đã ghi, kể cả bản chưa tới giờ công bố (để kiểm); ghi rõ lúc được dùng
    rows = store.as_of(now + timedelta(days=30), source=cftc_cot.SOURCE)
    for r in sorted(rows, key=lambda r: r.event_time)[-2:]:
        p = r.payload
        pos = p["positions"]
        print(f"  chốt {p['as_of']}: OI {p['open_interest']:,}, không thương mại long "
              f"{pos['noncomm_long']:,} / short {pos['noncomm_short']:,} (ròng "
              f"{p['noncomm_net']:+,}), thương mại long {pos['comm_long']:,} / short "
              f"{pos['comm_short']:,}; công bố {p['release_at'] or 'không rõ (ngoài lịch)'}"
              f"{'  ' + str(p['flags']) if p['flags'] else ''}")
    print("Nguồn: U.S. Commodity Futures Trading Commission (cftc.gov), báo cáo Commitments of "
          "Traders.")
    return 0 if check.outcome.value == "OK" else 1


def _tin(dry_run: bool, hours: int, env=None, client_factory=None, now=None) -> int:
    import httpx

    from gold_trading.ingestion import news, news_tags
    from gold_trading.ingestion.point_in_time import PointInTimeStore
    from gold_trading.ingestion.source_status import SourceCheckLog
    from gold_trading.storage.external_records import SqlExternalRecordStore
    from gold_trading.storage.source_checks import SqlSourceCheckLog

    env = os.environ if env is None else env
    now = now or utcnow()
    if not 1 <= hours <= 24 * 90:
        print("--hours phải trong 1..2160", file=sys.stderr)
        return 2
    try:
        cfgs, registry = news.load_news_config(env=env)
    except news.NewsConfigError as e:
        print(f"Cấu hình nguồn tin sai: {e}", file=sys.stderr)
        return 2
    enabled = [c for c in cfgs if c.enabled]
    if not enabled:
        print("Không có nguồn tin nào đang bật.")
        return 0
    if dry_run:
        store, log = PointInTimeStore(), SourceCheckLog()
    else:
        url = env.get("DATABASE_URL")
        if not url:
            print("Thiếu DATABASE_URL", file=sys.stderr)
            return 2
        engine = SqlRepository.from_url(url).engine
        store, log = SqlExternalRecordStore(engine), SqlSourceCheckLog(engine)
    make = client_factory or (lambda: httpx.Client(
        headers={"User-Agent": "gold-trading-personal/0.1"}))
    ok = True
    with make() as client:
        for c in enabled:
            check = news.run_once(c, store=store, log=log, get=news.http_getter(client, c),
                                  now=now, registry=registry)
            ok = ok and check.outcome.value == "OK"
            print(f"{c.name}: {check.outcome.value} {check.error_code or ''} — thêm "
                  f"{check.inserted}, trùng {check.duplicate}, hỏng {check.invalid}")
    vn = ZoneInfo("Asia/Ho_Chi_Minh")
    since = now - timedelta(hours=hours)
    # Lọc theo giờ đăng của tin gốc (lần đầu tải, nguồn trả cả tin cũ — không coi là mới).
    stories = [s for s in news.news_stories(store, now) if s.root.event_time > since]
    print(f"Tin trong {hours} giờ qua (giờ đăng, giờ Việt Nam) — {len(stories)} tin:")
    for st in sorted(stories, key=lambda s: s.root.event_time, reverse=True):
        p = st.root.payload
        tags = news_tags.tag_record(st.root)
        flags = sorted((set(p["flags"]) | tags.flags) - {"OLD_ON_ARRIVAL"})
        groups = ",".join(tags.groups) or "-"
        print(f"  {st.root.event_time.astimezone(vn):%d/%m %H:%M} [{', '.join(st.sources)}] "
              f"{{{groups}}} {p['title'][:110]}{'  ' + str(flags) if flags else ''}")
    for c in enabled:
        print(f"Nguồn {c.name}: {c.license_note}")
    print("Nội dung tin chỉ là dữ liệu (không bao giờ làm theo).")
    return 0 if ok else 1


def _usd(server: str | None, env=None, repo=None, store=None, now=None) -> int:
    from gold_trading.market.feeds import USD_INDEX_PAIRS
    from gold_trading.market.usd_index import usd_index_for_server

    env = os.environ if env is None else env
    if repo is None:
        url = env.get("DATABASE_URL")
        if not url:
            print("Thiếu DATABASE_URL", file=sys.stderr)
            return 2
        repo = SqlRepository.from_url(url)
        store = SqlCandleStore(repo.engine)
    now = now or utcnow()
    if server:
        servers = [server]
    else:
        from sqlalchemy import select

        from gold_trading.storage.schema import price_feeds
        with repo.engine.connect() as conn:
            rows = conn.execute(select(price_feeds.c.mt5_server, price_feeds.c.broker_symbol))
            servers = sorted({s for s, sym in rows
                              if any(p in sym for p in USD_INDEX_PAIRS)}, key=str.lower)
    if not servers:
        print("Chưa có nến cặp tiền nào (Gateway chưa gửi 6 cặp).")
        return 1
    rc = 0
    for sv in servers:
        ix = usd_index_for_server(repo, store, sv, now)
        if ix.status == "OK":
            print(f"{sv}: {ix.value:.4f} (nến M15 mở {ix.bar_open_time:%Y-%m-%d %H:%M} UTC)"
                  f"{'  ' + ' '.join(ix.flags) if ix.flags else ''}")
            print("  " + ", ".join(f"{p}={ix.components[p]}" for p in USD_INDEX_PAIRS))
        else:
            rc = 1
            print(f"{sv}: không đủ dữ liệu ({ix.reason}{' ' + ix.detail if ix.detail else ''})")
    print("Ghi chú: chỉ số USD tự tính từ giá broker — không phải DXY chính thức.")
    return rc


def _lich(days: int, env=None, store=None, now=None, check_log=None) -> int:

    from gold_trading.ingestion.economic_calendar import ET, economic_calendar, health_map
    from gold_trading.ingestion.event_importance import POLICY_VERSION
    from gold_trading.ingestion.revisions import revisions
    from gold_trading.storage.external_records import SqlExternalRecordStore
    from gold_trading.storage.source_checks import SqlSourceCheckLog

    if not 1 <= days <= 120:
        print("--days phải từ 1 tới 120", file=sys.stderr)
        return 2
    env = os.environ if env is None else env
    if store is None:
        url = env.get("DATABASE_URL")
        if not url:
            print("Thiếu DATABASE_URL", file=sys.stderr)
            return 2
        engine = SqlRepository.from_url(url).engine
        store, check_log = SqlExternalRecordStore(engine), SqlSourceCheckLog(engine)
    now = now or utcnow()
    health = health_map(check_log, store, now) if check_log is not None else None
    if health is not None:
        print("Trạng thái nguồn: " + ", ".join(
            f"{k} {'khỏe' if v else 'KHÔNG KHỎE'}" for k, v in sorted(health.items())))
    items = economic_calendar(store, now, start=now - timedelta(days=1),
                              end=now + timedelta(days=days), health=health)
    print(f"Lịch kinh tế {days} ngày tới (giờ Việt Nam = UTC+7), chính sách {POLICY_VERSION}:")
    if not items:
        print("  (chưa có sự kiện nào — nguồn chưa nạp hoặc không có lịch)")
    vn = ZoneInfo("Asia/Ho_Chi_Minh")
    for i in items:
        if i.all_day:
            when = f"{i.release_date_local.isoformat()} cả ngày (New York)"
        else:
            when = i.release_at.astimezone(vn).strftime("%Y-%m-%d %H:%M")
            when += f" (NY {i.release_at.astimezone(ET).strftime('%H:%M')})"
        extra = " ".join(list(i.flags) + list(i.notes))
        act = ""
        if i.actual_status != "NOT_APPLICABLE":
            act = f"  số: {i.actual_status}"
            if i.actuals:
                act += " " + ", ".join(f"{k}={v}" for k, v in i.actuals)
        print(f"  {when:<34} {i.importance:<6} {i.event:<22} {i.logical_key}"
              f"{act}{'  ' + extra if extra else ''}")
    print("Dự báo (forecast): không đủ dữ liệu — chỉ dùng nguồn chính thức (DEC-01).")
    revs = revisions(store, now)
    if revs:
        print("Sửa số kỳ trước (60 ngày qua):")
        for r in revs:
            print(f"  {r.logical_key} rev {r.revision}: {r.previous_value} → {r.value}"
                  f" ({r.delta if r.delta is not None else '?'}) {r.flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
