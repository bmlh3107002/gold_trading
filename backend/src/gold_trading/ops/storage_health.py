"""Tình trạng sao lưu và ổ đĩa cho Dashboard (DB-09, case 0-C04, 0-C05).

- Bản sao lưu do container ``backup`` ghi; backend chỉ ĐỌC ``status.json`` (mount chỉ đọc).
- Ổ đĩa: đo ổ của container (trên Docker Desktop là ổ ảo chứa cả volume DB) và ổ chứa bản
  sao lưu. > 85% → cảnh báo.
Không có thông tin → báo "không rõ", không giả định là ổn.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from gold_trading.common.time import utcnow

DISK_WARN_PCT = 85.0
STALE_MARGIN = timedelta(hours=2)

BackupState = Literal["OK", "STALE", "FAILED", "MISSING", "DISABLED"]


@dataclass(frozen=True)
class DiskUsage:
    name: str
    used_pct: float | None
    free_gb: float | None
    warn: bool


@dataclass(frozen=True)
class BackupInfo:
    state: BackupState
    last_finished_at: datetime | None
    last_result: str | None
    app_file: str | None
    keycloak_file: str | None
    app_count: int | None
    keycloak_count: int | None


def disk(name: str, path: str | Path) -> DiskUsage:
    try:
        u = shutil.disk_usage(path)
    except OSError:
        return DiskUsage(name, None, None, False)
    pct = round(u.used / u.total * 100, 1) if u.total else None
    return DiskUsage(name, pct, round(u.free / 1e9, 1), pct is not None and pct > DISK_WARN_PCT)


def backup_info(backup_dir: str | None, now: datetime | None = None) -> BackupInfo:
    if not backup_dir:
        return BackupInfo("DISABLED", None, None, None, None, None, None)
    now = now or utcnow()
    path = Path(backup_dir) / "status.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        finished = datetime.fromisoformat(str(raw["finished_at"]).replace("Z", "+00:00"))
        interval = timedelta(hours=float(raw.get("interval_hours", 24)))
    except (OSError, ValueError, KeyError, TypeError):
        return BackupInfo("MISSING", None, None, None, None, None, None)
    result = str(raw.get("result", ""))
    if result != "OK":
        state: BackupState = "FAILED"
    elif now - finished > interval + STALE_MARGIN:
        state = "STALE"
    else:
        state = "OK"

    def _int(k):
        v = raw.get(k)
        return v if isinstance(v, int) else None

    return BackupInfo(
        state, finished, result or None, raw.get("app_file") or None,
        raw.get("keycloak_file") or None, _int("app_count"), _int("keycloak_count"),
    )
