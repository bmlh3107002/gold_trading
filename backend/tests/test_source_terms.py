"""ING-32: nguồn chỉ bật được khi điều khoản nhà cung cấp đã đọc nguyên văn (VERIFIED)."""

import re
from datetime import date, timedelta
from pathlib import Path

import pytest

from gold_trading.ingestion.source_status import SourceRegistry, SourceSpec
from gold_trading.ingestion.source_terms import (
    SOURCE_TERMS,
    SourceTerms,
    TermsStatus,
    terms_problem,
)

DOC = Path(__file__).resolve().parents[2] / "docs/thiet-ke/11-dieu-khoan-nguon.md"
H = timedelta(hours=1)


def terms(status, provider="fred"):
    return {provider: SourceTerms(provider, status, date(2026, 11, 13), "#x")}


@pytest.mark.parametrize("status", [TermsStatus.NEEDS_REVIEW, TermsStatus.BLOCKED])
def test_enabled_source_needs_verified_terms(status):
    spec = SourceSpec("fred_dgs10", "macro", fetch_ttl=H, provider="fred")
    with pytest.raises(ValueError, match="ING-32"):
        SourceRegistry([spec], terms=terms(status))


def test_unknown_provider_blocked():
    with pytest.raises(ValueError, match="chưa ghi điều khoản"):
        SourceRegistry([SourceSpec("rss_x", "news", fetch_ttl=H)], terms={})


def test_verified_terms_allow_enable_and_provider_defaults_to_name():
    spec = SourceSpec("fred", "macro", fetch_ttl=H)
    assert spec.provider == "fred"
    reg = SourceRegistry([spec], terms=terms(TermsStatus.VERIFIED))
    assert reg.names() == ["fred"]


def test_disabled_source_may_be_declared_before_review():
    spec = SourceSpec("iau_holdings", "positioning", fetch_ttl=H, provider="iau",
                      enabled=False)
    assert SourceRegistry([spec]).get("iau_holdings") is spec  # điều khoản thật: BLOCKED


def test_real_terms_state():
    """Chỉ nhà cung cấp đã đọc nguyên văn điều khoản mới VERIFIED (lần 2, 2026-11-13);
    hai quỹ ETF bị chặn vì điều khoản website."""
    verified = {p for p, t in SOURCE_TERMS.items() if t.status is TermsStatus.VERIFIED}
    assert verified == {"bea", "census", "fed"}
    assert {p for p, t in SOURCE_TERMS.items() if t.status is TermsStatus.BLOCKED} == \
        {"gld", "iau"}
    for p in ("fred", "bls", "cftc", "dol", "treasury", "gld", "iau"):
        assert terms_problem(p, SOURCE_TERMS) is not None
    SourceRegistry([SourceSpec("bea_gdp", "macro", fetch_ttl=H, provider="bea")])


def test_every_provider_documented_with_same_status():
    """Code và tài liệu không lệch: mỗi nhà cung cấp có mục riêng, ghi đúng trạng thái."""
    text = DOC.read_text(encoding="utf-8")
    for p, t in SOURCE_TERMS.items():
        m = re.search(rf'<a id="{p}"></a>.*?\*\*Trạng thái:\*\* `(\w+)`', text, re.S)
        assert m, f"thiếu mục {p} trong {DOC.name}"
        assert m.group(1) == t.status.value, p
