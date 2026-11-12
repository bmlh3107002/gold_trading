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


def _setup_output(name: str | None, log_file: Path | None = None) -> None:
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows console: hiển thị tiếng Việt
    tag = f"[{name}] " if name else ""
    fmt = f"%(asctime)s {tag}%(levelname)s %(message)s"
    handlers: list[logging.Handler] = []
    if sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))
    if log_file is not None:
        from mt5_gateway.runtime import file_handler

        handlers.append(file_handler(log_file, fmt))  # GW-06: chạy nền → log ra file
    logging.basicConfig(level=logging.INFO, format=fmt, handlers=handlers, force=True)


def _multi(command: str, folder: Path, log_dir: Path | None = None) -> int:
    from mt5_gateway import multi

    log = logging.getLogger("mt5_gateway")
    terms, errors = multi.load_terminals(folder)
    if errors:
        # Qua logging: chạy nền (--log-dir) thì lỗi vẫn nằm trong file log, không mất.
        log.error("CẤU HÌNH NHIỀU TERMINAL CHƯA ĐÚNG (%s) — chưa chạy terminal nào:", folder)
        for e in errors:
            log.error("  - %s", e)
        return 1
    extra = multi.gt_vars_in_environ()
    if extra:
        log.warning("Lưu ý: bỏ qua biến môi trường %s — mỗi terminal chỉ dùng cấu hình trong "
                    "file của nó.", ", ".join(extra))
    names = ", ".join(f"{t.name} ({t.cfg.terminal_path})" for t in terms)
    log.info("%d terminal: %s", len(terms), names)
    if command == "check-all":
        codes = multi.check_all(terms)
        print("")
        print("=== TỔNG KẾT ===")
        for n, c in codes.items():
            print(f"  {n}: {'SẴN SÀNG' if c == 0 else 'CHƯA SẴN SÀNG (xem kết quả phía trên)'}")
        return 0 if all(c == 0 for c in codes.values()) else 1
    from mt5_gateway.runtime import AlreadyRunning, InstanceLock

    lock = InstanceLock(folder / ".run-all.lock")
    try:
        lock.acquire()
    except AlreadyRunning as e:
        logging.getLogger("mt5_gateway").error("%s", e)
        return 3
    extra_args = (lambda t: ["--log-file", str(log_dir / f"{t.name}.log")]) if log_dir else None
    sup = multi.Supervisor(terms, spawn=lambda t: multi.popen(t, extra=extra_args(t)
                                                              if extra_args else ()))
    logging.getLogger("mt5_gateway").info(
        "Đang chạy (chỉ đọc) mỗi terminal một tiến trình. Nhấn Ctrl+C để dừng tất cả.")
    try:
        sup.run_forever()
    except KeyboardInterrupt:
        print("Đã dừng tất cả.")
    finally:
        lock.release()
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
    p.add_argument("--log-file", default=None, type=Path,
                   help="run/check: ghi log ra file (xoay vòng 5 MB × 5) — dùng khi chạy nền")
    p.add_argument("--log-dir", default=None, type=Path,
                   help="run-all/check-all: thư mục log (run-all.log + <tên terminal>.log)")
    args = p.parse_args(argv)

    if args.command in ("check-all", "run-all"):
        _setup_output(None, args.log_dir / f"{args.command}.log" if args.log_dir else None)
        return _multi(args.command, args.dir, args.log_dir)
    _setup_output(args.name, args.log_file)

    tag = f"[{args.name}] " if args.name else ""
    to_file = args.log_file is not None
    out_log = logging.getLogger("mt5_gateway.check")

    def say(msg: str = "") -> None:
        if to_file:
            out_log.info("%s", msg)  # vào cả màn hình (nếu có) và file
        else:
            print(tag + msg if msg else msg, flush=True)

    lock = None
    if args.command == "run":
        from mt5_gateway.runtime import AlreadyRunning, InstanceLock

        # GW-06: một cấu hình chỉ một Gateway (tự chạy nền + chạy tay cùng lúc → từ chối)
        lock = InstanceLock(args.env_file.with_name(args.env_file.name + ".lock"))
        try:
            lock.acquire()
        except AlreadyRunning as e:
            logging.getLogger("mt5_gateway").error("%s", e)
            return 3
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
