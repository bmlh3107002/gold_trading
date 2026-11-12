"""MT-15: một Gateway trông coi NHIỀU terminal MT5 trên cùng một máy Windows.

Thư viện ``MetaTrader5`` chỉ nối được MỘT terminal trong một tiến trình Python, nên mỗi terminal
chạy trong một tiến trình con riêng (``mt5-gateway run --env-file <file> --name <tên>``), có
cấu hình + token riêng. Tiến trình cha (``run-all``) chỉ kiểm cấu hình, khởi động, và chạy lại
tiến trình con khi nó dừng. Không đọc MT5, không gửi gì lên backend.

Cấu hình: thư mục ``terminals/``, mỗi terminal một file ``<tên>.env`` (cùng khóa như
``gateway.env``). Bắt buộc với mỗi terminal: ``GT_MT5_PATH`` (đúng ``terminal64.exe``) và
``GT_INGEST_TOKEN`` riêng. Mặc định an toàn: sai một chỗ trong cấu hình chung (trùng token,
trùng terminal, thiếu đường dẫn...) → KHÔNG khởi động terminal nào.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from mt5_gateway import config
from mt5_gateway.config import MIN_TOKEN_LEN, Config
from mt5_gateway.reader import norm_terminal_dir

log = logging.getLogger("mt5_gateway.multi")

NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
MAX_TERMINALS = 20
RESTART_MIN_S = 30.0
RESTART_MAX_S = 300.0
HEALTHY_RUN_S = 600.0  # chạy được lâu hơn mức này rồi mới dừng → coi là lỗi mới, đặt lại backoff
START_GAP_S = 3.0  # giãn thời điểm khởi động (mỗi terminal nạp bù lịch sử khá nặng)
STOP_WAIT_S = 10.0


@dataclass(frozen=True)
class Terminal:
    name: str
    env_file: Path
    cfg: Config


def discover(folder: Path) -> list[Path]:
    """Các file ``*.env`` trong thư mục, theo thứ tự tên (không lấy thư mục con)."""
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.glob("*.env") if p.is_file())


def load_terminals(
    folder: Path, *, exists: Callable[[str], bool] | None = None
) -> tuple[list[Terminal], list[str]]:
    """Đọc + kiểm cấu hình mọi terminal. Trả (terminals, lỗi). Có lỗi → không chạy terminal nào.

    Không bao giờ đưa token vào thông báo lỗi (chỉ nêu tên file).
    """
    exists = exists or os.path.exists
    files = discover(folder)
    errors: list[str] = []
    if not files:
        return [], [
            f"Không thấy file cấu hình terminal nào (*.env) trong thư mục {folder}. "
            "Mỗi terminal MT5 cần một file, ví dụ terminals\\lordtrade.env"
        ]
    if len(files) > MAX_TERMINALS:
        return [], [f"Quá nhiều terminal ({len(files)} > {MAX_TERMINALS}): kiểm lại thư mục"]

    out: list[Terminal] = []
    for f in files:
        name = f.stem
        if not NAME_RE.match(name):
            errors.append(
                f"{f.name}: tên file chỉ dùng chữ không dấu, số, '-' hoặc '_' (tối đa 32 ký tự)"
            )
            continue
        try:
            cfg = config.load(f, use_environ=False, name=name)
        except ValueError as e:  # GT_TIMEFRAMES sai, số không hợp lệ...
            errors.append(f"{f.name}: {e}")
            continue
        if not cfg.terminal_path:
            errors.append(
                f"{f.name}: thiếu GT_MT5_PATH. Máy chạy nhiều MT5 thì mỗi file phải chỉ rõ "
                "terminal64.exe của terminal đó"
            )
        elif not norm_terminal_dir(cfg.terminal_path):
            errors.append(f"{f.name}: GT_MT5_PATH không hợp lệ")
        elif not exists(cfg.terminal_path):
            errors.append(f"{f.name}: không thấy file {cfg.terminal_path}")
        if len(cfg.token) < MIN_TOKEN_LEN:
            errors.append(f"{f.name}: GT_INGEST_TOKEN thiếu hoặc ngắn hơn {MIN_TOKEN_LEN} ký tự")
        out.append(Terminal(name, f, cfg))

    # Trùng nhau giữa các terminal: mỗi lỗi nêu đủ các file liên quan.
    def dupes(key: Callable[[Terminal], str | None], what: str) -> None:
        seen: dict[str, list[str]] = {}
        for t in out:
            k = key(t)
            if k:
                seen.setdefault(k, []).append(t.env_file.name)
        for names in seen.values():
            if len(names) > 1:
                errors.append(f"{', '.join(names)}: {what}")

    dupes(
        lambda t: t.cfg.token if len(t.cfg.token) >= MIN_TOKEN_LEN else None,
        "dùng CHUNG một token. Mỗi terminal phải có token riêng (token của đúng tài khoản "
        "giao dịch dùng MT5 đó)",
    )
    dupes(
        lambda t: norm_terminal_dir(t.cfg.terminal_path) if t.cfg.terminal_path else None,
        "trỏ tới CÙNG một terminal MT5. Mỗi file phải trỏ tới terminal64.exe của một MT5 khác",
    )
    dupes(lambda t: t.cfg.gateway_id.casefold(), "trùng GT_GATEWAY_ID")
    return (out if not errors else []), errors


def child_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Môi trường cho tiến trình con: BỎ mọi biến ``GT_*`` (biến chung sẽ đè cấu hình riêng
    của từng terminal — ví dụ hai terminal cùng một token)."""
    env = dict(os.environ if base is None else base)
    for k in [k for k in env if k.upper().startswith("GT_")]:
        del env[k]
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def gt_vars_in_environ(base: dict[str, str] | None = None) -> list[str]:
    env = os.environ if base is None else base
    return sorted(k for k in env if k.upper().startswith("GT_"))


