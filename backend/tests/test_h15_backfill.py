"""Nạp bù lịch sử H.15 (GĐ3 bước 4 — cho Macro). File thật: gói CMT của Fed DDP (cắt 90 dòng cuối)
+ đường cong lợi suất thực 2026 của Bộ Tài chính, tải 2026-11-14."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from gold_trading.analysts import macro as MA
from gold_trading.analysts.framework import Scope
from gold_trading.contracts.candle import DataSource
from gold_trading.ingestion.point_in_time import PointInTimeStore
from gold_trading.ingestion.source_status import SourceCheckLog
from gold_trading.ingestion.sources import fed_h15 as H
from gold_trading.ingestion.sources import h15_backfill as HB
from gold_trading.market.timeframes import Timeframe
from gold_trading.storage.external_records import SqlExternalRecordStore
from gold_trading.storage.repository import SqlRepository

FIX = Path(__file__).parent / "fixtures" / "fed"
DDP = (FIX / "ddp-h15-cmt-2026-11-14.csv").read_text(encoding="utf-8")
TRE = (FIX / "treasury-real-2026.csv").read_text(encoding="utf-8")
PAGE = (FIX / "h15-2026-11-12.html").read_text(encoding="utf-8")
NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)


@pytest.fixture(params=["memory", "sqlite"])
def st(request, tmp_path):
    if request.param == "memory":
        return PointInTimeStore()
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'h.db'}")
    repo.create_all()
    return SqlExternalRecordStore(repo.engine)


def all_obs():
    return HB.parse_ddp(DDP) + HB.parse_treasury_real(TRE)


def test_parse_real_files_match_h15_page_exactly():
    """Cùng ngày → cùng chuỗi số với trang phát hành H.15 (05–10/11/2026), cả 3 chuỗi."""
    page = {(o.series, o.day): o.value for o in H.parse_release(PAGE).observations
            if o.value is not None}
    bf = {(o.series, o.day): o.value for o in all_obs()}
    common = [k for k in page if k in bf and k[0] in ("UST_TIPS_10Y", "UST_CMT_10Y",
                                                      "UST_CMT_2Y")]
    assert len(common) == 12                       # 3 chuỗi × 4 ngày có số
    assert all(page[k] == bf[k] for k in common)
    assert ("UST_CMT_2Y", date(2026, 11, 11)) not in bf      # "ND" (Veterans Day) bị bỏ, không 0


def test_parse_counts_and_hand_values():
    t = HB.parse_treasury_real(TRE)
    assert (t[0].day, t[0].value) == (date(2026, 11, 13), "2.91")
    assert all(o.series == "UST_TIPS_10Y" for o in t) and len(t) > 200
    d = {(o.series, o.day): o.value for o in HB.parse_ddp(DDP)}
    assert d[("UST_CMT_2Y", date(2026, 11, 12))] == "4.86"
    assert d[("UST_CMT_10Y", date(2026, 11, 12))] == "5.10"


@pytest.mark.parametrize("bad", [
    DDP.replace("RIFLGFCY10_N.B", "RIFLGFCY11_N.B"),          # mất chuỗi
    DDP.replace("Percent:_Per_Year", "Basis_Points"),          # đổi đơn vị
    DDP.replace("2026-11-12,", "2026-13-12,"),                 # ngày hỏng
    DDP.replace(",4.86,", ",48.60,"),                          # số ngoài khoảng
])
def test_ddp_bad_file_rejected_whole(bad):
    with pytest.raises(HB.BackfillFormatError):
        HB.parse_ddp(bad)


@pytest.mark.parametrize("bad", [TRE.replace('"10 YR"', '"10 YEAR"'),
                                 TRE.replace("11/13/2026,", "2026-11-13,"),
                                 TRE.replace(",2.91,", ",2,91,")])
def test_treasury_bad_file_rejected_whole(bad):
    with pytest.raises(HB.BackfillFormatError):
        HB.parse_treasury_real(bad)


def test_backfill_adds_only_missing_never_rewrites(st):
    H.run_once(store=st, log=SourceCheckLog(), get=lambda: PAGE,
               now=datetime(2026, 11, 13, 12, tzinfo=UTC))
    before = {r.logical_key: r for r in st.as_of(NOW, source=H.SOURCE)}
    c = HB.backfill(st, all_obs(), NOW, since=date(2026, 6, 1))
    assert c.conflict == [] and c.same == 12 and c.added > 250 and c.rejected == []
    after = {r.logical_key: r for r in st.as_of(NOW, source=H.SOURCE)}
    for k, r in before.items():
        assert after[k] == r                                    # số trang H.15 không đổi
    new = after["UST_TIPS_10Y:2026-09-01"]
    assert new.payload["backfill_source"] == "TREASURY" and new.revision == 0
    assert "BACKFILL" in new.quality_flags
    again = HB.backfill(st, all_obs(), NOW, since=date(2026, 6, 1))
    assert again.added == 0                                     # chạy lại: không thêm


def test_backfill_conflict_kept_and_reported(st):
    H.run_once(store=st, log=SourceCheckLog(), get=lambda: PAGE,
               now=datetime(2026, 11, 13, 12, tzinfo=UTC))
    obs = [HB.Obs("UST_TIPS_10Y", date(2026, 11, 10), "9.99", "TREASURY")]
    c = HB.backfill(st, obs, NOW, since=date(2026, 6, 1))
    assert c.conflict == [("UST_TIPS_10Y", "2026-11-10", "2.78", "9.99")] and c.added == 0
    assert st.as_of(NOW, source=H.SOURCE, logical_key="UST_TIPS_10Y:2026-11-10")[0] \
        .payload["value"] == "2.78"


def test_backfill_point_in_time_and_since(st):
    c = HB.backfill(st, all_obs(), NOW, since=date(2026, 10, 1))
    assert c.skipped_old > 0
    assert st.as_of(NOW - timedelta(seconds=1), source=H.SOURCE) == []   # chưa nạp → chưa biết
    assert st.as_of(NOW, source=H.SOURCE, logical_key="UST_TIPS_10Y:2026-09-30") == []


def test_live_h15_after_backfill_still_works(st):
    """Trang H.15 tải sau khi nạp bù: ngày trùng số → không thêm revision."""
    HB.backfill(st, all_obs(), NOW, since=date(2026, 6, 1))
    chk = H.run_once(store=st, log=SourceCheckLog(), get=lambda: PAGE,
                     now=NOW + timedelta(hours=1))
    assert chk.outcome.value == "OK"
    hist = st.history(H.SOURCE, "UST_TIPS_10Y:2026-11-10", NOW + timedelta(hours=2))
    assert [r.revision for r in hist] == [0]


def test_macro_gets_z_after_backfill(st):
    HB.backfill(st, all_obs(), NOW, since=date(2026, 6, 1))
    o = MA.compute(repo=None, candle_store=None, record_store=st,
                   scope=Scope.of_feed("XAUUSD", Timeframe.M15, DataSource.MT5, "f"),
                   mt5_server=None, as_of=NOW + timedelta(minutes=1))
    r = o.features["rates"]["real_yield_10y"]
    assert r["history"] == 61 and r["z_5d"] is not None and r["direction"] is not None
    assert not any(f.startswith("Z_HISTORY_SHORT") for f in o.quality_flags)


def test_cli_dry_run_writes_nothing(tmp_path, capsys):
    from gold_trading.ingestion import cli

    url = f"sqlite:///{tmp_path / 'c.db'}"
    SqlRepository.from_url(url).create_all()

    class Resp:
        def __init__(self, text, host):
            self.text, self.status_code, self.content = text, 200, text.encode()
            self.url = type("U", (), {"host": host})()

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, **k):
            if "federalreserve" in url:
                return Resp(DDP, "www.federalreserve.gov")
            return Resp(TRE, "home.treasury.gov")

    rc = cli._h15_backfill(True, 200, env={"DATABASE_URL": url}, client_factory=Client,
                           now=NOW)
    out = capsys.readouterr().out
    assert rc == 0 and "CHẠY THỬ" in out and "UST_TIPS_10Y" in out
    st = SqlExternalRecordStore(SqlRepository.from_url(url).engine)
    assert st.as_of(NOW + timedelta(days=1), source=H.SOURCE) == []
    rc = cli._h15_backfill(False, 200, env={"DATABASE_URL": url}, client_factory=Client,
                           now=NOW)
    assert rc == 0 and st.as_of(NOW + timedelta(days=1), source=H.SOURCE)
