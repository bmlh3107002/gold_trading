"""DB-09: trạng thái sao lưu + ổ đĩa (0-C05: cảnh báo 85%, ổ đầy → ingest báo lỗi rõ, không mất
dữ liệu đã ghi)."""

from __future__ import annotations

import json
from collections import namedtuple
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import OperationalError

from gold_trading.contracts.candle import DataSource
from gold_trading.market.timeframes import Timeframe
from gold_trading.ops import storage_health
from gold_trading.ops.storage_health import backup_info, disk
from gold_trading.storage.candles import SqlCandleStore
from gold_trading.storage.repository import SqlRepository
from tests.auth_helpers import client, make_app
from tests.test_ingest_api import bars, batch

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
TOKEN = "t" * 32


def write_status(tmp_path, **over):
    body = {"result": "OK", "finished_at": "2026-11-06T03:00:00Z", "interval_hours": 24,
            "app_file": "app-x.dump", "keycloak_file": "keycloak-x.dump", "app_count": 7,
            "keycloak_count": 7, "disk_used_pct": 40, "keep": 14}
    body.update(over)
    (tmp_path / "status.json").write_text(json.dumps(body))


def test_backup_ok_stale_failed_missing(tmp_path):
    assert backup_info(None).state == "DISABLED"
    assert backup_info(str(tmp_path), NOW).state == "MISSING"
    write_status(tmp_path)
    info = backup_info(str(tmp_path), NOW)
    assert info.state == "OK" and info.app_count == 7
    assert backup_info(str(tmp_path), NOW + timedelta(hours=24)).state == "STALE"
    write_status(tmp_path, result="FAILED")
    assert backup_info(str(tmp_path), NOW).state == "FAILED"
    (tmp_path / "status.json").write_text("{broken")
    assert backup_info(str(tmp_path), NOW).state == "MISSING"


def test_disk_warn_above_85(monkeypatch):
    U = namedtuple("U", "total used free")
    monkeypatch.setattr(storage_health.shutil, "disk_usage", lambda p: U(100, 86, 14))
    assert disk("docker", "/").warn is True
    monkeypatch.setattr(storage_health.shutil, "disk_usage", lambda p: U(100, 85, 15))
    assert disk("docker", "/").warn is False

    def boom(p):
        raise OSError("no such path")

    monkeypatch.setattr(storage_health.shutil, "disk_usage", boom)
    d = disk("backups", "/nope")
    assert d.used_pct is None and d.warn is False


def test_health_endpoint_reports_backup_and_disk(tmp_path, monkeypatch):
    write_status(tmp_path, finished_at=datetime.now(UTC).isoformat())
    monkeypatch.setenv("GT_BACKUP_DIR", str(tmp_path))
    app, kc = make_app(data_source=None)
    c = client(app)
    kc.login(c, "admin", admin=True)
    h = c.get("/api/system/health").json()
    assert h["backup"]["state"] == "OK"
    assert {d["name"] for d in h["disks"]} == {"docker", "backups"}


def test_disk_full_ingest_returns_clear_error_and_keeps_existing_data(tmp_path, monkeypatch):
    """0-C05: DB không ghi được → 503 rõ ràng; lô hỏng không ghi dở; dữ liệu cũ còn nguyên."""
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'gt.db'}")
    repo.create_all()
    store = SqlCandleStore(repo.engine)
    app, kc = make_app(repo, candle_store=store, data_source=DataSource.MT5,
                       run_analysts=False, ingest_token=TOKEN)
    c = client(app)
    auth = {"Authorization": f"Bearer {TOKEN}"}
    first = bars(300)
    assert c.post("/api/ingest/mt5/candles", json=batch(first[:100]),
                  headers=auth).json()["accepted"] == 100

    real_begin = repo.engine.begin

    def full_disk():
        raise OperationalError("INSERT", {}, Exception("could not extend file: No space left"))

    monkeypatch.setattr(store.engine, "begin", full_disk)
    r = c.post("/api/ingest/mt5/candles", json=batch(first[100:]), headers=auth)
    assert r.status_code == 503 and "ổ đĩa" in r.json()["detail"]
    monkeypatch.setattr(store.engine, "begin", real_begin)
    assert store.stats("XAUUSD", Timeframe.M15, DataSource.MT5).count == 100
    # Ổ được giải phóng → Gateway gửi lại, nhận bình thường
    r = c.post("/api/ingest/mt5/candles", json=batch(first[100:]), headers=auth)
    assert r.status_code == 200 and r.json()["accepted"] == 200


@pytest.mark.parametrize("script", ["backup.sh", "restore.sh", "common.sh"])
def test_backup_scripts_never_echo_passwords(script):
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2] / "ops/backup" / script).read_text()
    for line in src.splitlines():
        if "echo" in line or "log " in line or "printf" in line:
            assert "PASSWORD" not in line, line
