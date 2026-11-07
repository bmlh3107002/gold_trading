"""Lệnh ``check``: chẩn đoán từng bước, KHÔNG ghi dữ liệu.

``run`` chỉ chạy khi không có bước LỖI.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from mt5_gateway.backend_client import BackendClient, BackendError
from mt5_gateway.config import MIN_TOKEN_LEN, Config, history_bars_for
from mt5_gateway.reader import Mt5Error, Mt5Reader
from mt5_gateway.timeconv import load_tz, tz_offset_hours

PASS, WARN, FAIL = "ĐẠT", "CẢNH BÁO", "LỖI"
DRY_RUN_BARS = 2000
# Múi giờ server phổ biến của broker MT5. Ưu tiên loại có giờ mùa hè (đúng quanh năm).
TZ_CANDIDATES = (
    "Europe/Athens",  # GMT+2 / GMT+3: đa số broker (đóng nến ngày theo giờ New York)
    "Europe/London",  # GMT+0 / GMT+1
    "Europe/Berlin",  # GMT+1 / GMT+2
    "America/New_York",  # GMT-5 / GMT-4
    "UTC",
    "Etc/GMT-2",  # GMT+2 cố định (không đổi giờ)
    "Etc/GMT-3",  # GMT+3 cố định
)


@dataclass
class Step:
    name: str
    status: str
    detail: str
    fix: str = ""


@dataclass
class CheckReport:
    steps: list[Step] = field(default_factory=list)
    reader: Mt5Reader | None = None
    account_type: str = "UNKNOWN"
    account: Any = None
    symbol_info: Any = None
    offset_now: int | None = None
    # Khung được phép đồng bộ khi ``run`` (M15 luôn có; H1/H4/D1 chỉ khi bước kiểm tra đạt)
    timeframes_ok: list[str] = field(default_factory=lambda: ["M15"])

    def add(self, name: str, status: str, detail: str, fix: str = "") -> None:
        self.steps.append(Step(name, status, detail, fix))

    @property
    def ok(self) -> bool:
        return all(s.status != FAIL for s in self.steps)


def run_checks(
    cfg: Config,
    mt5: Any,
    client: BackendClient,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    tick_wait_s: float = 10.0,
    progress: Callable[[str], None] = lambda _msg: None,
) -> CheckReport:
    """``progress``: in tiến độ cho người dùng thấy (bước đọc MT5 có thể mất vài chục giây)."""
    rep = CheckReport()

    # 1. Cấu hình
    try:
        tz = load_tz(cfg.server_tz) if cfg.server_tz else None
    except ValueError as e:
        tz = None
        rep.add("Cấu hình múi giờ server", FAIL, str(e), "Sửa GT_SERVER_TZ trong gateway.env")
    if not cfg.server_tz:
        rep.add(
            "Cấu hình múi giờ server",
            FAIL,
            "Chưa đặt GT_SERVER_TZ",
            "Thêm GT_SERVER_TZ=Europe/Athens vào gateway.env (đa số broker GMT+2/GMT+3); "
            "bước kiểm tra giờ bên dưới sẽ xác nhận lại",
        )
    elif tz:
        rep.add(
            "Cấu hình múi giờ server",
            PASS,
            f"{cfg.server_tz} (hiện tại GMT{tz_offset_hours(tz, now()):+g})",
        )
    if len(cfg.token) < MIN_TOKEN_LEN:
        rep.add(
            "Token",
            FAIL,
            f"GT_INGEST_TOKEN phải dài ít nhất {MIN_TOKEN_LEN} ký tự",
            "Đặt cùng một token ở gateway.env và ở file .env của Docker",
        )
    else:
        rep.add("Token", PASS, f"Đã đặt ({len(cfg.token)} ký tự)")
    if tz is None:
        return rep

    # 2. MT5
    reader = Mt5Reader(
        mt5, broker_symbol=cfg.broker_symbol, server_tz=tz, terminal_path=cfg.terminal_path
    )
    rep.reader = reader
    try:
        reader.connect()
        term = reader.terminal()
        if not getattr(term, "connected", False):
            rep.add(
                "Kết nối MT5",
                FAIL,
                "MT5 đang mở nhưng chưa kết nối server broker",
                "Kiểm tra mạng và đăng nhập trong MT5 (góc dưới phải phải hiện tốc độ kết nối)",
            )
            return rep
        rep.add(
            "Kết nối MT5", PASS, f"{getattr(term, 'company', '')} · {getattr(term, 'name', '')}"
        )
    except Mt5Error as e:
        rep.add(
            "Kết nối MT5",
            FAIL,
            str(e),
            "Mở MetaTrader 5, đăng nhập tài khoản, rồi chạy lại. "
            "Nếu cài nhiều MT5, đặt GT_MT5_PATH",
        )
        return rep

    try:
        rep.account_type, rep.account = reader.account()
        # MT-12: hiện login + server để người dùng đối chiếu đúng tài khoản MT5 của mình.
        login = getattr(rep.account, "login", None)
        server = f"login {login} · {getattr(rep.account, 'server', '')}"
        if rep.account_type == "DEMO":
            rep.add("Tài khoản", PASS, f"DEMO · {server}")
        elif rep.account_type == "REAL":
            rep.add(
                "Tài khoản",
                WARN,
                f"TÀI KHOẢN THẬT · {server}",
                "Gateway chỉ đọc nên không đặt lệnh, nhưng nên dùng tài khoản demo khi thử nghiệm",
            )
        else:
            rep.add("Tài khoản", WARN, f"Loại {rep.account_type} · {server}")
    except Mt5Error as e:
        rep.add(
            "Tài khoản",
            FAIL,
            str(e),
            "Đăng nhập tài khoản trong MT5 (File → Login to Trade Account)",
        )
        return rep

    try:
        info = reader.symbol_info()
    except Mt5Error as e:
        rep.add("Symbol", FAIL, str(e), "Mở Market Watch (Ctrl+M), chuột phải → Show All")
        return rep
    if info is None:
        similar = reader.similar_symbols()
        rep.add(
            "Symbol",
            FAIL,
            f"Không tìm thấy {cfg.broker_symbol}",
            "Đặt GT_BROKER_SYMBOL theo tên trong Market Watch. "
            f"Gợi ý: {', '.join(similar) or 'không thấy'}",
        )
        return rep
    rep.symbol_info = info
    rep.add(
        "Symbol",
        PASS,
        f"{cfg.broker_symbol}: digits {info.digits}, contract {info.trade_contract_size:g}, "
        f"lot tối thiểu {info.volume_min:g}, bước lot {info.volume_step:g}",
    )

    # 3. Giờ server: tick sống
    rep.offset_now = reader.live_tick_offset(wait_s=tick_wait_s, now=lambda: now().timestamp())
    expected = tz_offset_hours(tz, now())
    if rep.offset_now is None:
        rep.add(
            "Giờ server (tick trực tiếp)",
            WARN,
            "Không có tick mới (thị trường đóng cửa hoặc đang yên) "
            "nên chưa xác nhận được độ lệch giờ",
            "Bước kiểm tra lịch sử bên dưới vẫn kiểm tra múi giờ. Nên chạy lại khi thị trường mở",
        )
    elif rep.offset_now != expected:
        rep.add(
            "Giờ server (tick trực tiếp)",
            FAIL,
            f"Server đang ở GMT{rep.offset_now:+d} nhưng {cfg.server_tz} hiện là GMT{expected:+g}",
            "Sửa GT_SERVER_TZ cho khớp (ví dụ broker GMT+2 mùa đông/GMT+3 mùa hè → Europe/Athens)",
        )
    else:
        rep.add("Giờ server (tick trực tiếp)", PASS, f"Khớp: GMT{rep.offset_now:+d}")

    # 4. Lịch sử
    try:
        progress(f"Đang đọc lịch sử M15 ({cfg.history_bars} nến) từ MT5...")
        bars = reader.closed_bars(cfg.history_bars)
    except Mt5Error as e:
        rep.add(
            "Lịch sử nến M15",
            FAIL,
            str(e),
            "Mở chart XAUUSD M15 trong MT5 cho tải lịch sử rồi chạy lại",
        )
        return rep
    if len(bars) < 300:
        rep.add(
            "Lịch sử nến M15",
            FAIL,
            f"Chỉ có {len(bars)} nến",
            "Tools → Options → Charts → Max bars in chart = Unlimited; "
            "mở chart M15 và cuộn về quá khứ",
        )
        return rep
    rep.add(
        "Lịch sử nến M15",
        PASS,
        f"{len(bars)} nến đã đóng, {bars[0].open_time_utc:%d/%m/%Y %H:%M} → "
        f"{bars[-1].open_time_utc:%d/%m/%Y %H:%M} UTC"
        + (
            f" (bỏ {reader.skipped_ambiguous} nến giờ mơ hồ do đổi DST)"
            if reader.skipped_ambiguous
            else ""
        ),
    )

    # 5. Backend
    try:
        h = client.health()
        rep.add("Backend", PASS, f"{client.base} · lưu trữ {h.get('storage')}")
    except BackendError as e:
        rep.add(
            "Backend", FAIL, str(e), "Bật Docker (docker compose up -d) và kiểm tra GT_BACKEND_URL"
        )
        return rep

    # 6. Chạy thử gửi dữ liệu (không lưu): xác thực token + R1 trên lịch sử
    try:
        progress("Đang chạy thử gửi lịch sử M15 lên backend (không lưu)...")
        r = dry_run_all(cfg, client, bars)
        detail = (
            f"{r['received']} nến: hợp lệ {r['accepted'] + r['duplicates']}, "
            f"cách ly {r['quarantined']} {r['reasons'] or ''}; "
            f"ngoài giờ giao dịch {r['session_outside_fraction']:.2%}"
        )
        rep.add("Chạy thử gửi dữ liệu (không lưu)", WARN if r["quarantined"] else PASS, detail)
    except BackendError as e:
        fix = {
            401: "Token ở gateway.env khác token ở .env của Docker",
            503: "Docker chưa đặt GT_INGEST_TOKEN: thêm vào .env rồi docker compose up -d",
        }.get(e.status or 0, "")
        detail = e.detail
        if e.status == 422:
            # Không gợi ý "độ lệch cố định" (sai khi broker đổi giờ theo mùa): thử tên múi giờ IANA
            ok = suggest_timezones(cfg, mt5, client, exclude=cfg.server_tz)
            detail = f"Múi giờ {cfg.server_tz} không khớp lịch giao dịch. {e.detail}"
            if ok:
                also = f"; cũng khớp: {', '.join(ok[1:])}" if len(ok) > 1 else ""
                fix = f"Đặt GT_SERVER_TZ={ok[0]} (khớp với dữ liệu{also})"
            else:
                fix = "Không tìm được múi giờ khớp: liên hệ broker để hỏi giờ server"
        rep.add("Chạy thử gửi dữ liệu (không lưu)", FAIL, detail, fix)
        return rep

    # 7. Khung lớn H1/H4/D1 (ING-14): đọc thẳng từ MT5, chạy thử ở backend. Không đạt thì chỉ
    # CẢNH BÁO và không đồng bộ khung đó (M15 vẫn chạy).
    extra = [t for t in cfg.timeframes if t != "M15"]
    if extra:
        check_higher_timeframes(cfg, reader, client, rep, extra, progress)
    return rep


def check_higher_timeframes(
    cfg: Config,
    reader: Mt5Reader,
    client: BackendClient,
    rep: CheckReport,
    tfs: list[str],
    progress: Callable[[str], None] = lambda _msg: None,
) -> None:
    good: list[str] = []
    notes: list[str] = []
    problems: list[str] = []
    for tf in tfs:
        try:
            n = history_bars_for(cfg, tf)
            progress(f"Đang đọc lịch sử {tf} ({n} nến) từ MT5...")
            bars = reader.closed_bars(n, tf)
        except Mt5Error as e:
            problems.append(f"{tf}: {e}")
            continue
        if not bars:
            problems.append(f"{tf}: MT5 chưa có lịch sử")
            continue
        try:
            r = dry_run_all(cfg, client, bars, timeframe=tf)
        except BackendError as e:
            problems.append(f"{tf}: backend từ chối ({e.detail})")
            continue
        reasons = r["reasons"] or {}
        if reasons.get("MISALIGNED_TIME"):
            # Nến không khớp ranh giới giờ server: múi giờ/dữ liệu sai → không gửi khung này
            problems.append(f"{tf}: {reasons['MISALIGNED_TIME']} nến lệch ranh giới giờ server")
            continue
        good.append(tf)
        note = f"{tf} {len(bars)} nến"
        if r["quarantined"]:
            note += f" (cách ly {r['quarantined']} {reasons})"
            problems.append(f"{tf}: cách ly {r['quarantined']}")
        notes.append(note)
    rep.timeframes_ok = ["M15", *good]
    detail = "; ".join(notes) if notes else "không khung nào dùng được"
    if problems:
        rep.add(
            "Khung H1/H4/D1",
            WARN,
            f"{detail}. Vấn đề: {'; '.join(problems)}",
            "Mở chart XAUUSD ở khung bị thiếu trong MT5 cho tải lịch sử rồi chạy lại check. "
            "Khung bị lỗi sẽ không được gửi; M15 vẫn chạy bình thường",
        )
    else:
        rep.add("Khung H1/H4/D1", PASS, detail)


def dry_run_all(
    cfg: Config, client: BackendClient, bars: list[Any], *, timeframe: str = "M15"
) -> dict[str, Any]:
    """Chạy thử (không lưu) TOÀN BỘ lịch sử theo lô. Lô nào bị từ chối thì ném BackendError.

    Kiểm tra cả lịch sử (không chỉ vài tuần gần nhất) để phân biệt múi giờ có giờ mùa hè với
    độ lệch cố định: sai khác chỉ lộ ra ở các tháng nằm bên kia mốc đổi giờ.
    """
    total = {
        "received": 0,
        "accepted": 0,
        "duplicates": 0,
        "quarantined": 0,
        "reasons": {},
        "session_outside_fraction": 0.0,
    }
    for i in range(0, len(bars), DRY_RUN_BARS):
        part = [b.to_json() for b in bars[i : i + DRY_RUN_BARS]]
        r = client.post_candles(
            symbol=cfg.symbol,
            bars=part,
            backfill=True,
            gateway_id=cfg.gateway_id,
            dry_run=True,
            timeframe=timeframe,
            server_tz=cfg.server_tz,
        )
        for k in ("received", "accepted", "duplicates", "quarantined"):
            total[k] += r[k]
        for k, v in (r.get("reasons") or {}).items():
            total["reasons"][k] = total["reasons"].get(k, 0) + v
        total["session_outside_fraction"] = max(
            total["session_outside_fraction"], r.get("session_outside_fraction") or 0.0
        )
    return total


def suggest_timezones(cfg: Config, mt5: Any, client: BackendClient, *, exclude: str) -> list[str]:
    """Đọc lại lịch sử với từng múi giờ ứng viên, chạy thử ở backend (không lưu); trả các tz đạt."""
    good: list[str] = []
    for name in TZ_CANDIDATES:
        if name == exclude:
            continue
        reader = Mt5Reader(
            mt5,
            broker_symbol=cfg.broker_symbol,
            server_tz=load_tz(name),
            terminal_path=cfg.terminal_path,
        )
        try:
            dry_run_all(cfg, client, reader.closed_bars(cfg.history_bars))
            good.append(name)
        except (BackendError, Mt5Error):
            continue
    return good


def print_report(rep: CheckReport, out=print) -> None:
    out("")
    out("=== KIỂM TRA MT5 GATEWAY (chỉ đọc) ===")
    for i, s in enumerate(rep.steps, 1):
        out(f"[{s.status:^8}] {i}. {s.name}: {s.detail}")
        if s.fix and s.status != PASS:
            out(f"            → Cách xử lý: {s.fix}")
    out("")
    out(
        "KẾT QUẢ: "
        + (
            "SẴN SÀNG. Chạy: mt5-gateway run"
            if rep.ok
            else "CHƯA SẴN SÀNG. Sửa các mục LỖI rồi chạy lại check"
        )
    )
