"""Lệnh cấm mở lệnh mới có hạn của làn nhanh (GĐ2 bước 4a — FAST-03; DEC-20 câu 5).

Thiết kế: ``docs/thiet-ke/26-lam-nhanh.md``. Tóm tắt:

- Làn nhanh **không gạt công tắc Safety** của người dùng (ACTIVE / PAUSED / HALTED). Nó ghi
  **lệnh cấm có hạn**; Safety cho mở lệnh mới khi công tắc ACTIVE **và** không còn lệnh cấm nào
  có hiệu lực cho nguồn giá của tài khoản. Hành động bảo vệ (đóng lệnh, dời SL) không bị chặn.
- **Chỉ thêm.** ``block_id`` = sha256(loại | phạm vi | nguyên nhân) → cùng nguyên nhân ghi lại
  không sinh lệnh cấm mới (idempotent, replay được).
- **Point-in-time:** lệnh cấm chỉ có hiệu lực từ ``created_at`` (lúc hệ thống ghi / biết). Có
  hiệu lực tại ``t`` khi ``created_at <= t``, ``start_at <= t``, chưa tới ``end_at`` (``None`` =
  tới khi gỡ — dùng cho spread) và chưa có bản ghi gỡ với ``lifted_at <= t``.
"""

from __future__ import annotations

import hashlib
import re
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

ALL = "*"     # phạm vi: mọi nguồn giá / mọi tài khoản
CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


class BlockKind(StrEnum):
    RELEASE = "RELEASE"      # số liệu HIGH vừa công bố (DEC-20 câu 1)
    NEWS = "NEWS"            # thông cáo tiền tệ Fed ngoài lịch (câu 3)
    SPREAD = "SPREAD"        # spread giãn mạnh (câu 2)
    LATENCY = "LATENCY"      # làn nhanh vượt ngân sách độ trễ (câu 4, 2-C09)


def _utc(name: str, v: datetime | None) -> datetime | None:
    if v is None:
        return None
    if v.tzinfo is None or v.utcoffset() is None:
        raise ValueError(f"{name} phải có múi giờ (UTC)")
    return v.astimezone(UTC)


def block_id_for(kind: str, scope: str, cause_ref: str) -> str:
    return hashlib.sha256(f"{kind}|{scope}|{cause_ref}".encode()).hexdigest()[:40]


@dataclass(frozen=True)
class Block:
    kind: BlockKind
    scope: str
    reason_code: str
    start_at: datetime
    end_at: datetime | None
    cause_ref: str
    created_at: datetime
    policy_version: str
    latency_ms: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", BlockKind(self.kind))
        for n in ("start_at", "created_at"):
            object.__setattr__(self, n, _utc(n, getattr(self, n)))
        object.__setattr__(self, "end_at", _utc("end_at", self.end_at))
        if not self.scope or len(self.scope) > 64:
            raise ValueError("phạm vi không hợp lệ")
        if not CODE_RE.match(self.reason_code):
            raise ValueError("reason_code phải là mã ngắn [A-Z0-9_]")
        if not self.cause_ref or len(self.cause_ref) > 256:
            raise ValueError("cause_ref không hợp lệ")
        if self.end_at is not None and self.end_at <= self.start_at:
            raise ValueError("end_at phải sau start_at")
        if self.latency_ms is not None and self.latency_ms < 0:
            raise ValueError("latency_ms < 0")
        if not self.policy_version or len(self.policy_version) > 32:
            raise ValueError("policy_version không hợp lệ")

    @property
    def block_id(self) -> str:
        return block_id_for(self.kind.value, self.scope, self.cause_ref)

    def applies_to(self, feed: str | None) -> bool:
        return self.scope == ALL or (feed is not None and self.scope == feed)


@dataclass(frozen=True)
class Lift:
    block_id: str
    lifted_at: datetime
    reason_code: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "lifted_at", _utc("lifted_at", self.lifted_at))
        if not CODE_RE.match(self.reason_code):
            raise ValueError("reason_code phải là mã ngắn [A-Z0-9_]")


def is_active(b: Block, lift: Lift | None, at: datetime) -> bool:
    return (b.created_at <= at and b.start_at <= at
            and (b.end_at is None or at < b.end_at)
            and (lift is None or lift.lifted_at > at))


class BlockStore:
    """Bản trong bộ nhớ (test / tham chiếu). Bản SQL: ``storage.risk_blocks``."""

    def __init__(self) -> None:
        self._blocks: dict[str, Block] = {}
        self._lifts: dict[str, Lift] = {}
        self._lock = threading.Lock()

    def add(self, b: Block) -> bool:
        with self._lock:
            if b.block_id in self._blocks:
                return False
            self._blocks[b.block_id] = b
            return True

    def lift(self, x: Lift) -> bool:
        """Gỡ một lần (gỡ lại → False). Lệnh cấm chưa có → lỗi."""
        with self._lock:
            if x.block_id not in self._blocks:
                raise ValueError("lệnh cấm chưa có")
            if x.block_id in self._lifts:
                return False
            self._lifts[x.block_id] = x
            return True

    def get(self, block_id: str) -> tuple[Block, Lift | None] | None:
        with self._lock:
            b = self._blocks.get(block_id)
            return None if b is None else (b, self._lifts.get(block_id))

    def active(self, at: datetime, feed: str | None = None) -> list[Block]:
        """Lệnh cấm có hiệu lực tại ``at`` áp cho ``feed`` (``None`` → chỉ lệnh cấm toàn bộ)."""
        at = _utc("at", at)
        with self._lock:
            rows = [b for k, b in self._blocks.items()
                    if b.applies_to(feed) and is_active(b, self._lifts.get(k), at)]
        return sorted(rows, key=lambda b: (b.start_at, b.block_id))

    def open_spread(self, at: datetime) -> list[Block]:
        """Lệnh cấm spread chưa gỡ (đã biết tại ``at``) — làn nhanh xét gỡ."""
        at = _utc("at", at)
        with self._lock:
            return [b for k, b in self._blocks.items() if b.kind is BlockKind.SPREAD
                    and b.created_at <= at and not (k in self._lifts
                                                    and self._lifts[k].lifted_at <= at)]
