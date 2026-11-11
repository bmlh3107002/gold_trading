"""mt5-gateway check | run"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


def _mt5():
    try:
        import MetaTrader5 as mt5
    except ImportError:
        print(
            "Không tìm thấy thư viện MetaTrader5. Gateway phải chạy trên Windows có cài MT5.",
            file=sys.stderr,
        )
        raise SystemExit(2) from None
    return mt5


def main(argv: list[str] | None = None) -> int:
    from mt5_gateway import config
    from mt5_gateway.backend_client import BackendClient
    from mt5_gateway.checks import print_report, run_checks
    from mt5_gateway.sync import Syncer

    p = argparse.ArgumentParser(prog="mt5-gateway", description="MT5 Gateway bản chỉ đọc")
    p.add_argument("command", choices=["check", "run"])
    p.add_argument("--env-file", default="gateway.env", type=Path)
    args = p.parse_args(argv)

    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows console: hiển thị tiếng Việt
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = config.load(args.env_file)
    mt5 = _mt5()
    client = BackendClient(cfg.backend_url, cfg.token)
    print("Đang kiểm tra (có thể mất 1–2 phút, đừng tắt)...", flush=True)
    rep = run_checks(cfg, mt5, client, progress=lambda m: print("  " + m, flush=True))
    print_report(rep)
    if args.command == "check" or not rep.ok:
        if rep.reader:
            rep.reader.shutdown()
        return 0 if rep.ok else 1

    syncer = Syncer(cfg, rep.reader, client, rep)
    try:
        print("Đang chạy (chỉ đọc): nạp bù lịch sử rồi đồng bộ nến. Nhấn Ctrl+C để dừng.")
        syncer.run_forever()
    except KeyboardInterrupt:
        print("Đã dừng.")
    finally:
        rep.reader.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
