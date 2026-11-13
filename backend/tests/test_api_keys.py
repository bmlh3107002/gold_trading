"""ING-31: khóa API chỉ trong .env, không commit, không log (nền cho 1E-C05)."""

from __future__ import annotations

import io
import json
import logging
import pickle
import re
import secrets
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from gold_trading.common.enums import SourceStatus
from gold_trading.ingestion.api_keys import (
    KEY_ENV,
    ApiKey,
    describe_keys,
    error_code_for_exception,
    error_code_for_http,
    load_api_key,
    load_api_keys,
)
from gold_trading.ingestion.source_status import (
    CheckOutcome,
    SourceCheck,
    SourceCheckLog,
    SourceSpec,
    evaluate,
)
from gold_trading.ops.logging import configure_logging, redact

REPO = Path(__file__).resolve().parents[2]
T0 = datetime(2026, 1, 5, 14, 0, tzinfo=UTC)


def fresh_key(n: int = 32) -> str:
    return secrets.token_hex(n // 2)


@pytest.fixture
def captured():
    buf = io.StringIO()
    root = logging.getLogger()
    old_handlers, old_level = list(root.handlers), root.level
    configure_logging("DEBUG", stream=buf)
    yield buf
    for h in list(root.handlers):
        root.removeHandler(h)
    for h in old_handlers:
        root.addHandler(h)
    root.setLevel(old_level)


# --- ApiKey không tự lộ ---

def test_api_key_never_prints_value():
    v = fresh_key()
    k = ApiKey("fred", v)
    # Cố ý thử mọi kiểu định dạng chuỗi.
    pct = "%s" % k  # noqa: UP031
    fmt = "{}".format(k)  # noqa: UP032
    for shown in (str(k), repr(k), f"{k}", f"{k!r}", pct, fmt, str([k]), str({"k": k})):
        assert v not in shown and "***" in shown
    assert k.reveal() == v and k.source == "fred"
    with pytest.raises(TypeError):
        json.dumps({"k": k})
    with pytest.raises(TypeError):
        pickle.dumps(k)
    assert k == ApiKey("fred", v) and k != ApiKey("bls", v)


# --- nạp khóa ---

@pytest.mark.parametrize("raw", [None, "", "   ", "\t\n"])
def test_missing_key(raw):
    env = {} if raw is None else {"GT_FRED_API_KEY": raw}
    lk = load_api_key("fred", env)
    assert (lk.ok, lk.key, lk.error_code) == (False, None, "KEY_MISSING")


@pytest.mark.parametrize("bad", [
    '"{k}"',          # dán kèm dấu nháy
    "'{k}'",
    "{k} {k}",        # khoảng trắng ở giữa
    "{k}#comment",
    "short123",       # quá ngắn
    "x" * 129,        # quá dài
    "{k}\x00",
    "khóa{k}",        # chữ có dấu
])
def test_invalid_key_format(bad, captured):
    k = fresh_key()
    raw = bad.format(k=k)
    lk = load_api_key("bls", {"GT_BLS_API_KEY": raw})
    assert (lk.ok, lk.error_code) == (False, "KEY_INVALID")
    # Khóa sai định dạng vẫn có thể chứa khóa thật → vẫn bị che trong log.
    logging.getLogger("t").error("gọi BLS với %s", raw)
    if len(raw.strip()) >= 8:
        assert k not in captured.getvalue()


def test_valid_key_trimmed():
    v = fresh_key(36)
    lk = load_api_key("bea", {"GT_BEA_API_KEY": f"  {v}\n"})
    assert lk.ok and lk.key.reveal() == v and lk.error_code is None


def test_unknown_source_rejected():
    with pytest.raises(ValueError):
        load_api_key("ghost", {})


def test_load_all_independent():
    v = fresh_key()
    out = load_api_keys({"GT_FRED_API_KEY": v, "GT_BLS_API_KEY": "bad key"})
    assert set(out) == set(KEY_ENV)
    assert describe_keys(out) == {"bea": "KEY_MISSING", "bls": "KEY_INVALID",
                                  "fred": "CONFIGURED"}
    assert v not in json.dumps(describe_keys(out))


# --- không log ---

def test_loaded_key_redacted_everywhere_in_logs(captured):
    fred, bls, bea = fresh_key(), fresh_key(), fresh_key(36)
    load_api_keys({"GT_FRED_API_KEY": fred, "GT_BLS_API_KEY": bls, "GT_BEA_API_KEY": bea})
    log = logging.getLogger("gold_trading.ingestion.test")
    log.info("GET https://api.stlouisfed.org/fred/series/observations?series_id=DGS10"
             "&api_key=%s&file_type=json", fred)
    log.info("POST bls body=%s", json.dumps({"seriesid": ["CUUR0000SA0"],
                                            "registrationkey": bls}))
    log.warning("BEA ?UserID=%s&method=GetData", bea)
    log.warning("khóa trần không có tên tham số: %s / %s", fred, bea)
    try:
        raise RuntimeError(f"HTTP 400 for url https://x/?api_key={fred}")
    except RuntimeError:
        log.exception("gọi nguồn hỏng")
    out = captured.getvalue()
    for v in (fred, bls, bea):
        assert v not in out
    lines = [json.loads(x) for x in out.splitlines() if x.strip()]
    assert len(lines) == 5 and "exc" in lines[-1]
    assert "series_id=DGS10" in lines[0]["msg"]  # phần không bí mật vẫn đọc được


@pytest.mark.parametrize("raw,secret", [
    ("?api_key=abcdef0123456789abcdef0123456789", "abcdef0123456789"),
    ('{"registrationkey": "0123456789abcdef0123456789abcdef"}', "0123456789abcdef"),
    ("&UserID=11111111-2222-3333-4444-555555555555&", "11111111-2222"),
    ("?get=NAME&key=zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz", "zzzzzzzz"),
    ("x-api-key='kkkkkkkkkkkkkkkkkkkk'", "kkkkkkkk"),
    ("apikey=QQQQQQQQQQQQQQQQQQ", "QQQQQQQQ"),
])
def test_redact_unregistered_api_key_params(raw, secret):
    """Khóa chưa đăng ký (ví dụ nguồn mới) vẫn bị che theo tên tham số."""
    assert secret not in redact(raw)


def test_redact_keeps_logical_key_param():
    assert redact("logical_key=CPI:2026-10") == "logical_key=CPI:2026-10"


# --- mã lỗi an toàn ---

@pytest.mark.parametrize("status,code", [
    (401, "AUTH_FAILED"), (403, "FORBIDDEN"), (404, "NOT_FOUND"), (429, "RATE_LIMITED"),
    (400, "HTTP_400"), (500, "HTTP_500"), (503, "HTTP_503"), (302, "HTTP_UNEXPECTED"),
    (0, "HTTP_UNEXPECTED"),
])
def test_error_code_for_http(status, code):
    assert error_code_for_http(status) == code
    SourceCheck("fred", T0, CheckOutcome.ERROR, code)  # mã hợp lệ cho nhật ký


class HTTPStatusError(Exception):
    pass


class ReadTimeout(Exception):
    pass


class _x9(Exception):
    pass


def test_error_code_for_exception_ignores_message():
    k = fresh_key()
    cases = {
        TimeoutError(k): "TIMEOUT",
        ReadTimeout(k): "TIMEOUT",
        ConnectionResetError(k): "NETWORK_ERROR",
        HTTPStatusError(f"?api_key={k}"): "HTTP_STATUS_ERROR",
        ValueError(k): "VALUE_ERROR",
        _x9(k): "X9",
    }
    for exc, code in cases.items():
        got = error_code_for_exception(exc)
        assert got == code and k not in got
        SourceCheck("fred", T0, CheckOutcome.ERROR, got)


# --- thiếu / sai khóa → nguồn MISSING ngay (1E-C05 phần trạng thái) ---

@pytest.mark.parametrize("raw,code", [("", "KEY_MISSING"), ("bad key", "KEY_INVALID")])
def test_key_problem_makes_source_missing(raw, code):
    lk = load_api_key("fred", {"GT_FRED_API_KEY": raw})
    log = SourceCheckLog()
    log.record(SourceCheck("fred", T0, CheckOutcome.OK))  # trước đó chạy tốt
    log.record(SourceCheck("fred", T0.replace(minute=5), CheckOutcome.ERROR, lk.error_code))
    spec = SourceSpec("fred", "macro", fetch_ttl=timedelta(hours=26))
    at = T0.replace(minute=5)
    r = evaluate("fred", spec, log.summary("fred", at), at, None)
    assert (r.status, r.reason) == (SourceStatus.MISSING, code)


# --- không commit ---

_KEY_ASSIGN = re.compile(r"GT_[A-Z]+_API_KEY[ \t]*[=:][ \t]*[\"']?([A-Za-z0-9_-]{8,})")


def _tracked_files() -> list[Path]:
    if shutil.which("git") is None or not (REPO / ".git").exists():
        pytest.skip("không có git checkout")
    out = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z"], capture_output=True,
                         check=True).stdout.decode()
    return [REPO / p for p in out.split("\0") if p]


