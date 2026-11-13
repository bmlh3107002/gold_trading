"""Bước 10f — ING-34: replay mọi nguồn — nạp lại cùng dữ liệu → cùng kết quả.

Mọi việc của bộ chạy tự động (lịch FOMC / BEA / DOL, số BEA / DOL, H.15, COT, 3 nguồn tin) chạy trên
dữ liệu thật đã lưu (``tests/fixtures``, máy chủ giả ``Net`` của test bộ chạy):

1. Chạy lại lần 2 (giờ khác) → không thêm, không xung đột, không cách ly; DB không đổi.
2. Store mới, cùng giờ → **y hệt** từng revision (cùng nội dung, cùng thời điểm).
3. Bộ nhớ = SQLite (cùng quy tắc ở hai bản store).
4. Thứ tự chạy đảo ngược → cùng số liệu + thời điểm; khác biệt duy nhất là cờ cảnh báo đã ghi lúc
   nạp (xem test). 5. Nguồn chết giữa chừng rồi sống lại → như chạy liền mạch.
Nến (CSV / MT5) có test idempotent riêng: ``test_candles.py``, ``test_ingest_api.py``.
"""

from datetime import timedelta

import httpx
import pytest

from gold_trading.ingestion import external_runner as R
from gold_trading.ingestion.point_in_time import PointInTimeStore, fingerprint
from gold_trading.ingestion.source_status import CheckOutcome, SourceCheckLog
from gold_trading.storage.external_records import SqlExternalRecordStore
from gold_trading.storage.repository import SqlRepository
from gold_trading.storage.source_checks import SqlSourceCheckLog
from tests.test_external_runner import BLS_KEY, KEY_VALUE, NOW, Net

FAR = NOW + timedelta(days=400)
ENV = {"GT_BEA_API_KEY": KEY_VALUE, "GT_BLS_API_KEY": BLS_KEY}
ALL = R.DEFAULT_SOURCES


def make_store(kind, tmp_path, name="r"):
    if kind == "memory":
        return PointInTimeStore(), SourceCheckLog()
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / (name + '.db')}")
    repo.create_all()
    return SqlExternalRecordStore(repo.engine), SqlSourceCheckLog(repo.engine)


def jobs_for(store, log, net=None):
    client = httpx.Client(transport=httpx.MockTransport((net or Net()).handler))
    jobs, reg = R.build_jobs(ALL, store=store, check_log=log, env=ENV, client=client)
    return jobs, reg


def snapshot(store, reg):
    """Mọi revision đã biết (tới rất xa trong tương lai) của mọi nguồn + số cách ly."""
    out = []
    for src in reg.names():
        for latest in store.as_of(FAR, source=src):
            for r in store.history(src, latest.logical_key, FAR):
                out.append((r.source, r.logical_key, r.revision, r.record_id, r.kind,
                            r.event_time, r.available_at, r.ingested_at, fingerprint(r)))
    return sorted(out), store.quarantine_counts(FAR)


def run_all(jobs, now, order=1):
    """Chạy trực tiếp mọi việc (bỏ qua lịch hẹn của bộ chạy) theo thứ tự xếp sẵn hoặc đảo."""
    return [j.run(now) for j in jobs[::order]]


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_replay_every_source(kind, tmp_path):
    store, log = make_store(kind, tmp_path)
    jobs, reg = jobs_for(store, log)
    assert {j.source for j in jobs} == {
        "fed_fomc", "bea_schedule", "dol_claims_schedule", "bea_nipa", "dol_claims", "fed_h15",
        "cftc_cot_gold", "fed_rss_monetary", "fed_rss_speeches", "treasury_press",
        "bls_schedule", "bls_values"}
    first = run_all(jobs, NOW)
    assert all(c.outcome is CheckOutcome.OK for c in first), [(c.source, c.error_code)
                                                              for c in first]
    assert all(c.inserted > 0 for c in first), [(c.source, c.inserted) for c in first]
    snap = snapshot(store, reg)
    # 1. chạy lại (2 giờ sau, rồi 3 ngày sau): không thêm gì, không xung đột / hỏng
    for later in (NOW + timedelta(hours=2), NOW + timedelta(days=3)):
        again = run_all(jobs, later)
        assert [(c.source, c.inserted, c.conflict, c.invalid) for c in again] == \
            [(c.source, 0, 0, 0) for c in again]
        assert snapshot(store, reg) == snap


