"""MT-15: nhiều terminal MT5 trên một máy — đúng terminal đã cấu hình, mỗi terminal một token,
mỗi terminal một tiến trình, lỗi một terminal không ảnh hưởng terminal khác."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from mt5_gateway import checks, cli, config, multi
from mt5_gateway.reader import Mt5Error, Mt5Reader, TerminalMismatch, norm_terminal_dir
from mt5_gateway.sync import Syncer
from tests.fake_mt5 import FakeMt5
from tests.test_gateway import ATHENS, NOW_WINTER, FakeBackend, cfg

EXE_A = r"C:\MT5\LordTrade\terminal64.exe"
EXE_B = r"C:\MT5\Exness\terminal64.exe"
TOK_A = "a" * 32
TOK_B = "b" * 32


# ---------- so đường dẫn terminal ----------


@pytest.mark.parametrize(
    "configured, reported",
    [
        (EXE_A, r"C:\MT5\LordTrade"),
        (EXE_A, r"c:\mt5\lordtrade"),  # Windows không phân biệt hoa/thường
        (EXE_A, "C:/MT5/LordTrade/"),  # gạch chéo xuôi + gạch cuối
        ('"C:\\MT5\\LordTrade\\terminal64.exe"', r"C:\MT5\LordTrade"),  # chép kèm dấu nháy
        (r"C:\MT5\LordTrade\TERMINAL64.EXE", r"C:\MT5\LordTrade"),
        (r"C:\MT5\LordTrade", r"C:\MT5\LordTrade"),  # người dùng ghi thư mục
    ],
)
def test_same_terminal_dir(configured, reported):
    assert norm_terminal_dir(configured) == norm_terminal_dir(reported)


@pytest.mark.parametrize(
    "configured, reported",
    [
        (EXE_A, r"C:\MT5\Exness"),
        (EXE_A, r"C:\MT5\LordTrade2"),  # tiền tố giống nhau không được coi là một
        (EXE_A, r"C:\MT5"),  # thư mục cha
        (EXE_A, r"C:\MT5\LordTrade\sub"),
        (EXE_A, r"D:\MT5\LordTrade"),
    ],
)
def test_different_terminal_dir(configured, reported):
    assert norm_terminal_dir(configured) != norm_terminal_dir(reported)


def reader(fake, path=EXE_A):
    return Mt5Reader(fake, broker_symbol="XAUUSD", server_tz=ATHENS, terminal_path=path)


def test_connect_passes_path_and_accepts_right_terminal():
    fake = FakeMt5(now_utc=NOW_WINTER)
    fake.terminal_dir = r"C:\MT5\LordTrade"
    r = reader(fake)
    r.connect()
    assert fake.init_paths == [EXE_A]
    assert fake.shutdowns == 0


def test_connect_wrong_terminal_raises_and_releases():
    fake = FakeMt5(now_utc=NOW_WINTER)
    fake.terminal_dir = r"C:\MT5\Exness"  # initialize nối nhầm MT5 khác
    with pytest.raises(TerminalMismatch, match="TERMINAL_MISMATCH"):
        reader(fake).connect()
    assert fake.shutdowns == 1  # buông terminal nhầm


@pytest.mark.parametrize("bad", [None, "", "   "])
def test_unreadable_terminal_path_is_mismatch(bad):
    fake = FakeMt5(now_utc=NOW_WINTER)
    fake.terminal_dir = bad
    with pytest.raises(TerminalMismatch):
        reader(fake).connect()


def test_terminal_info_none_is_mismatch():
    fake = FakeMt5(now_utc=NOW_WINTER)
    fake.terminal_info = lambda: None
    with pytest.raises(TerminalMismatch):
        reader(fake).ensure_terminal()


def test_no_path_configured_keeps_old_behaviour():
    fake = FakeMt5(now_utc=NOW_WINTER)
    fake.terminal_dir = r"C:\Anything"
    r = reader(fake, path=None)
    r.connect()
    assert fake.init_paths == [None]


# ---------- check ----------


def test_check_fails_on_wrong_terminal():
    fake = FakeMt5(now_utc=NOW_WINTER)
    fake.terminal_dir = r"C:\MT5\Exness"
    rep = checks.run_checks(cfg(terminal_path=EXE_A), fake, FakeBackend(), now=lambda: NOW_WINTER,
                            tick_wait_s=1)
    assert not rep.ok
    step = [s for s in rep.steps if s.name == "Kết nối MT5"][0]
    assert step.status == checks.FAIL and "TERMINAL_MISMATCH" in step.detail
    assert "GT_MT5_PATH" in step.fix


def test_check_shows_terminal_path_when_configured():
    fake = FakeMt5(now_utc=NOW_WINTER)
    fake.terminal_dir = r"C:\MT5\LordTrade"
    rep = checks.run_checks(cfg(terminal_path=EXE_A), fake, FakeBackend(), now=lambda: NOW_WINTER,
                            tick_wait_s=1)
    assert rep.ok
    step = [s for s in rep.steps if s.name == "Kết nối MT5"][0]
    assert r"C:\MT5\LordTrade" in step.detail


# ---------- run: terminal bị đổi khi đang chạy ----------


def running(path=EXE_A):
    fake = FakeMt5(now_utc=NOW_WINTER)
    fake.terminal_dir = r"C:\MT5\LordTrade"
    be = FakeBackend()
    conf = cfg(terminal_path=path, timeframes=("M15", "H1"))
    rep = checks.run_checks(conf, fake, be, now=lambda: NOW_WINTER, tick_wait_s=1)
    assert rep.ok
    be.posts.clear()
    t = [0.0]

    def sleep(s):
        t[0] += s

    return fake, be, Syncer(conf, rep.reader, be, rep, sleep=sleep, clock=lambda: t[0])


def test_run_sends_nothing_while_on_wrong_terminal_then_recovers():
    fake, be, s = running()
    fake.terminal_dir = r"C:\MT5\Exness"  # IPC bị nối sang MT5 khác
    n = iter([False, False, False, True])
    s.run_forever(stop=lambda: next(n))
    assert be.posts == []  # không gửi nến của MT5 người khác
    assert s.backfilled is False
    assert "H1" in s.higher  # không tắt khung lớn vì lỗi nối nhầm
    fake.terminal_dir = r"C:\MT5\LordTrade"
    n = iter([False, True])
    s.run_forever(stop=lambda: next(n))
    assert s.backfilled and be.posts
    assert {p["timeframe"] for p in be.posts} == {"M15", "H1"}
    assert fake.order_send_called is False


def test_mismatch_during_higher_timeframe_push_stops_round():
    fake, be, s = running()
    s.backfill()
    be.posts.clear()
    real = fake.copy_rates_from_pos

    def switch_after_m15(name, tf, start, count):
        out = real(name, tf, start, count)
        fake.terminal_dir = r"C:\MT5\Exness"
        return out

    fake.copy_rates_from_pos = switch_after_m15
    with pytest.raises(TerminalMismatch):
        s.push_recent()
    assert all(p["timeframe"] == "M15" for p in be.posts)  # H1 không gửi khi đã sai terminal
    assert "H1" in s.higher


# ---------- cấu hình nhiều terminal ----------


def write(folder: Path, name: str, **kv: str) -> Path:
    base = {"GT_INGEST_TOKEN": TOK_A, "GT_MT5_PATH": EXE_A, "GT_SERVER_TZ": "Europe/Athens"}
    base.update(kv)
    p = folder / f"{name}.env"
    p.write_text("\n".join(f"{k}={v}" for k, v in base.items() if v is not None), "utf-8")
    return p


def load(folder: Path):
    return multi.load_terminals(folder, exists=lambda _p: True)


def test_two_terminals_ok(tmp_path):
    write(tmp_path, "lordtrade")
    write(tmp_path, "exness", GT_INGEST_TOKEN=TOK_B, GT_MT5_PATH=EXE_B)
    terms, errors = load(tmp_path)
    assert errors == []
    assert [t.name for t in terms] == ["exness", "lordtrade"]
    ids = {t.cfg.gateway_id for t in terms}
    assert len(ids) == 2 and all(i.endswith(("-exness", "-lordtrade")) for i in ids)


def test_missing_folder_or_empty(tmp_path):
    for folder in (tmp_path / "khong-co", tmp_path):
        terms, errors = load(folder)
        assert terms == [] and errors and "*.env" in errors[0]


def test_example_and_other_files_ignored(tmp_path):
    write(tmp_path, "lordtrade")
    (tmp_path / "exness.env.example").write_text("GT_INGEST_TOKEN=" + TOK_A, "utf-8")
    (tmp_path / "ghi-chu.txt").write_text("x", "utf-8")
    (tmp_path / "sub.env").mkdir()  # thư mục tên .env không phải file
    terms, errors = load(tmp_path)
    assert errors == [] and [t.name for t in terms] == ["lordtrade"]


def test_shared_token_blocks_everything_and_never_prints_token(tmp_path):
    write(tmp_path, "lordtrade")
    write(tmp_path, "exness", GT_MT5_PATH=EXE_B)  # quên đổi token
    terms, errors = load(tmp_path)
    assert terms == []
    assert any("CHUNG một token" in e and "exness.env" in e and "lordtrade.env" in e
               for e in errors)
    assert all(TOK_A not in e for e in errors)


@pytest.mark.parametrize("other", [EXE_A, EXE_A.lower(), "C:/MT5/LordTrade/terminal64.exe",
                                   r"C:\MT5\LordTrade"])
def test_same_terminal_twice_blocks_everything(tmp_path, other):
    write(tmp_path, "lordtrade")
    write(tmp_path, "exness", GT_INGEST_TOKEN=TOK_B, GT_MT5_PATH=other)
    terms, errors = load(tmp_path)
    assert terms == [] and any("CÙNG một terminal" in e for e in errors)


def test_missing_path_blocks_everything(tmp_path):
    write(tmp_path, "lordtrade")
    write(tmp_path, "exness", GT_INGEST_TOKEN=TOK_B, GT_MT5_PATH=None)
    terms, errors = load(tmp_path)
    assert terms == [] and any("exness.env: thiếu GT_MT5_PATH" in e for e in errors)


def test_path_not_found(tmp_path):
    write(tmp_path, "lordtrade")
    terms, errors = multi.load_terminals(tmp_path, exists=lambda _p: False)
    assert terms == [] and "không thấy file" in errors[0]


def test_short_or_missing_token(tmp_path):
    write(tmp_path, "lordtrade", GT_INGEST_TOKEN="ngan")
    write(tmp_path, "exness", GT_INGEST_TOKEN=None, GT_MT5_PATH=EXE_B)
    terms, errors = load(tmp_path)
    assert terms == [] and len([e for e in errors if "GT_INGEST_TOKEN" in e]) == 2


def test_duplicate_gateway_id(tmp_path):
    write(tmp_path, "lordtrade", GT_GATEWAY_ID="may-1")
    write(tmp_path, "exness", GT_INGEST_TOKEN=TOK_B, GT_MT5_PATH=EXE_B, GT_GATEWAY_ID="MAY-1")
    terms, errors = load(tmp_path)
    assert terms == [] and any("GT_GATEWAY_ID" in e for e in errors)


@pytest.mark.parametrize("bad", ["tài-khoản", "a b", "x" * 33])
def test_bad_file_name(tmp_path, bad):
    write(tmp_path, bad)
    terms, errors = load(tmp_path)
    assert terms == [] and errors


def test_bad_timeframes_reported_not_crash(tmp_path):
    write(tmp_path, "lordtrade", GT_TIMEFRAMES="M15,M1")
    terms, errors = load(tmp_path)
    assert terms == [] and "GT_TIMEFRAMES" in errors[0]


def test_environment_variables_cannot_override_terminal_files(tmp_path, monkeypatch):
    """Biến GT_INGEST_TOKEN đặt chung trong Windows sẽ biến mọi terminal thành chung token."""
    write(tmp_path, "lordtrade")
    write(tmp_path, "exness", GT_INGEST_TOKEN=TOK_B, GT_MT5_PATH=EXE_B)
    monkeypatch.setenv("GT_INGEST_TOKEN", "z" * 40)
    monkeypatch.setenv("GT_MT5_PATH", EXE_A)
    terms, errors = load(tmp_path)
    assert errors == []
    assert {t.cfg.token for t in terms} == {TOK_A, TOK_B}
    env = multi.child_env()
    assert not [k for k in env if k.upper().startswith("GT_")]
    assert multi.gt_vars_in_environ() == ["GT_INGEST_TOKEN", "GT_MT5_PATH"]


def test_single_terminal_mode_still_reads_environment(tmp_path, monkeypatch):
    p = write(tmp_path, "gateway")
    monkeypatch.setenv("GT_INGEST_TOKEN", "z" * 40)
    assert config.load(p).token == "z" * 40
    assert config.load(p, use_environ=False).token == TOK_A


def test_child_command():
    t = multi.Terminal("lordtrade", Path("terminals/lordtrade.env"), cfg())
    cmd = multi.child_command(t)
    assert cmd[1:] == ["-m", "mt5_gateway.cli", "run", "--env-file",
                       str(Path("terminals/lordtrade.env")), "--name", "lordtrade"]
    assert multi.child_command(t, "check")[3] == "check"


# ---------- trông coi tiến trình ----------


class FakeProc:
    def __init__(self, name):
        self.name = name
        self.code: int | None = None
        self.terminated = False
        self.killed = False
        self.hang = False

    def poll(self):
        return self.code

    def terminate(self):
        self.terminated = True
        if not self.hang:
            self.code = 0

    def kill(self):
        self.killed = True
        self.code = -9

    def wait(self, timeout=None):
        if self.code is None:
            raise TimeoutError
        return self.code


def sup_world(names=("a", "b")):
    t = [0.0]
    spawned: list[FakeProc] = []

    def spawn(term):
        p = FakeProc(term.name)
        spawned.append(p)
        return p

    terms = [multi.Terminal(n, Path(f"{n}.env"), cfg(gateway_id=n)) for n in names]
    sup = multi.Supervisor(terms, spawn=spawn, clock=lambda: t[0], sleep=lambda s: None)
    return sup, spawned, t


def test_starts_each_terminal_staggered():
    sup, spawned, t = sup_world()
    sup.step()
    assert [p.name for p in spawned] == ["a"]
    t[0] = multi.START_GAP_S
    sup.step()
    assert [p.name for p in spawned] == ["a", "b"]
    sup.step()
    assert len(spawned) == 2  # không khởi động thêm khi đang chạy


def test_crash_of_one_terminal_restarts_only_it_with_backoff():
    sup, spawned, t = sup_world()
    t[0] = 10
    sup.step()
    a, b = spawned
    a.code = 1  # check chưa đạt / MT5 lỗi
    t[0] = 20
    sup.step()
    assert len(spawned) == 2 and b.poll() is None  # b vẫn chạy, a chờ
    t[0] = 20 + multi.RESTART_MIN_S - 1
    sup.step()
    assert len(spawned) == 2
    t[0] = 20 + multi.RESTART_MIN_S
    sup.step()
    assert [p.name for p in spawned] == ["a", "b", "a"]
    # chết ngay lần nữa → chờ gấp đôi
    spawned[-1].code = 1
    t[0] += 1
    sup.step()
    t[0] += 2 * multi.RESTART_MIN_S - 1
    sup.step()
    assert len(spawned) == 3
    t[0] += 1
    sup.step()
    assert len(spawned) == 4


def test_backoff_capped_and_reset_after_healthy_run():
    sup, spawned, t = sup_world(("a",))
    for _ in range(10):
        sup.step()
        spawned[-1].code = 1
        t[0] += 1
        sup.step()
        t[0] += multi.RESTART_MAX_S
    assert sup.slots[0].backoff == multi.RESTART_MAX_S
    sup.step()
    t[0] += multi.HEALTHY_RUN_S + 1
    spawned[-1].code = 1
    sup.step()
    assert sup.slots[0].next_start - t[0] == multi.RESTART_MIN_S


def test_spawn_failure_retried_later():
    t = [0.0]
    calls = []

    def spawn(term):
        calls.append(term.name)
        raise OSError("không chạy được python")

    terms = [multi.Terminal("a", Path("a.env"), cfg())]
    sup = multi.Supervisor(terms, spawn=spawn, clock=lambda: t[0], sleep=lambda s: None)
    sup.step()
    sup.step()
    assert calls == ["a"]
    t[0] = multi.RESTART_MIN_S
    sup.step()
    assert calls == ["a", "a"]


def test_stop_all_terminates_and_kills_hung():
    sup, spawned, t = sup_world()
    t[0] = multi.START_GAP_S
    sup.step()
    spawned[1].hang = True
    sup.stop_all()
    assert all(p.terminated for p in spawned)
    assert spawned[1].killed and not spawned[0].killed


def test_run_forever_stops_children_on_ctrl_c():
    sup, spawned, t = sup_world(("a",))

    def sleep(_s):
        raise KeyboardInterrupt

    sup.sleep = sleep
    with pytest.raises(KeyboardInterrupt):
        sup.run_forever()
    assert spawned and spawned[0].terminated


def test_check_all_runs_each_in_own_process():
    terms = [multi.Terminal(n, Path(f"{n}.env"), cfg()) for n in ("a", "b")]
    seen = []

    def run(cmd):
        seen.append(cmd)
        return 0 if cmd[-1] == "a" else 1

    assert multi.check_all(terms, run=run) == {"a": 0, "b": 1}
    assert [c[3] for c in seen] == ["check", "check"]


# ---------- CLI ----------


def test_cli_refuses_bad_config_without_starting(tmp_path, capsys, monkeypatch):
    write(tmp_path, "lordtrade")
    write(tmp_path, "exness", GT_MT5_PATH=EXE_B)  # chung token
    started = []
    monkeypatch.setattr(multi, "Supervisor", lambda *a, **k: started.append(1))
    monkeypatch.setattr(multi.os.path, "exists", lambda _p: True)
    assert cli.main(["run-all", "--dir", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "chưa chạy terminal nào" in out and started == []
    assert TOK_A not in out


def test_cli_check_all_summary(tmp_path, capsys, monkeypatch):
    write(tmp_path, "lordtrade")
    write(tmp_path, "exness", GT_INGEST_TOKEN=TOK_B, GT_MT5_PATH=EXE_B)
    monkeypatch.setattr(multi.os.path, "exists", lambda _p: True)
    monkeypatch.setattr(multi, "check_all", lambda terms: {"exness": 0, "lordtrade": 1})
    assert cli.main(["check-all", "--dir", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert re.search(r"exness: SẴN SÀNG", out) and "lordtrade: CHƯA SẴN SÀNG" in out
    assert TOK_A not in out and TOK_B not in out


def test_reader_mt5error_subclass():
    assert issubclass(TerminalMismatch, Mt5Error)


def test_terminal_token_files_are_git_ignored():
    """File token của từng terminal không bao giờ được commit (soát lại tìm được: mẫu
    ``terminals/*.env`` ở .gitignore gốc chỉ khớp thư mục gốc, không khớp mt5_gateway/terminals)."""
    import shutil
    import subprocess

    if shutil.which("git") is None:
        pytest.skip("không có git")
    root = Path(__file__).resolve().parents[2]
    if not (root / ".git").exists():
        pytest.skip("không phải bản git")

    def ignored(rel: str) -> bool:
        return subprocess.run(["git", "check-ignore", "-q", rel], cwd=root).returncode == 0

    assert ignored("mt5_gateway/terminals/lordtrade.env")
    assert ignored("mt5_gateway/gateway.env")
    assert not ignored("mt5_gateway/terminals/vi-du.env.example")
