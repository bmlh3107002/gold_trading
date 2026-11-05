from __future__ import annotations

import uuid


def new_id(prefix: str) -> str:
    """Sinh định danh có tiền tố dễ đọc, ví dụ ``mv_3f2a...``."""
    return f"{prefix}_{uuid.uuid4().hex}"