def test_no_env_file_committed():
    names = {p.name for p in _tracked_files()}
    assert ".env" not in names and "gateway.env" not in names
    tracked_env = [p for p in _tracked_files()
                   if p.name.startswith(".env") and p.name != ".env.example"]
    assert tracked_env == []
    for rel in (".env", "deploy/.env", "backend/.env", "mt5_gateway/gateway.env"):
        r = subprocess.run(["git", "-C", str(REPO), "check-ignore", "-q", "--no-index", rel],
                           check=False)
        assert r.returncode == 0, rel  # .env ở mọi thư mục đều bị bỏ qua


def test_no_api_key_value_in_committed_files():
    """Quét file đã commit: không có dòng gán khóa API kèm giá trị (chỉ cho phép để trống
    hoặc ${GT_..._API_KEY:-})."""
    hits = []
    for p in _tracked_files():
        if p.suffix in {".png", ".jpg", ".ico", ".woff", ".woff2", ".lock"} or not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for m in _KEY_ASSIGN.finditer(text):
            if p.name != Path(__file__).name:
                hits.append(f"{p.relative_to(REPO)}: {m.group(0)[:30]}")
    assert hits == []


def test_compose_passes_keys_without_default_value():
    for rel in ("deploy/docker-compose.yml", "docker-compose.yml"):
        text = (REPO / rel).read_text(encoding="utf-8")
        for var in KEY_ENV.values():
            assert f"{var}: ${{{var}:-}}" in text, (rel, var)
