"""GW-06: chạy nền lâu dài trên Windows — ghi log ra file có xoay vòng, chặn chạy trùng.

- Log file: ``RotatingFileHandler`` 5 MB × 5 file (không đầy ổ đĩa), UTF-8.
- Chặn chạy trùng: khóa file ``<cấu hình>.lock`` (Windows: ``msvcrt.locking``; nơi khác:
  ``fcntl.flock``). Hệ điều hành tự nhả khóa khi tiến trình chết → không kẹt khóa sau mất điện.
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import IO

LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUPS = 5


def file_handler(path: Path, fmt: str) -> logging.Handler:
    path.parent.mkdir(parents=True, exist_ok=True)
    h = RotatingFileHandler(path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS,
                            encoding="utf-8")
    h.setFormatter(logging.Formatter(fmt))
    return h


class AlreadyRunning(RuntimeError):
    pass


class InstanceLock:
    """Một cấu hình (một terminal) chỉ một Gateway chạy cùng lúc."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._f: IO[str] | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        f = open(self.path, "a+", encoding="utf-8")  # noqa: SIM115 — giữ mở suốt đời tiến trình
        try:
            if sys.platform == "win32":
                import msvcrt

                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.close()
            raise AlreadyRunning(
                f"Đã có một Gateway khác đang chạy với cấu hình này (khóa {self.path.name}). "
                "Có thể Gateway đang tự chạy nền (Task Scheduler): xem log trong thư mục logs, "
                "hoặc dừng nó trước khi chạy tay."
            ) from None
        f.seek(0)
        f.truncate()
        f.write(str(os.getpid()))
        f.flush()
        self._f = f

    def release(self) -> None:
        if self._f is not None:
            try:
                self._f.close()
            finally:
                self._f = None