def child_command(t: Terminal, command: str = "run", extra: Sequence[str] = ()) -> list[str]:
    return [
        sys.executable, "-m", "mt5_gateway.cli", command,
        "--env-file", str(t.env_file), "--name", t.name, *extra,
    ]


class Proc(Protocol):
    def poll(self) -> int | None: ...
    def terminate(self) -> None: ...
    def kill(self) -> None: ...
    def wait(self, timeout: float | None = None) -> int: ...


def popen(t: Terminal, command: str = "run", extra: Sequence[str] = ()) -> Proc:
    return subprocess.Popen(child_command(t, command, extra), env=child_env())


@dataclass
class _Slot:
    term: Terminal
    proc: Proc | None = None
    started_at: float = 0.0
    next_start: float = 0.0
    backoff: float = RESTART_MIN_S
    restarts: int = 0
    exits: list[int] = field(default_factory=list)


class Supervisor:
    """Giữ mỗi terminal một tiến trình con. Con dừng (lỗi MT5, check chưa đạt, crash...) →
    chạy lại sau ``backoff`` (30 s, gấp đôi tới 5 phút). Lỗi một terminal không ảnh hưởng
    terminal khác."""

    def __init__(
        self,
        terminals: list[Terminal],
        *,
        spawn: Callable[[Terminal], Proc] = popen,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.spawn, self.clock, self.sleep = spawn, clock, sleep
        now = clock()
        self.slots = [
            _Slot(t, next_start=now + i * START_GAP_S) for i, t in enumerate(terminals)
        ]

    def step(self) -> None:
        now = self.clock()
        for s in self.slots:
            if s.proc is not None:
                code = s.proc.poll()
                if code is None:
                    continue
                s.exits.append(code)
                ran = now - s.started_at
                if ran >= HEALTHY_RUN_S:
                    s.backoff = RESTART_MIN_S
                s.next_start = now + s.backoff
                log.warning(
                    "[%s] Gateway của terminal này đã dừng (mã %s) sau %.0f giây. "
                    "Chạy lại sau %.0f giây. Các terminal khác vẫn chạy.",
                    s.term.name, code, ran, s.backoff,
                )
                s.backoff = min(s.backoff * 2, RESTART_MAX_S)
                s.proc = None
            if s.proc is None and now >= s.next_start:
                try:
                    s.proc = self.spawn(s.term)
                except OSError as e:
                    log.error("[%s] Không khởi động được: %s", s.term.name, e)
                    s.next_start = now + s.backoff
                    s.backoff = min(s.backoff * 2, RESTART_MAX_S)
                    continue
                s.started_at = now
                if s.exits:
                    s.restarts += 1
                    log.info("[%s] Đã chạy lại (lần %d)", s.term.name, s.restarts)

    def stop_all(self) -> None:
        running = [s for s in self.slots if s.proc is not None and s.proc.poll() is None]
        for s in running:
            try:
                s.proc.terminate()  # type: ignore[union-attr]
            except OSError:
                pass
        for s in running:
            try:
                s.proc.wait(timeout=STOP_WAIT_S)  # type: ignore[union-attr]
            except Exception:
                try:
                    s.proc.kill()  # type: ignore[union-attr]
                except OSError:
                    pass
        for s in self.slots:
            s.proc = None

    def run_forever(self, stop: Callable[[], bool] = lambda: False, tick_s: float = 1.0) -> None:
        try:
            while not stop():
                self.step()
                self.sleep(tick_s)
        finally:
            self.stop_all()


def check_all(
    terminals: list[Terminal],
    *,
    run: Callable[[list[str]], Any] | None = None,
) -> dict[str, int]:
    """Chạy ``check`` cho từng terminal LẦN LƯỢT (mỗi terminal một tiến trình con). Trả mã thoát."""

    def _run(cmd: list[str]) -> int:
        return subprocess.run(cmd, env=child_env()).returncode

    runner = run or _run
    return {t.name: int(runner(child_command(t, "check"))) for t in terminals}
