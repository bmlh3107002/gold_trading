"""Snapshot Builder (docs/05; thiết kế 33 mục 3 — GĐ4 bước 2: SNP-01, SNP-02; 4-C06).

Gom output analyst **còn hiệu lực** tại ``at`` cho **một nguồn giá** (MT-05) thành ảnh chụp:

- Technical / Regime / Macro: phạm vi của nguồn giá đó; Event / Positioning / News: toàn cục.
- Point-in-time: chỉ output đã ghi trước ``at`` (``known_by = at``). Output mới nhất đã biết nhưng
  hết hạn → **không** lùi về bản cũ hơn; ghi vào ``excluded_inputs`` để Quality Gate báo "hết hạn".
- ``as_of > at`` → lỗi lập trình (nhìn trước tương lai) → ném lỗi, không âm thầm bỏ qua.
- ``snapshot_id`` xác định theo phạm vi + manifest + danh sách bị loại → replay không nhân đôi.
- Có đầu vào SAMPLE → cờ ``SAMPLE_DATA`` (4-C06).

Tái dựng: ``rebuild`` đọc lại đúng các ``output_id`` trong manifest (``analyst_outputs`` chỉ-thêm);
thiếu một output hoặc output được ghi sau ``available_at`` → ``SnapshotRebuildError``, không đoán.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime

from gold_trading.analysts.framework import GLOBAL_SCOPE, Scope, input_digest
from gold_trading.contracts.analyst import AnalystOutput
from gold_trading.contracts.market_view import SAMPLE_DATA
from gold_trading.contracts.snapshot import Snapshot

BUILDER_VERSION = "snapshot-1.0.0"
PRICE_ANALYSTS = ("technical", "regime", "macro")
GLOBAL_ANALYSTS = ("event", "positioning", "news")
ANALYSTS = PRICE_ANALYSTS + GLOBAL_ANALYSTS
# DEC-24 (người dùng 2026-11-15): thiếu một trong ba → Quality Gate REJECTED (bước 3).
REQUIRED = frozenset({"technical", "regime", "event"})


class SnapshotRebuildError(RuntimeError):
    """Không tái dựng được snapshot từ manifest (thiếu output / sai thời điểm / lệch nội dung)."""


def scope_for(analyst_id: str, price_scope: Scope) -> Scope:
    if analyst_id in PRICE_ANALYSTS:
        return price_scope
    if analyst_id in GLOBAL_ANALYSTS:
        return GLOBAL_SCOPE
    raise ValueError(f"analyst không thuộc snapshot: {analyst_id!r}")


def _check_price_scope(price_scope: Scope) -> None:
    if not isinstance(price_scope, Scope) or price_scope.is_global:
        raise ValueError("snapshot phải theo một nguồn giá cụ thể (không phải phạm vi toàn cục)")


def _belongs(out: AnalystOutput, scope: Scope) -> bool:
    """Kiểm phạm vi qua ``output_id`` — chỉ dùng khi KHÔNG có phạm vi từ kho (gọi trực tiếp).

    Technical có trước khung chung: ``technical:<ver>:<SRC>:<SYM>:<TF>:...`` — không có feed trong
    id nên chỉ kiểm được nguồn / mã / khung (soát 5b, 2026-11-15). Đường chính (``collect`` /
    ``rebuild``) kiểm bằng cột phạm vi trong kho."""
    if f":{scope.key}:" in out.output_id:
        return True
    legacy = f"technical:{out.version}:{scope.source}:{scope.symbol}:{scope.timeframe}:"
    return out.analyst_id == "technical" and out.output_id.startswith(legacy)


def snapshot_id(price_scope: Scope, manifest: Mapping[str, str],
                excluded: Mapping[str, str]) -> str:
    digest = input_digest({"builder": BUILDER_VERSION, "inputs": dict(manifest),
                           "excluded": dict(excluded)})
    return f"snap:{price_scope.key}:{digest[:16]}"


def build_snapshot(
    latest: Mapping[str, AnalystOutput],
    price_scope: Scope,
    at: datetime,
    *,
    required: frozenset[str] = REQUIRED,
    scopes: Mapping[str, Scope] | None = None,
) -> Snapshot:
    """``latest``: analyst → output **mới nhất đã biết tại ``at``** (đã lọc ``known_by``).
    ``scopes``: phạm vi kho đã dùng để đọc từng output (cột trong kho) — có thì kiểm bằng nó."""
    _check_price_scope(price_scope)
    used: dict[str, AnalystOutput] = {}
    excluded: dict[str, str] = {}
    for analyst_id in sorted(latest):
        out = latest[analyst_id]
        if out.analyst_id != analyst_id:
            raise ValueError(f"output {out.output_id!r} không phải của {analyst_id!r}")
        want = scope_for(analyst_id, price_scope)
        ok = scopes[analyst_id] == want if scopes is not None else _belongs(out, want)
        if not ok:
            raise ValueError(f"output {out.output_id!r} không thuộc phạm vi {price_scope.key!r}")
        if out.as_of > at:
            raise ValueError(f"nhìn trước tương lai: {out.output_id!r} có as_of > {at.isoformat()}")
        if out.is_valid_at(at):
            used[analyst_id] = out
        else:
            excluded[analyst_id] = out.output_id

    manifest = {a: o.output_id for a, o in used.items()}
    flags = {f"EXPIRED_EXCLUDED:{a}" for a in excluded}
    if price_scope.source == "SAMPLE" or any(SAMPLE_DATA in o.quality_flags
                                             for o in used.values()):
        flags.add(SAMPLE_DATA)
    req_expiry = [o.expires_at for a, o in used.items() if a in required]
    return Snapshot(
        snapshot_id=snapshot_id(price_scope, manifest, excluded),
        builder_version=BUILDER_VERSION,
        symbol=price_scope.symbol,
        timeframe=price_scope.timeframe,
        source=price_scope.source,
        feed_id=price_scope.feed,
        event_time=max((o.as_of for o in used.values()), default=at),
        available_at=at,
        expires_at=min(req_expiry) if req_expiry else at,
        analyst_outputs=tuple(used[a] for a in sorted(used)),
        quality_flags=frozenset(flags),
        input_manifest=manifest,
        excluded_inputs=excluded,
    )


def collect(out_store, price_scope: Scope, at: datetime,
            analysts: Iterable[str] = ANALYSTS) -> tuple[dict[str, AnalystOutput],
                                                          dict[str, Scope]]:
    """Output mới nhất đã ghi trước ``at`` cho mỗi analyst (``latest_scoped(known_by=at)``) + phạm
    vi kho đã đọc (lọc theo cột ``symbol / timeframe / source / feed_id``)."""
    _check_price_scope(price_scope)
    found: dict[str, AnalystOutput] = {}
    scopes: dict[str, Scope] = {}
    for a in analysts:
        got = out_store.latest_scoped(a, scope_for(a, price_scope), known_by=at)
        if got is not None:
            found[a], scopes[a] = got.output, got.scope
    return found, scopes


def snapshot_at(out_store, price_scope: Scope, at: datetime, *,
                required: frozenset[str] = REQUIRED) -> Snapshot:
    found, scopes = collect(out_store, price_scope, at)
    return build_snapshot(found, price_scope, at, required=required, scopes=scopes)


@dataclass(frozen=True)
class SnapshotRecord:
    """Phần snapshot được lưu (không chép ``features`` analyst — đã có ở ``analyst_outputs``)."""

    snapshot_id: str
    builder_version: str
    symbol: str
    timeframe: str
    source: str
    feed_id: str
    event_time: datetime
    available_at: datetime
    expires_at: datetime
    quality_flags: frozenset[str]
    input_manifest: Mapping[str, str]
    excluded_inputs: Mapping[str, str]

    @classmethod
    def of(cls, s: Snapshot) -> SnapshotRecord:
        return cls(s.snapshot_id, s.builder_version, s.symbol, s.timeframe, s.source, s.feed_id,
                   s.event_time, s.available_at, s.expires_at, s.quality_flags,
                   dict(s.input_manifest), dict(s.excluded_inputs))

    @property
    def price_scope(self) -> Scope:
        return Scope(self.symbol, self.timeframe, self.source, self.feed_id)


def rebuild(record: SnapshotRecord, out_store, *,
            required: frozenset[str] = REQUIRED) -> Snapshot:
    """Dựng lại snapshot từ manifest đã lưu; phải ra **đúng** snapshot cũ, không thì báo lỗi."""
    if record.builder_version != BUILDER_VERSION:
        raise SnapshotRebuildError(
            f"phiên bản bộ dựng khác: {record.builder_version} ≠ {BUILDER_VERSION}")
    scope = record.price_scope
    latest: dict[str, AnalystOutput] = {}
    scopes: dict[str, Scope] = {}
    for a, oid in {**record.input_manifest, **record.excluded_inputs}.items():
        got = out_store.get_scoped(oid, scope_for(a, scope))
        if got is None:
            raise SnapshotRebuildError(f"không còn output {oid!r} của {a!r}")
        if got.computed_at > record.available_at:
            raise SnapshotRebuildError(f"output {oid!r} được ghi sau available_at")
        latest[a], scopes[a] = got.output, got.scope
    snap = build_snapshot(latest, scope, record.available_at, required=required, scopes=scopes)
    if SnapshotRecord.of(snap) != record:
        raise SnapshotRebuildError(f"tái dựng lệch nội dung: {record.snapshot_id}")
    return snap
