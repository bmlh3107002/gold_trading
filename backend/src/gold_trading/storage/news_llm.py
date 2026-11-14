"""Sổ gọi Claude cho News analyst (GĐ3 bước 6, migration 0017) — chỉ thêm.

Bản bộ nhớ + bản SQL cùng giao diện ``analysts.news_llm.LlmStore``. Ghi trùng ``call_id`` (cùng tin,
prompt, mô hình, lần thử) → False (khóa chính quyết định, kể cả hai tiến trình cùng lúc).
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError

from gold_trading.analysts.news_llm import CallRow
from gold_trading.storage.schema import news_llm_calls

_C = news_llm_calls.c


def _utc(v: datetime) -> datetime:
    return v.replace(tzinfo=UTC) if v.tzinfo is None else v.astimezone(UTC)


class InMemoryNewsLlmStore:
    def __init__(self) -> None:
        self._rows: dict[str, CallRow] = {}
        self._lock = threading.Lock()

    def append(self, row: CallRow) -> bool:
        with self._lock:
            if row.call_id in self._rows or any(
                    (r.story_key, r.prompt_version, r.model, r.attempt)
                    == (row.story_key, row.prompt_version, row.model, row.attempt)
                    for r in self._rows.values()):
                return False
            self._rows[row.call_id] = row
            return True

    def spent_between(self, lo: datetime, hi: datetime) -> Decimal:
        with self._lock:
            return sum((r.cost_usd for r in self._rows.values() if lo <= r.created_at <= hi),
                       Decimal(0))

    def calls_for(self, story_key: str) -> list[CallRow]:
        with self._lock:
            return sorted((r for r in self._rows.values() if r.story_key == story_key),
                          key=lambda r: (r.created_at, r.attempt))

    def calls_between(self, lo: datetime, hi: datetime) -> list[CallRow]:
        with self._lock:
            return sorted((r for r in self._rows.values() if lo <= r.created_at <= hi),
                          key=lambda r: (r.created_at, r.call_id))


def _row(m) -> CallRow:
    return CallRow(call_id=m.call_id, story_key=m.story_key, attempt=m.attempt,
                   created_at=_utc(m.created_at), model=m.model, served_model=m.served_model,
                   prompt_version=m.prompt_version, status=m.status,
                   input_tokens=m.input_tokens, output_tokens=m.output_tokens,
                   cost_usd=Decimal(m.cost_usd), error_code=m.error_code,
                   request_id=m.request_id, result=m.result)


class SqlNewsLlmStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def append(self, row: CallRow) -> bool:
        values = dict(call_id=row.call_id, story_key=row.story_key[:256], attempt=row.attempt,
                      created_at=row.created_at, model=row.model[:64],
                      served_model=(row.served_model or None) and row.served_model[:64],
                      prompt_version=row.prompt_version, status=row.status,
                      input_tokens=row.input_tokens, output_tokens=row.output_tokens,
                      cost_usd=format(row.cost_usd, "f"), error_code=row.error_code,
                      request_id=(row.request_id or None) and row.request_id[:128],
                      result=row.result)
        try:
            with self.engine.begin() as conn:
                conn.execute(news_llm_calls.insert().values(**values))
        except IntegrityError:
            return False
        return True

    def spent_between(self, lo: datetime, hi: datetime) -> Decimal:
        q = select(_C.cost_usd).where(_C.created_at >= lo, _C.created_at <= hi)
        with self.engine.connect() as conn:
            return sum((Decimal(v) for (v,) in conn.execute(q)), Decimal(0))

    def calls_for(self, story_key: str) -> list[CallRow]:
        q = select(news_llm_calls).where(_C.story_key == story_key[:256]).order_by(
            _C.created_at, _C.attempt)
        with self.engine.connect() as conn:
            return [_row(m) for m in conn.execute(q)]

    def calls_between(self, lo: datetime, hi: datetime) -> list[CallRow]:
        q = select(news_llm_calls).where(_C.created_at >= lo, _C.created_at <= hi).order_by(
            _C.created_at, _C.call_id)
        with self.engine.connect() as conn:
            return [_row(m) for m in conn.execute(q)]
