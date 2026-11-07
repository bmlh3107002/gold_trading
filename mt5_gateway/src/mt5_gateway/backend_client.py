"""Gửi dữ liệu tới backend qua HTTP (thư viện chuẩn, không cần cài thêm)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class BackendError(RuntimeError):
    def __init__(self, status: int | None, detail: str) -> None:
        super().__init__(f"HTTP {status}: {detail}" if status else detail)
        self.status = status
        self.detail = detail


class BackendClient:
    def __init__(self, base_url: str, token: str, timeout_s: float = 20.0) -> None:
        self.base = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout_s

    def _call(self, method: str, path: str, body: Any | None = None, auth: bool = True) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if auth:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read()).get("detail", e.reason)
            except Exception:
                detail = str(e.reason)
            raise BackendError(e.code, str(detail)) from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise BackendError(None, f"Không kết nối được backend tại {self.base}: {e}") from e

    def health(self) -> Any:
        return self._call("GET", "/api/health", auth=False)

    def post_candles(
        self,
        *,
        symbol: str,
        bars: list[dict[str, Any]],
        backfill: bool,
        gateway_id: str,
        dry_run: bool = False,
        timeframe: str = "M15",
        server_tz: str | None = None,
    ) -> Any:
        q = "?dry_run=true" if dry_run else ""
        body: dict[str, Any] = {
            "symbol": symbol,
            "timeframe": timeframe,
            "backfill": backfill,
            "gateway_id": gateway_id,
            "bars": bars,
        }
        if server_tz:
            body["server_tz"] = server_tz  # bắt buộc với H4/D1 (backend căn theo giờ server)
        return self._call("POST", f"/api/ingest/mt5/candles{q}", body)

    def heartbeat(self, payload: dict[str, Any]) -> Any:
        return self._call("POST", "/api/ingest/mt5/heartbeat", payload)
