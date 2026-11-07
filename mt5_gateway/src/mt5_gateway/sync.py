"""Vòng đồng bộ: nạp bù lịch sử một lần, sau đó gửi nến vừa đóng + nhịp tim. Chỉ đọc MT5.

M15 gửi mỗi vòng (như cũ). H1/H4/D1 (ING-14) chỉ gửi khi có nến mới đóng, hoặc định kỳ
``HIGHER_RESEND_S`` để bắt bản sửa của broker; backend khử trùng nên gửi lại không nhân đôi.

1A-C21: mỗi lô realtime gửi kèm nến VỊ TRÍ 0 (``tail_bar``) khi terminal đang kết nối. Backend
quyết định theo đồng hồ của nó + lịch broker có coi nến đó là đã đóng không (nến cuối phiên trước
cuối tuần / ngày lễ / giờ nghỉ), nên không phải chờ tới khi thị trường mở lại. Đã được nhận thì
không gửi lại nến vị trí 0 đó nữa.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from mt5_gateway import __version__, snapshot
from mt5_gateway.backend_client import BackendClient, BackendError
from mt5_gateway.checks import CheckReport
from mt5_gateway.config import Config, history_bars_for
from mt5_gateway.reader import Bar, Mt5Error, Mt5Reader

log = logging.getLogger("mt5_gateway")
BATCH = 1000
LIVE_BARS = 20
LIVE_BARS_HIGHER = 3
HIGHER_RESEND_S = 60.0
MAX_BACKOFF_S = 30.0


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

    @property
    def timeframes(self) -> list[str]:
        return ["M15", *self.higher]

    def _post(self, tf: str, bars: list[Bar], *, backfill: bool, tail: Bar | None = None) -> Any:
        kw: dict[str, Any] = {}
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
            except (Mt5Error, BackendError) as e:
                # Không làm hỏng M15. Khung này tắt tới lần chạy sau (không gửi lịch sử dở dang).
                log.warning("Nạp bù %s lỗi: %s. Tạm không đồng bộ %s; chạy lại run sau.", tf, e, tf)
                self.higher.remove(tf)
        return totals

    def _backfill_tf(self, tf: str) -> dict[str, int]:
        bars = self.reader.closed_bars(history_bars_for(self.cfg, tf), tf)
        totals = {"accepted": 0, "duplicates": 0, "quarantined": 0}
        for part in chunks(bars, BATCH):
            r = self._post(tf, part, backfill=True)
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
            "server_offset_hours_now": self.report.offset_now,
            "last_tick_time": last_tick,
            "symbol": snapshot.symbol(self.reader, self.cfg.broker_symbol),
            "last_sent_bar": self.last_sent.open_time_utc.isoformat() if self.last_sent else None,
            "timeframes": self.timeframes,
        }

    def push_recent(self) -> dict[str, Any] | None:
        self._connected = None
        bars, tail = self.reader.bars_with_tail(LIVE_BARS)
        tail = self._tail_to_send("M15", tail)
        r = None
        if bars or tail:
            r = self._post("M15", bars, backfill=False, tail=tail)
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
            except (Mt5Error, BackendError) as e:
                # Lỗi riêng một khung lớn không được làm ngừng M15; thử lại ở lần định kỳ sau.
                log.warning("Gửi nến %s lỗi: %s", tf, e)
                self._retry_after[tf] = self.clock() + HIGHER_RESEND_S
        return r

    def _push_higher(self, tf: str) -> None:
        now = self.clock()
        if now < self._retry_after.get(tf, 0.0):
            return
        bars, tail = self.reader.bars_with_tail(LIVE_BARS_HIGHER, tf)
        if not bars:
            return
        prev = self.last_sent_tf.get(tf)
        is_new = prev is None or bars[-1].open_time_utc > prev.open_time_utc
        if not is_new and now < self._next_resend.get(tf, 0.0):
            return
        tail = self._tail_to_send(tf, tail)
        r = self._post(tf, bars, backfill=False, tail=tail)
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

    def run_forever(self, stop: Callable[[], bool] = lambda: False) -> None:
        backoff = 1.0
        next_hb = 0.0
        while not stop():
            try:
                self.push_recent()
                self.terminal_ok = True
                backoff = 1.0
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
                log.warning("Backend lỗi: %s. Thử lại sau %.0fs", e, backoff)
                self.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_S)
                continue
            if self.clock() >= next_hb:
                try:
                    self.client.heartbeat(self.heartbeat_payload())
                except BackendError as e:
                    log.warning("Gửi nhịp tim lỗi: %s", e)
                next_hb = self.clock() + self.cfg.heartbeat_seconds
            self.sleep(self.cfg.poll_seconds)
