"""Snapshot Builder (docs/05): gom output analyst còn hạn thành ảnh chụp bất biến."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from gold_trading.common.ids import new_id
from gold_trading.contracts.analyst import AnalystOutput
from gold_trading.contracts.snapshot import Snapshot


def build_snapshot(outputs: Iterable[AnalystOutput], at: datetime) -> Snapshot:
    """Chọn output mới nhất còn hiệu lực tại ``at`` cho mỗi analyst."""
    latest: dict[str, AnalystOutput] = {}
    for out in outputs:
        if not out.is_valid_at(at):
            continue
        cur = latest.get(out.analyst_id)
        if cur is None or out.as_of > cur.as_of:
            latest[out.analyst_id] = out

    chosen = tuple(sorted(latest.values(), key=lambda o: o.analyst_id))
    if chosen:
        event_time = max(o.as_of for o in chosen)
        expires_at = min(o.expires_at for o in chosen)
    else:
        event_time = at
        expires_at = at
    return Snapshot(
        snapshot_id=new_id("snap"),
        event_time=event_time,
        available_at=at,
        expires_at=max(expires_at, at),
        analyst_outputs=chosen,
        input_manifest={o.analyst_id: o.output_id for o in chosen},
    )
