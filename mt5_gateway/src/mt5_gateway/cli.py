"""mt5-gateway check | run | check-all | run-all

- ``check`` / ``run``: một terminal, cấu hình ở ``gateway.env`` (như cũ).
- ``check-all`` / ``run-all`` (MT-15): nhiều terminal MT5 trên một máy, mỗi terminal một file
  ``terminals/<tên>.env`` với token + ``GT_MT5_PATH`` riêng; mỗi terminal chạy trong một tiến
  trình con riêng (thư viện MetaTrader5 chỉ nối một terminal mỗi tiến trình).
"""

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


def _setup_output(name: str | None) -> None:
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows console: hiển thị tiếng Việt
    tag = f"[{name}] " if name else ""
    logging.basicConfig(level=logging.INFO, format=f"%(asctime)s {tag}%(levelname)s %(message)s")


def _multi(command: str, folder: Path) -> int:
    from mt5_gateway import multi

    terms, errors = multi.load_terminals(folder)
    if errors:
        print(f"CẤU HÌNH NHIỀU TERMINAL CHƯA ĐÚNG ({folder}) — chưa chạy terminal nào:")
        for e in errors:
            print(f"  - {e}")
        return 1
    extra = multi.gt_vars_in_environ()
    if extra:
        print(
            "Lưu ý: bỏ qua biến môi trường "
            f"{', '.join(extra)} — mỗi terminal chỉ dùng cấu hình trong file của nó."
        )
    names = ", ".join(f"{t.name} ({t.cfg.terminal_path})" for t in terms)
    print(f"{len(terms)} terminal: {names}")
    if command == "check-all":
        codes = multi.check_all(terms)
        print("")
        print("=== TỔNG KẾT ===")
        for n, c in codes.items():
            print(f"  {n}: {'SẴN SÀNG' if c == 0 else 'CHƯA SẴN SÀNG (xem kết quả phía trên)'}")
        return 0 if all(c == 0 for c in codes.values()) else 1
    sup = multi.Supervisor(terms)
    print("Đang chạy (chỉ đọc) mỗi terminal một tiến trình. Nhấn Ctrl+C để dừng tất cả.")
    try:
        sup.run_forever()
    except KeyboardInterrupt:
        print("Đã dừng tất cả.")
    return 0


def main(argv: list[str] | None = None) -> int:
    from mt5_gateway import config
    from mt5_gateway.backend_client import BackendClient
    from mt5_gateway.checks import print_report, run_checks
    from mt5_gateway.sync import Syncer

    p = argparse.ArgumentParser(prog="mt5-gateway", description="MT5 Gateway bản chỉ đọc")
    p.add_argument("command", choices=["check", "run", "check-all", "run-all"])
    p.add_argument("--env-file", default="gateway.env", type=Path)
    p.add_argument("--dir", default="terminals", type=Path,
                   help="check-all/run-all: thư mục chứa <tên>.env của từng terminal")
    # --name: do run-all đặt cho tiến trình con (nhãn log + gateway_id mặc định)
    p.add_argument("--name", default=None, help=argparse.SUPPRESS)
    args = p.parse_args(argv)

    _setup_output(args.name)
    if args.command in ("check-all", "run-all"):
        return _multi(args.command, args.dir)

    tag = f"[{args.name}] " if args.name else ""

    def say(msg: str = "") -> None:
        print(tag + msg if msg else msg, flush=True)

    # Tiến trình con của run-all: chỉ đọc file của terminal đó (không để biến môi trường đè).
    cfg = config.load(args.env_file, use_environ=args.name is None, name=args.name)
    mt5 = _mt5()
    client = BackendClient(cfg.backend_url, cfg.token)
    say("Đang kiểm tra (có thể mất 1–2 phút, đừng tắt)...")
    rep = run_checks(cfg, mt5, client, progress=lambda m: say("  " + m))
    print_report(rep, out=say)
    if args.command == "check" or not rep.ok:
        if rep.reader:
            rep.reader.shutdown()
        return 0 if rep.ok else 1

    syncer = Syncer(cfg, rep.reader, client, rep)
    try:
        say("Đang chạy (chỉ đọc): nạp bù lịch sử rồi đồng bộ nến. Nhấn Ctrl+C để dừng.")
        syncer.run_forever()
    except KeyboardInterrupt:
        say("Đã dừng.")
    finally:
        rep.reader.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