def test_replay_fresh_store_identical_and_memory_equals_sqlite(tmp_path):
    snaps = []
    for i, kind in enumerate(("memory", "sqlite")):
        store, log = make_store(kind, tmp_path, f"s{i}")
        jobs, reg = jobs_for(store, log)
        run_all(jobs, NOW)
        snaps.append(snapshot(store, reg))
    assert snaps[0] == snaps[1]
    assert len(snaps[0][0]) > 100   # đủ lớn để có ý nghĩa


def _latest(store, reg):
    return {(r.source, r.logical_key): r for s in reg.names() for r in store.as_of(FAR, source=s)}


def test_reversed_order_only_documented_difference(tmp_path):
    """Đảo thứ tự (số chạy trước lịch) rồi chạy lại đúng thứ tự: cùng tập dữ kiện, cùng số, cùng
    thời điểm sự kiện. Khác biệt được chấp nhận (ghi điều hệ thống biết lúc nạp, không viết lại):
    số DOL mang cờ ``RELEASE_OFF_SCHEDULE``; số BLS không gắn lần công bố (``available_at``
    trống → coi là biết từ lúc nạp, không sớm hơn). Chạy thật không xảy ra: lịch DOL theo quy tắc,
    lịch BLS là bảng chép tay — đều không gọi mạng, luôn chạy trước số."""
    store, log = make_store("sqlite", tmp_path, "rev")
    jobs, reg = jobs_for(store, log)
    run_all(jobs, NOW, order=-1)
    run_all(jobs, NOW)
    ref_store, ref_log = make_store("memory", tmp_path)
    ref_jobs, _ = jobs_for(ref_store, ref_log)
    run_all(ref_jobs, NOW)
    a, b = _latest(store, reg), _latest(ref_store, reg)
    assert a.keys() == b.keys()
    diff = []
    link = ("release_ref", "latency_seconds", "flags")
    for k in a:
        x, y = a[k], b[k]
        skip = ("flags",) if k[0] != "bls_values" else link
        px = {f: v for f, v in x.payload.items() if f not in skip}
        py = {f: v for f, v in y.payload.items() if f not in skip}
        assert (px, x.event_time, x.revision) == (py, y.event_time, y.revision), k
        if k[0] == "bls_values":
            # Số BLS nạp khi lịch chưa có: không gắn lần công bố → available_at trống → được
            # "biết" từ lúc nạp (không sớm hơn bản chuẩn) — hướng an toàn.
            assert x.available_at is None or x.available_at == y.available_at, k
            assert x.known_at >= y.known_at, k
            continue
        assert x.available_at == y.available_at, k
        if x.quality_flags != y.quality_flags:
            fx, fy = x.quality_flags, y.quality_flags
            diff.append((k[0], fx - fy, fy - fx))
    assert diff and all(d == ("dol_claims", {"RELEASE_OFF_SCHEDULE"}, set()) for d in diff)


def test_replay_with_source_outage_then_recovery(tmp_path):
    """Một nguồn chết giữa chừng rồi sống lại → kết quả cuối giống chạy liền mạch."""
    net = Net()
    store, log = make_store("sqlite", tmp_path, "o")
    jobs, reg = jobs_for(store, log, net)
    net.down.add("www.federalreserve.gov")
    run_all(jobs, NOW)
    net.down.clear()
    run_all(jobs, NOW)
    ref_store, ref_log = make_store("memory", tmp_path)
    ref_jobs, ref_reg = jobs_for(ref_store, ref_log)
    run_all(ref_jobs, NOW)
    a, b = snapshot(store, reg), snapshot(ref_store, ref_reg)
    assert [x[:7] + x[8:] for x in a[0]] == [x[:7] + x[8:] for x in b[0]] and a[1] == b[1]
