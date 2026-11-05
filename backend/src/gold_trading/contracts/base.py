from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Contract(BaseModel):
    """Base cho mọi contract: bất biến và không nhận trường lạ."""

    model_config = ConfigDict(frozen=True, extra="forbid")
