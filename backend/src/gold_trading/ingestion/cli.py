"""Nạp nến từ CSV vào database.

    python -m gold_trading.ingestion.cli import-csv FILE --server-tz Europe/Athens

Trong Docker:

    docker compose cp XAUUSD_M15.csv backend:/tmp/data.csv
    docker compose exec backend python -m gold_trading.ingestion.cli import-csv /tmp/data.csv \\
        --server-tz Europe/Athens

Dữ liệu nạp có nguồn CSV; muốn Dashboard dùng nó thì đặt GT_DATA_SOURCE=CSV.
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
    imp.add_argument("--timeframe", default="M15", choices=[t.value for t in Timeframe])
    imp.add_argument("--dry-run", action="store_true", help="Chỉ đọc và kiểm tra, không ghi DB")
    args = p.parse_args(argv)

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
        timeframe=Timeframe(args.timeframe),
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


if __name__ == "__main__":
    raise SystemExit(main())
