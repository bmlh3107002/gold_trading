from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Self

from pydantic import BaseModel, ConfigDict


class Contract(BaseModel):
    """Base cho mọi contract: bất biến và không nhận trường lạ."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    def model_copy(self, *, update: Mapping[str, Any] | None = None, deep: bool = False) -> Self:
        """``model_copy`` mặc định của Pydantic **không kiểm tra lại** → lén tạo được bản ghi sai
        (vd. SL sai chiều, gỡ cờ bắt buộc, trường lạ). Mọi hợp đồng luôn dựng lại qua kiểm tra
        (KN-21 / F-10, đưa bản vá MarketView 2026-11-15 lên lớp gốc). Dựng lại là bản sao sâu,
        nên ``deep`` không còn ý nghĩa."""
        data = self.model_dump()
        data.update(update or {})
        return type(self).model_validate(data)
