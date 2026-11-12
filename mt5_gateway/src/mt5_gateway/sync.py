"""Vòng đồng bộ: nạp bù lịch sử một lần, sau đó gửi nến vừa đóng + nhịp tim. Chỉ đọc MT5.

M15 gửi mỗi vòng (như cũ). H1/H4/D1 (ING-14) chỉ gửi khi có nến mới đóng, hoặc định kỳ
``HIGHER_RESEND_S`` để bắt bản sửa của broker; backend khử trùng nên gửi lại không nhân đôi.

1A-C21: mỗi lô realtime gửi kèm nến VỊ TRÍ 0 (``tail_bar``) khi terminal đang kết nối. Backend
quyết định theo đồng hồ của nó + lịch broker có coi nến đó là đã đóng không (nến cuối phiên trước
cuối tuần / ngày lễ / giờ nghỉ), nên không phải chờ tới khi thị trường mở lại. Đã được nhận thì
không gửi lại nến vị trí 0 đó nữa.

MT-14 (0.4.0): mỗi lô nến mang danh tính MT5 (login, server, loại tài khoản) đọc NGAY TRƯỚC và
NGAY SAU khi lấy nến; hai lần khác nhau (người dùng vừa đổi tài khoản) hoặc chưa đăng nhập →
bỏ lô đó. Backend chỉ ghi khi khớp liên kết ACTIVE; bị từ chối vì liên kết (409 ``MT5_LINK_*``)
thì Gateway KHÔNG thoát: vẫn gửi nhịp tim (để web hiện MT5 cho chủ tài khoản xác nhận / thấy
cảnh báo) và thử lại định kỳ.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from mt5_gateway import __version__, snapshot
from mt5_gateway.backend_client import BackendClient, BackendError
from mt5_gateway.checks import CheckReport
from mt5_gateway.config import Config, history_bars_for
from mt5_gateway.quotes import QuoteCollector, TickRequestMismatch, TzWatch
from mt5_gateway.reader import Bar, Mt5Error, Mt5Reader, TerminalMismatch
from mt5_gateway.timeconv import tz_offset_hours

log = logging.getLogger("mt5_gateway")
BATCH = 1000
LIVE_BARS = 20
LIVE_BARS_HIGHER = 3
HIGHER_RESEND_S = 60.0
MAX_BACKOFF_S = 30.0
LINK_RETRY_S = 30.0


def read_overlapping(read: Callable[[int], list[Bar]], last: Bar | None, base: int,
                     cap: int) -> tuple[list[Bar], bool]:
    """GW-07 / 1A-C09: đọc đủ xa để nối liền với nến đã gửi cuối (``last``) — không hụt nến sau
    gián đoạn (backend tắt, mạng mất...). Đọc ``base`` nến; chưa chạm ``last`` thì đọc gấp 4,
    tối đa ``cap``. KHÔNG dựa vào đồng hồ máy (đồng hồ chậm sẽ làm đọc thiếu). MT5 chính là
    "hàng đợi bền vững": nến đã đóng nằm sẵn trong lịch sử terminal.

    Trả (nến, đã_nối_liền). ``False`` = đọc tới ``cap`` vẫn chưa chạm nến đã gửi: CÓ THỂ thiếu."""
    n = base
    while True:
        bars = read(n)
        if last is None or not bars or bars[0].open_time_utc <= last.open_time_utc:
            return bars, True
        if n >= cap or len(bars) < n:
            # hết lịch sử cấu hình / MT5 không có thêm: không nối được
            return bars, False
        n = min(cap, n * 4)


class IdentityUnstable(RuntimeError):
    """Không biết chắc nến thuộc MT5 nào (chưa đăng nhập / vừa đổi tài khoản): không gửi."""


class ServerTzChanged(RuntimeError):
    """1A-C08: giờ server broker lệch khác GT_SERVER_TZ khi đang chạy: không gửi nến/giá."""


def waiting_for_link(e: BackendError) -> bool:
    return e.status == 409 and e.detail.startswith("MT5_LINK")


def chunks(xs: list[Bar], n: int) -> list[list[Bar]]:
    return [xs[i : i + n] for i in range(0, len(xs), n)]


class Syncer:
    def __init__(
        self,
        cfg: Config,
        reader: Mt5Reader,
        client: BackendClient,
        report: CheckReport,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        now_utc: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.cfg, self.reader, self.client, self.report = cfg, reader, client, report
        self.sleep, self.clock = sleep, clock
        self.last_sent: Bar | None = None
        self.terminal_ok = True
        self.higher = [t for t in report.timeframes_ok if t != "M15"]
        self.last_sent_tf: dict[str, Bar] = {}
        self._next_resend: dict[str, float] = {}
        self._retry_after: dict[str, float] = {}
        self._tail_done: dict[str, Any] = {}  # khung → open_time nến vị trí 0 backend đã nhận
        self._connected: bool | None = None  # đọc một lần mỗi vòng push_recent
        self.backfilled = False
        self._backfill_retry_at = 0.0
        self._last_wait: str | None = None  # thông báo chờ liên kết gần nhất (tránh lặp log)
        self.now_utc = now_utc
        self._gap_warned: set[tuple[str, Any]] = set()
        # 1A-C08: theo dõi độ lệch giờ server khi đang chạy
        self.tzwatch = TzWatch(reader.tz)
        # GW-08: giá sống (chỉ khi check tự kiểm đạt)
        point = getattr(report.symbol_info, "point", None)
        # 5d: 6 cặp tiền chỉ số USD (chỉ những cặp check thấy có trong MT5)
        from mt5_gateway.fx import FxSync

        self.fx = FxSync(self, list(report.fx_pairs_ok))
        self.quotes: QuoteCollector | None = (
            QuoteCollector(reader, reader.tz, float(point), now=now_utc)
            if report.quotes_ok and isinstance(point, (int, float)) and point > 0 else None
        )

    @property
    def timeframes(self) -> list[str]:
        return ["M15", *self.higher]

    def _read(self, fn: Callable[[], Any]) -> tuple[Any, dict[str, Any]]:
        """Đọc nến kẹp giữa hai lần đọc danh tính MT5 (MT-14). MT-15: trước đó kiểm đúng
        terminal đã cấu hình (sai → ``Mt5Error``, vòng chạy nối lại, không gửi gì)."""
        self.reader.ensure_terminal()
        before = snapshot.batch_identity(self.reader)
        if before is None:
            raise IdentityUnstable("MT5 chưa đăng nhập tài khoản: không gửi nến")
        out = fn()
        after = snapshot.batch_identity(self.reader)
        if after != before:
            raise IdentityUnstable("Tài khoản MT5 vừa thay đổi trong lúc đọc nến: bỏ lô này")
        return out, before

    def _post(
        self,
        tf: str,
        bars: list[Bar],
        *,
        backfill: bool,
        tail: Bar | None = None,
        ident: dict[str, Any] | None = None,
    ) -> Any:
        kw: dict[str, Any] = {}
        if ident is not None:
            kw["identity"] = ident
        if tail is not None:
            kw["tail_bar"] = tail.to_json()
        return self.client.post_candles(
            symbol=self.cfg.symbol,
            bars=[b.to_json() for b in bars],
            backfill=backfill,
            gateway_id=self.cfg.gateway_id,
            timeframe=tf,
            server_tz=self.cfg.server_tz,
            **kw,
        )

    def _tail_to_send(self, tf: str, tail: Bar | None) -> Bar | None:
        """Nến vị trí 0 chỉ gửi khi terminal đang kết nối (mất kết nối → nến có thể thiếu tick)
        và chưa được backend nhận trước đó."""
        if tail is None or self._tail_done.get(tf) == tail.open_time_utc:
            return None
        if self._connected is None:
            self._connected = self.reader.terminal_connected()
        return tail if self._connected else None

    def _after_post(self, tf: str, tail: Bar | None, r: Any) -> None:
        if tail is not None and isinstance(r, dict) and r.get("tail") == "INCLUDED":
            self._tail_done[tf] = tail.open_time_utc
            log.info(
                "Nến cuối phiên %s %s: thị trường đóng cửa, backend đã nhận (1A-C21)",
                tf,
                f"{tail.open_time_utc:%d/%m %H:%M} UTC",
            )
            self.last_sent_tf[tf] = tail
            if tf == "M15":
                self.last_sent = tail

    def backfill(self) -> dict[str, int]:
        """Nạp bù M15 rồi các khung lớn. Trả tổng của M15 (giữ như cũ)."""
        totals = self._backfill_tf("M15")
        for tf in list(self.higher):
            try:
                self._backfill_tf(tf)
            except BackendError as e:
                if waiting_for_link(e):
                    raise  # liên kết vừa đổi: thử lại cả lượt nạp bù sau, không bỏ khung
                log.warning("Nạp bù %s lỗi: %s. Tạm không đồng bộ %s; chạy lại run sau.", tf, e, tf)
                self.higher.remove(tf)
            except TerminalMismatch:
                raise  # nối nhầm terminal: dừng cả lượt, không tắt khung này
            except Mt5Error as e:
                # Không làm hỏng M15. Khung này tắt tới lần chạy sau (không gửi lịch sử dở dang).
                log.warning("Nạp bù %s lỗi: %s. Tạm không đồng bộ %s; chạy lại run sau.", tf, e, tf)
                self.higher.remove(tf)
        self.backfilled = True
        return totals

    def _backfill_tf(self, tf: str) -> dict[str, int]:
        n = history_bars_for(self.cfg, tf)
        bars, ident = self._read(lambda: self.reader.closed_bars(n, tf))
        totals = {"accepted": 0, "duplicates": 0, "quarantined": 0}
        for part in chunks(bars, BATCH):
            r = self._post(tf, part, backfill=True, ident=ident)
            for k in totals:
                totals[k] += r[k]
        if bars:
            self.last_sent_tf[tf] = bars[-1]
            if tf == "M15":
                self.last_sent = bars[-1]
        log.info("Nạp bù lịch sử %s: %s", tf, totals)
        return totals

    def heartbeat_payload(self) -> dict[str, Any]:
        """Nhịp tim. MT-12/GW-09: danh tính, tài khoản, symbol đọc TRỰC TIẾP mỗi lần (không lấy từ
        lúc ``check``), để báo đúng tài khoản đang đăng nhập nếu người dùng đổi trong terminal."""
        ident = snapshot.identity(self.reader)
        last_tick = None
        try:
            t = self.reader.last_tick_utc()
            last_tick = t.isoformat() if t else None
        except Exception:
            pass
        return {
            "gateway_id": self.cfg.gateway_id,
            "gateway_version": __version__,
            "read_only": True,
            "terminal_connected": self.terminal_ok,
            # Ba trường cũ giữ cho backend bản trước; cùng nguồn với ``identity``.
            "account_type": ident["account_type"] if ident else "UNKNOWN",
            "server": ident["server"] if ident else None,
            "company": ident["company"] if ident else None,
            "identity": ident,
            "account": snapshot.account(self.reader),
            "server_tz": self.cfg.server_tz,
            "server_offset_hours_now": (
                self.tzwatch.last_offset
                if self.tzwatch.last_offset is not None else self.report.offset_now
            ),
            "last_tick_time": last_tick,
            "symbol": snapshot.symbol(self.reader, self.cfg.broker_symbol),
            "last_sent_bar": self.last_sent.open_time_utc.isoformat() if self.last_sent else None,
            "timeframes": self.timeframes,
        }

    def _read_from_last(self, tf: str, base: int, read: Callable[[int], Any],
                        split: Callable[[Any], list[Bar]]) -> tuple[Any, dict[str, Any]]:
        """Đọc (kẹp danh tính) đủ xa để nối liền nến ``tf`` đã gửi cuối; báo rõ nếu vẫn hở."""
        last = self.last_sent_tf.get(tf)
        cap = max(base, history_bars_for(self.cfg, tf))
        box: dict[str, Any] = {}

        def one(n: int) -> list[Bar]:
            box["out"] = read(n)
            return split(box["out"])

        (bars, joined), ident = self._read(lambda: read_overlapping(one, last, base, cap))
        if last is not None and len(bars) > base:
            log.info("Nạp bù sau gián đoạn: %d nến %s", len(bars), tf)
        if not joined and last is not None:
            key = (tf, last.open_time_utc)
            if key not in self._gap_warned:
                self._gap_warned.add(key)
                log.warning(
                    "Gián đoạn dài hơn lịch sử đọc được (%d nến %s): có thể THIẾU nến %s sau %s "
                    "UTC. Tăng GT_HISTORY_BARS rồi chạy lại run để nạp đủ.",
                    cap, tf, tf, f"{last.open_time_utc:%d/%m %H:%M}",
                )
        return box["out"], ident

    def _post_chunks(self, tf: str, bars: list[Bar], *, tail: Bar | None,
                     ident: dict[str, Any]) -> Any:
        """Gửi theo lô ≤ BATCH (nạp bù sau gián đoạn có thể nhiều nến). Nến vị trí 0 (tail) đi
        kèm lô cuối. Nến tới muộn gửi realtime (backfill=false) → available_at = lúc nhận."""
        if len(bars) <= BATCH:
            return self._post(tf, bars, backfill=False, tail=tail, ident=ident)
        total: dict[str, Any] = {"accepted": 0, "quarantined": 0, "revised": 0, "duplicates": 0,
                                 "reasons": {}}
        parts = chunks(bars, BATCH)
        for i, part in enumerate(parts):
            r = self._post(tf, part, backfill=False, ident=ident,
                           tail=tail if i == len(parts) - 1 else None)
            for k in ("accepted", "quarantined", "revised", "duplicates"):
                total[k] += r.get(k, 0)
            for k, v in (r.get("reasons") or {}).items():
                total["reasons"][k] = total["reasons"].get(k, 0) + v
            if "tail" in r:
                total["tail"] = r["tail"]
        return total

    def push_recent(self) -> dict[str, Any] | None:
        self._connected = None
        (bars, tail), ident = self._read_from_last(
            "M15", LIVE_BARS, self.reader.bars_with_tail, lambda o: o[0])
        tail = self._tail_to_send("M15", tail)
        r = None
        if bars or tail:
            r = self._post_chunks("M15", bars, tail=tail, ident=ident)
            if r["accepted"] or r["quarantined"]:
                log.info(
                    "Nến M15 mới: +%d, cách ly %d %s", r["accepted"], r["quarantined"], r["reasons"]
                )
            if bars and (
                self.last_sent is None or bars[-1].open_time_utc > self.last_sent.open_time_utc
            ):
                self.last_sent = bars[-1]
                self.last_sent_tf["M15"] = bars[-1]
            self._after_post("M15", tail, r)
        for tf in self.higher:
            try:
                self._push_higher(tf)
            except IdentityUnstable as e:
                log.info("%s (%s)", e, tf)
                return r
            except TerminalMismatch:
                raise
            except (Mt5Error, BackendError) as e:
                # Lỗi riêng một khung lớn không được làm ngừng M15; thử lại ở lần định kỳ sau.
                log.warning("Gửi nến %s lỗi: %s", tf, e)
                self._retry_after[tf] = self.clock() + HIGHER_RESEND_S
        return r

    def _push_higher(self, tf: str) -> None:
        now = self.clock()
        if now < self._retry_after.get(tf, 0.0):
            return
        (bars, tail), ident = self._read_from_last(
            tf, LIVE_BARS_HIGHER, lambda n: self.reader.bars_with_tail(n, tf), lambda o: o[0])
        if not bars:
            return
        prev = self.last_sent_tf.get(tf)
        is_new = prev is None or bars[-1].open_time_utc > prev.open_time_utc
        if not is_new and now < self._next_resend.get(tf, 0.0):
            return
        tail = self._tail_to_send(tf, tail)
        r = self._post_chunks(tf, bars, tail=tail, ident=ident)
        if r["accepted"] or r["quarantined"] or r.get("revised"):
            log.info(
                "Nến %s: +%d, sửa %d, cách ly %d %s",
                tf,
                r["accepted"],
                r.get("revised", 0),
                r["quarantined"],
                r["reasons"],
            )
        if prev is None or bars[-1].open_time_utc > prev.open_time_utc:
            self.last_sent_tf[tf] = bars[-1]
        self._after_post(tf, tail, r)
        self._next_resend[tf] = now + HIGHER_RESEND_S

    def _quotes_off(self, why: str) -> None:
        log.error("Tắt gửi giá sống: %s (nến vẫn chạy). Chạy lại run để thử lại.", why)
        self.quotes = None

    def push_quotes(self) -> dict[str, Any] | None:
        """GW-08: gom tick thành giây đã trọn rồi gửi. Lỗi riêng của giá sống không làm ngừng
        nến (trừ chờ liên kết / sai danh tính, xử lý chung ở vòng chạy)."""
        if self.quotes is None:
            return None
        q = self.quotes
        try:
            got, ident = self._read(q.collect)
        except TickRequestMismatch as e:
            self._quotes_off(str(e))
            return None
        except TerminalMismatch:
            raise
        except Mt5Error as e:
            log.warning("Đọc tick lỗi: %s (thử lại vòng sau)", e)
            return None
        if got.skipped_gap_s:
            log.info("Bỏ qua %d giây giá sống cũ (gián đoạn dài); nến vẫn đầy đủ",
                     got.skipped_gap_s)
        if not got.seconds and not got.dropped:
            q.cursor = got.next_cursor
            return None
        body = {
            "symbol": self.cfg.symbol, "gateway_id": self.cfg.gateway_id,
            "mt5_login": ident["mt5_login"], "mt5_server": ident["mt5_server"],
            "mt5_account_type": ident["mt5_account_type"],
            "broker_symbol": ident["broker_symbol"], "point": q.point,
            "seconds": got.seconds, "gateway_dropped": got.dropped,
        }
        try:
            r = self.client.post_quotes(body)
        except BackendError as e:
            if waiting_for_link(e):
                raise
            if e.status == 404:
                self._quotes_off("backend chưa có cổng nhận giá sống (cần cập nhật backend)")
                return None
            log.warning("Gửi giá sống lỗi: %s (thử lại vòng sau)", e)
            return None
        q.cursor = got.next_cursor
        if isinstance(r, dict) and (r.get("dropped") or got.dropped):
            log.warning("Giá sống: backend bỏ %s, Gateway bỏ %s", r.get("dropped"), got.dropped)
        return r

    def watch_tz(self) -> None:
        """1A-C08: so giờ tick mới nhất với đồng hồ máy; lệch kéo dài → ``ServerTzChanged``."""
        msc = self.reader.last_tick_msc()
        self.tzwatch.observe(msc / 1000 if msc is not None else None, self.now_utc())
        if self.tzwatch.paused and not self.tzwatch.blocked:
            raise ServerTzChanged(
                f"SERVER_TZ_SUSPECT: tick mới báo giờ server GMT{self.tzwatch.last_offset:+d}, "
                f"khác {self.cfg.server_tz}. Tạm dừng gửi nến + giá trong lúc xác nhận"
            )
        if self.tzwatch.blocked and self.tzwatch.last_offset == tz_offset_hours(
                self.reader.tz, self.now_utc()):
            raise ServerTzChanged(
                "SERVER_TZ_CHANGED: giờ server đã khớp lại GT_SERVER_TZ, chờ xác nhận thêm vài "
                "lần rồi tự gửi tiếp"
            )
        if self.tzwatch.blocked:
            raise ServerTzChanged(
                f"SERVER_TZ_CHANGED: giờ server broker đang lệch GMT{self.tzwatch.last_offset:+d}, "
                f"khác {self.cfg.server_tz}. Ngừng gửi nến + giá để không sai giờ; kiểm tra giờ "
                "broker rồi sửa GT_SERVER_TZ (chạy lại check)"
            )

    def _heartbeat(self) -> None:
        try:
            self.client.heartbeat(self.heartbeat_payload())
        except BackendError as e:
            log.warning("Gửi nhịp tim lỗi: %s", e)

    def _wait_note(self, msg: str) -> None:
        if msg != self._last_wait:
            log.warning("Chưa gửi nến: %s", msg)
            self._last_wait = msg

    def run_forever(self, stop: Callable[[], bool] = lambda: False) -> None:
        """Nạp bù (nếu chưa) rồi đồng bộ. Nhịp tim gửi đều theo lịch, KỂ CẢ khi nến đang bị
        chặn (chờ liên kết MT5) hay backend/MT5 lỗi."""
        backoff = 1.0
        next_hb = 0.0
        while not stop():
            if self.clock() >= next_hb:
                self._heartbeat()
                next_hb = self.clock() + self.cfg.heartbeat_seconds
            try:
                self.watch_tz()
                if not self.backfilled:
                    if self.clock() >= self._backfill_retry_at:
                        self.backfill()
                        log.info("Đồng bộ nến %s (chỉ đọc).", ", ".join(self.timeframes))
                else:
                    self.push_recent()
                    self.push_quotes()
                    self.fx.push(self.clock)
                self.terminal_ok = True
                backoff = 1.0
                if self._last_wait is not None:
                    log.info("Đã gửi nến bình thường trở lại.")
                    self._last_wait = None
            except ServerTzChanged as e:
                self._wait_note(str(e))
                self.backfilled = False  # khớp lại thì nạp bù lại (backend khử trùng)
                self.fx.reset()
                self._backfill_retry_at = self.clock() + self.cfg.poll_seconds
            except IdentityUnstable as e:
                self._wait_note(str(e))
                self._backfill_retry_at = self.clock() + self.cfg.poll_seconds
            except Mt5Error as e:
                self.terminal_ok = False
                log.warning("MT5 lỗi: %s. Thử kết nối lại sau %.0fs", e, backoff)
                try:
                    self.reader.connect()
                except Mt5Error:
                    pass
                self.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_S)
                continue
            except BackendError as e:
                if waiting_for_link(e):
                    # Không thoát, không dồn lỗi: chờ chủ tài khoản xác nhận / xác minh trên web.
                    self._wait_note(e.detail)
                    # Khi thông lại: nạp bù lại cả lịch sử (backend khử trùng), không chỉ 20 nến
                    # gần nhất, để không hụt nến của khoảng thời gian bị chặn.
                    self.backfilled = False
                    self.fx.reset()
                    self._backfill_retry_at = self.clock() + LINK_RETRY_S
                    self.sleep(self.cfg.poll_seconds)
                    continue
                log.warning("Backend lỗi: %s. Thử lại sau %.0fs", e, backoff)
                self.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_S)
                continue
            self.sleep(self.cfg.poll_seconds)
