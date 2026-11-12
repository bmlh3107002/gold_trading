"""GW-06: chạy nền — log ra file xoay vòng, chặn hai Gateway cùng một cấu hình."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from mt5_gateway import cli
from mt5_gateway.runtime import LOG_BACKUPS, LOG_MAX_BYTES, AlreadyRunning, InstanceLock

ROOT = Path(__file__).resolve().parents[1]


def test_lock_blocks_second_and_releases(tmp_path):
    a, b = InstanceLock(tmp_path / "gateway.env.lock"), InstanceLock(tmp_path / "gateway.env.lock")
    a.acquire()
    with pytest.raises(AlreadyRunning, match="đang chạy"):
        b.acquire()
    a.release()
    b.acquire()  # nhả rồi thì lấy được
    b.release()


def test_lock_released_when_process_dies(tmp_path):
    """Mất điện / tiến trình bị giết: hệ điều hành tự nhả khóa, lần chạy sau không bị kẹt."""
    lock = tmp_path / "x.lock"
    src, lk = ROOT / "src", lock
    code = (f"import sys,time; sys.path.insert(0, r'{src}');"
            "from mt5_gateway.runtime import InstanceLock; import pathlib;"
            f"L = InstanceLock(pathlib.Path(r'{lk}')); L.acquire(); print('ok', flush=True);"
            "time.sleep(60)")
    p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    assert p.stdout.readline().strip() == "ok"
    with pytest.raises(AlreadyRunning):
        InstanceLock(lock).acquire()
    p.kill()
    p.wait()
    time.sleep(0.1)
    InstanceLock(lock).acquire()


def test_cli_run_refuses_when_already_running(tmp_path, capsys):
    env = tmp_path / "gateway.env"
    env.write_text("GT_INGEST_TOKEN=" + "x" * 32 + "\n", "utf-8")
    held = InstanceLock(tmp_path / "gateway.env.lock")
    held.acquire()
    assert cli.main(["run", "--env-file", str(env)]) == 3  # không đụng tới MT5
    assert "đang chạy" in capsys.readouterr().out
    held.release()


def test_cli_run_all_lock_and_config_errors_go_to_log_file(tmp_path):
    folder = tmp_path / "terminals"
    folder.mkdir()
    logs = tmp_path / "logs"
    assert cli.main(["run-all", "--dir", str(folder), "--log-dir", str(logs)]) == 1
    text = (logs / "run-all.log").read_text("utf-8")
    assert "CẤU HÌNH NHIỀU TERMINAL CHƯA ĐÚNG" in text  # chạy ẩn vẫn thấy lỗi trong file


def test_log_file_rotation_settings(tmp_path):
    from mt5_gateway.runtime import file_handler

    h = file_handler(tmp_path / "logs" / "g.log", "%(message)s")
    assert h.maxBytes == LOG_MAX_BYTES == 5 * 1024 * 1024 and h.backupCount == LOG_BACKUPS == 5
    assert (tmp_path / "logs").is_dir()
    h.close()


def test_children_get_their_own_log_file():
    from mt5_gateway import multi
    from tests.test_gateway import cfg

    t = multi.Terminal("exness", Path("terminals/exness.env"), cfg())
    cmd = multi.child_command(t, "run", ["--log-file", str(Path("logs/exness.log"))])
    assert cmd[-2:] == ["--log-file", str(Path("logs/exness.log"))]


def test_powershell_scripts_utf8_bom_and_safe():
    for name in ("cai-tu-chay.ps1", "go-tu-chay.ps1"):
        raw = (ROOT / "scripts" / name).read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf")  # PowerShell 5 đọc đúng tiếng Việt
        text = raw.decode("utf-8-sig")
        assert "order" not in text.lower() and "Invoke-WebRequest" not in text
    inst = (ROOT / "scripts" / "cai-tu-chay.ps1").read_text("utf-8-sig")
    assert "-LogonType Interactive" in inst  # chạy trong phiên người dùng (thấy được MT5)
    assert "-MultipleInstances IgnoreNew" in inst and "RestartCount" in inst
    assert "mt5-gateway $Check" in inst and "$LASTEXITCODE -ne 0" in inst  # check trước khi cài
