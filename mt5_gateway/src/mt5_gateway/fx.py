"""5d (chuẩn bị ING-24, DEC-03): đồng bộ nến M15 ĐÃ ĐÓNG của 6 cặp tiền chỉ số USD. Chỉ đọc MT5.

Mỗi cặp độc lập: lỗi / thiếu một cặp không làm ngừng vàng hay cặp khác (chỉ số USD sau này sẽ
báo "không đủ dữ liệu" khi thiếu cặp, không nội suy). Mỗi lô kẹp giữa hai lần đọc danh tính MT5
(như nến vàng). Nạp bù lịch sử từng cặp (lười, trong vòng chạy) rồi gửi khi có nến mới đóng hoặc
định kỳ ``RESEND_S`` để bắt bản sửa của broker.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mt5_gateway.backend_client import BackendError
from mt5_gateway.reader import Bar, Mt5Error, Mt5Reader, TerminalMismatch

if TYPE_CHECKING:
    from mt5_gateway.sync import Syncer

log = logging.getLogger("mt5_gateway.fx")
FX_LIVE_BARS = 20
RESEND_S = 60.0
RETRY_S = 60.0
BATCH = 1000


@dataclass
class PairState:
    pair: str
    broker: str
    reader: Mt5Reader
    backfilled: bool = False
    last_sent: Bar | None = None
    next_try: float = 0.0
    next_resend: float = 0.0


class FxSync:
    def __init__(self, syncer: Syncer, pairs: list[tuple[str, str]]) -> None:
        self.s = syncer
        r = syncer.reader
        self.pairs = [
            PairState(p, b, Mt5Reader(r.mt5, broker_symbol=b, server_tz=r.tz))
            for p, b in pairs
        ]
        self.enabled = bool(self.pairs)

    def reset(self) -> None:
        """Sau thời gian bị chặn (chờ liên kết / giờ server lệch): nạp bù lại (backend khử
        trùng)."""
        for st in self.pairs:
            st.backfilled = False
            st.next_try = 0.0

    def _post(self, st: PairState, bars: list[Bar], ident: dict[str, Any], backfill: bool) -> Any:
        return self.s.client.post_fx_candles({
            "pair": st.pair, "broker_symbol": st.broker, "timeframe": "M15",
            "server_tz": self.s.cfg.server_tz, "backfill": backfill,
            "gateway_id": self.s.cfg.gateway_id, "bars": [b.to_json() for b in bars],
            "mt5_login": ident["mt5_login"], "mt5_server": ident["mt5_server"],
            "mt5_account_type": ident["mt5_account_type"],
        })

    def _one(self, st: PairState, now: float) -> None:
        if not st.backfilled:
            n = self.s.cfg.history_bars
            bars, ident = self.s._read(lambda: st.reader.closed_bars(n))
            for i in range(0, len(bars), BATCH):
                self._post(st, bars[i:i + BATCH], ident, backfill=True)
            st.backfilled = True
            st.last_sent = bars[-1] if bars else None
            st.next_resend = now + RESEND_S
            log.info("Nạp bù %s (%s): %d nến M15", st.pair, st.broker, len(bars))
            return
        bars, ident = self.s._read(lambda: st.reader.closed_bars(FX_LIVE_BARS))
        if not bars:
            return
        is_new = st.last_sent is None or bars[-1].open_time_utc > st.last_sent.open_time_utc
        if not is_new and now < st.next_resend:
            return
        self._post(st, bars, ident, backfill=False)
        if is_new:
            st.last_sent = bars[-1]
        st.next_resend = now + RESEND_S

    def push(self, clock: Callable[[], float]) -> None:
        if not self.enabled:
            return
        for st in self.pairs:
            now = clock()
            if now < st.next_try:
                continue
            try:
                self._one(st, now)
            except TerminalMismatch:
                raise
            except BackendError as e:
                if e.status == 409 and e.detail.startswith("MT5_LINK"):
                    raise  # chờ liên kết: xử lý chung ở vòng chạy
                if e.status == 404:
                    log.error("Backend chưa có cổng nhận nến cặp tiền (cần cập nhật backend): "
                              "tắt gửi 6 cặp tiền, vàng vẫn chạy")
                    self.enabled = False
                    return
                log.warning("Gửi nến %s lỗi: %s (thử lại sau %.0fs)", st.pair, e, RETRY_S)
                st.next_try = now + RETRY_S
            except Mt5Error as e:
                log.warning("Đọc nến %s (%s) lỗi: %s (thử lại sau %.0fs)", st.pair, st.broker, e,
                            RETRY_S)
                st.next_try = now + RETRY_S
