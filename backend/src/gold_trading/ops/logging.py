"""Log JSON có cấu trúc + che bí mật + correlation id (OPS-11, case 0-C18).

- Mỗi dòng log là một JSON: ts, level, logger, msg, correlation_id (+ exc nếu có).
- ``redact()`` che mọi thứ giống bí mật TRƯỚC khi ghi: Bearer token, token Gateway ``gtk_…``,
  JWT, cookie phiên, tham số ``code``/``state``/``password``/``client_secret``..., mật khẩu
  trong URL database, khóa API nguồn ngoài (``api_key``/``registrationkey``/``UserID``/``key``,
  ING-31). Áp dụng cho mọi logger (kể cả thư viện).
- ``register_secret()``: bí mật đã biết giá trị (khóa API nạp từ ``.env``) bị che ở **mọi chỗ**
  xuất hiện, kể cả khi không đứng sau tên tham số nào.
- Access log do middleware của mình ghi (đường dẫn KHÔNG kèm query string), không dùng access
  log của uvicorn.
- ``correlation_id`` lấy từ header ``X-Request-ID`` (nginx đặt) hoặc tự sinh, trả lại trong
  response.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
import time
import uuid
from datetime import UTC, datetime

correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)

_SECRET_KEYS = (
    "password|passwd|pwd|client_secret|secret|refresh_token|id_token|access_token|token|"
    "code|state|session_state|nonce|code_verifier|id_token_hint|authorization|cookie|"
    # ING-31: tên tham số khóa API — FRED api_key, BLS registrationkey, BEA UserID, Census key
    "api_key|apikey|api-key|x-api-key|registrationkey|userid|key"
)
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+"), r"\1 ***"),
    (re.compile(r"gtk_[A-Za-z0-9_-]{8,}"), "gtk_***"),
    (re.compile(r"eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*"), "***jwt***"),
    (re.compile(r"(__Host-gt_session|__Host-gt_login|KEYCLOAK_[A-Z_]+|AUTH_SESSION_ID)"
                r"=[^;\s\"',]+"), r"\1=***"),
    (re.compile(rf"(?i)\b({_SECRET_KEYS})=([^&\s\"',;]+)"), r"\1=***"),
    (re.compile(rf"(?i)([\"']?(?:{_SECRET_KEYS})[\"']?\s*[:=]\s*)[\"'][^\"']*[\"']"),
     r"\1'***'"),
    (re.compile(r"(?i)(postgres(?:ql)?(?:\+\w+)?://[^:/\s@]+:)[^@\s]+@"), r"\1***@"),
]


_KNOWN_SECRETS: set[str] = set()
_MIN_KNOWN_LEN = 8  # giá trị quá ngắn dễ trùng chữ thường → không đăng ký (bị từ chối từ trước)


def register_secret(value: str) -> None:
    """Đăng ký giá trị bí mật để che ở mọi chỗ trong log (ING-31)."""
    if len(value) < _MIN_KNOWN_LEN:
        raise ValueError("bí mật quá ngắn để che an toàn")
    _KNOWN_SECRETS.add(value)


def redact(text: str) -> str:
    for secret in sorted(_KNOWN_SECRETS, key=len, reverse=True):
        if secret in text:
            text = text.replace(secret, "***")
    for pat, repl in _PATTERNS:
        text = pat.sub(repl, text)
    return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        try:
            msg = record.getMessage()
        except Exception:  # args không khớp format: vẫn ghi được, không làm sập
            msg = str(record.msg)
        out = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(msg),
            "correlation_id": getattr(record, "correlation_id", None) or correlation_id.get(),
        }
        for key in ("method", "path", "status", "duration_ms"):
            if hasattr(record, key):
                out[key] = getattr(record, key)
        if record.exc_info:
            out["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(out, ensure_ascii=False)


def configure_logging(level: str = "INFO", stream=None) -> logging.Handler:
    """Một handler JSON duy nhất ở root; logger của uvicorn đi qua root."""
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
    logging.getLogger("uvicorn.access").disabled = True  # dùng access log của middleware
    return handler


_RID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
access_log = logging.getLogger("gold_trading.access")


class CorrelationMiddleware:
    """ASGI: gắn correlation id cho request, ghi access log không có query string."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        given = None
        for k, v in scope.get("headers", []):
            if k == b"x-request-id":
                given = v.decode("latin-1")
                break
        rid = given if given and _RID.match(given) else uuid.uuid4().hex
        token = correlation_id.set(rid)
        started = time.perf_counter()
        status = {"code": 500}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
                message.setdefault("headers", [])
                message["headers"] = [*message["headers"], (b"x-request-id", rid.encode())]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            path = scope.get("path", "")
            if path != "/api/health":  # healthcheck 10 s/lần: không làm ngập log
                access_log.info(
                    "%s %s %s", scope.get("method"), path, status["code"],
                    extra={"method": scope.get("method"), "path": path,
                           "status": status["code"],
                           "duration_ms": round((time.perf_counter() - started) * 1000, 1)},
                )
            correlation_id.reset(token)
