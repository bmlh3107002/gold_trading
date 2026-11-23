"""Sổ paper trong bộ nhớ có chỉ mục cho backtest (GĐ6 bước 7 — hiệu năng, thiết kế 39 mục 13).

``RiskLedger`` (GĐ5) quét **toàn bộ** sự kiện ở mỗi lần đọc → mô phỏng nhiều lệnh chậm theo bình
phương (669 lệnh / 22 tháng: 84 giây). ``FastLedger`` giữ **đúng** giao diện và ngữ nghĩa giao dịch
(ghi vào bộ đệm, commit khi ra khỏi khóa, lỗi → bỏ) nhưng đọc qua chỉ mục cập nhật lúc commit:
theo loại sự kiện, theo (loại, mã), khóa kết thúc (``once_key``), giữ chỗ / vị thế còn mở, SL dời.
Bộ test sổ cái + khớp lệnh của GĐ5 chạy cả trên lớp này (``tests/test_paper_ledger.py``,
``tests/test_paper_fill.py``) để chứng minh cùng kết quả. Chỉ dùng trong backtest.
"""

from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime

from gold_trading.risk.ledger import (
    EQUITY_TYPES,
    EquityState,
    EventType,
    LedgerEvent,
    RiskLedger,
    _MemTxn,
    replay_equity,
)


class _Index:
    def __init__(self) -> None:
        self.all: list[LedgerEvent] = []
        self.by_type: dict[EventType, list[LedgerEvent]] = defaultdict(list)
        self.first: dict[tuple[EventType, str], LedgerEvent] = {}
        self.once: set[str] = set()
        self.open: dict[EventType, dict[str, LedgerEvent]] = defaultdict(dict)
        self.sl: dict[str, LedgerEvent] = {}          # vị thế → MODIFY_SL cuối
        self.eq_last_at: datetime | None = None
        self.eq_count = 0
        self.eq_cache: tuple[EquityState | None] | None = None

    def add(self, e: LedgerEvent) -> None:
        self.all.append(e)
        self.by_type[e.type].append(e)
        self.first.setdefault((e.type, e.ref_id), e)
        if e.once_key is not None:
            self.once.add(e.once_key)
            if e.once_key.startswith("END:"):
                self.open[EventType.RESERVE].pop(e.once_key[4:], None)
            elif e.once_key.startswith("CLOSE:"):
                self.open[EventType.OPEN].pop(e.once_key[6:], None)
        if e.type in (EventType.RESERVE, EventType.OPEN) and not (
                (e.type is EventType.RESERVE and f"END:{e.ref_id}" in self.once)
                or (e.type is EventType.OPEN and f"CLOSE:{e.ref_id}" in self.once)):
            self.open[e.type][e.ref_id] = e
        if e.type is EventType.MODIFY_SL:
            self.sl[e.ref_id] = e
        if e.type in EQUITY_TYPES:
            if self.eq_last_at is None or e.at > self.eq_last_at:
                self.eq_last_at = e.at
            self.eq_count += 1
            self.eq_cache = None                      # tính lại (đúng ``replay_equity``) khi cần


class FastLedger(RiskLedger):
    def __init__(self, *, clock=None) -> None:
        if clock is None:
            super().__init__()
        else:
            super().__init__(clock=clock)
        self._idx: dict[str, _Index] = defaultdict(_Index)

    @contextmanager
    def _begin(self, account_id):
        tx = _MemTxn()
        yield tx
        with self._mem:                       # commit (như RiskLedger) + cập nhật chỉ mục
            for e in tx.events:
                if e.once_key is not None:
                    self._once.add(e.once_key)
            self._ev.setdefault(account_id, []).extend(tx.events)
            self._dec.update(tx.decisions)
            idx = self._idx[account_id]
            for e in tx.events:
                idx.add(e)

    def _tx(self, account_id) -> list[LedgerEvent]:
        h = self._handle(account_id)
        return h.events if isinstance(h, _MemTxn) else []

    def _visible(self, account_id):
        return self._idx[account_id].all + list(self._tx(account_id))

    def _append(self, h, ev):
        assert isinstance(h, _MemTxn)
        idx = self._idx[ev.account_id]
        if ev.once_key is not None and (ev.once_key in idx.once
                                        or any(e.once_key == ev.once_key for e in h.events)):
            from gold_trading.risk.ledger import LedgerConflict
            raise LedgerConflict(ev.once_key)
        last = h.events[-1] if h.events else (idx.all[-1] if idx.all else None)
        seq = (last.account_seq if last else 0) + 1
        ev = LedgerEvent(**{**ev.__dict__, "account_seq": seq})
        h.events.append(ev)
        return ev

    def _events(self, account_id, types, since=None):
        idx = self._idx[account_id]
        tx = self._tx(account_id)
        if types is None:
            rows = idx.all + list(tx)
        else:
            rows = sorted((e for t in types for e in idx.by_type.get(t, ())),
                          key=lambda e: e.account_seq) if len(types) > 1 \
                else list(idx.by_type.get(types[0], ()))
            rows += [e for e in tx if e.type in types]
        return rows if since is None else [e for e in rows if e.at >= since]

    def _find(self, account_id, type, ref_id):
        e = self._idx[account_id].first.get((type, ref_id))
        if e is not None:
            return e
        return next((x for x in self._tx(account_id) if x.type is type and x.ref_id == ref_id),
                    None)

    def _once_exists(self, account_id, key):
        return key in self._idx[account_id].once or any(e.once_key == key
                                                        for e in self._tx(account_id))

    def _open_starts(self, account_id, type, end_prefix):
        accs = [account_id] if account_id is not None else self._all_accounts()
        out = []
        for a in accs:
            idx = self._idx[a]
            tx = self._tx(a)
            ended = {e.once_key for e in tx if e.once_key}
            rows = sorted(idx.open[type].values(), key=lambda e: e.account_seq)
            rows += [e for e in tx if e.type is type]
            out += [e for e in rows if f"{end_prefix}{e.ref_id}" not in ended]
        return out

    def current_stop(self, account_id, opened):
        from decimal import Decimal
        tx = [e for e in self._tx(account_id)
              if e.type is EventType.MODIFY_SL and e.ref_id == opened.ref_id]
        m = tx[-1] if tx else self._idx[account_id].sl.get(opened.ref_id)
        return Decimal(m.data["stop_loss"] if m else opened.data["stop_loss"])

    def equity_state(self, account_id, at):
        """Nhớ kết quả ``replay_equity`` (hàm của GĐ5, không chép lại) cho tới khi có sự kiện
        equity mới; chỉ dùng khi ``at`` ≥ sự kiện equity mới nhất và không có sự kiện equity
        đang chờ commit — ngoài ra đi đường của lớp gốc."""
        idx = self._idx[account_id]
        if (idx.eq_last_at is None or at < idx.eq_last_at
                or any(e.type in EQUITY_TYPES for e in self._tx(account_id))):
            return super().equity_state(account_id, at)
        if idx.eq_cache is None:
            idx.eq_cache = (replay_equity(self._events(account_id, EQUITY_TYPES)),)
        return idx.eq_cache[0]
