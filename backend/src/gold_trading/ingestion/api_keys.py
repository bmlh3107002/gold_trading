"""Khóa API của nguồn ngoài (ING-31, DEC-07).

Quy tắc (``docs/thiet-ke/10-nguon-ngoai.md`` mục 3):

- Khóa **chỉ** đọc từ biến môi trường (do ``docker compose`` lấy từ ``.env`` trên máy người
  dùng). ``.env`` không bao giờ commit (``.gitignore``; test quét file đã commit).
- Giá trị khóa nằm trong ``ApiKey``: in / ``repr`` / f-string / JSON đều ra ``***``; chỉ
  ``reveal()`` (lúc dựng request) mới lấy giá trị thật. Không tuần tự hóa được (pickle).
- Mỗi khóa nạp vào được đăng ký với bộ che log → xuất hiện ở đâu trong log cũng thành ``***``.
- Thiếu khóa → ``KEY_MISSING``; khóa sai định dạng (dán thừa dấu nháy, khoảng trắng giữa, chữ
  lạ) → ``KEY_INVALID``. Cả hai là lỗi "chết" → nguồn MISSING ngay (ING-30), không gọi nguồn.
- Lỗi khi gọi nguồn chỉ đổi thành **mã ngắn** (``error_code_for_*``), không bao giờ dùng thông
  điệp lỗi gốc (thường chứa URL kèm khóa).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from gold_trading.ops.logging import register_secret

# Nguồn → tên biến môi trường. Thêm nguồn cần khóa: thêm một dòng ở đây + docker-compose.
KEY_ENV: dict[str, str] = {
    "fred": "GT_FRED_API_KEY",
    "bls": "GT_BLS_API_KEY",
    "bea": "GT_BEA_API_KEY",
}

# Không ép định dạng riêng của từng nhà cung cấp (đoán sai thì chặn nhầm khóa đúng); chỉ chặn
# những gì chắc chắn sai: khoảng trắng / dấu nháy / ký tự lạ, quá ngắn, quá dài.
_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


class ApiKey:
    """Giữ giá trị khóa; không bao giờ tự lộ ra khi in hay tuần tự hóa."""

    __slots__ = ("_source", "_value")

    def __init__(self, source: str, value: str) -> None:
        self._source = source
        self._value = value

    @property
    def source(self) -> str:
        return self._source

    def reveal(self) -> str:
        """Giá trị thật — chỉ dùng lúc dựng request tới nguồn."""
        return self._value

    def __repr__(self) -> str:
        return f"ApiKey({self._source}, ***)"

    __str__ = __repr__

    def __format__(self, spec: str) -> str:
        return repr(self)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ApiKey) and (other._source, other._value) == (
            self._source, self._value)

    def __hash__(self) -> int:
        return hash((self._source, self._value))

    def __reduce__(self):
        raise TypeError("ApiKey không được tuần tự hóa (ING-31)")


@dataclass(frozen=True)
class KeyLookup:
    """Kết quả nạp khóa của một nguồn: có khóa, hoặc mã lỗi (KEY_MISSING / KEY_INVALID)."""

    source: str
    key: ApiKey | None
    error_code: str | None

    @property
    def ok(self) -> bool:
        return self.key is not None


def load_api_key(source: str, env: Mapping[str, str]) -> KeyLookup:
    """Đọc khóa của ``source`` từ ``env`` (thường là ``os.environ``). Không bao giờ ném lỗi kèm
    giá trị khóa."""
    var = KEY_ENV.get(source)
    if var is None:
        raise ValueError(f"nguồn {source!r} không khai báo khóa trong KEY_ENV")
    raw = env.get(var)
    value = (raw or "").strip()
    if not value:
        return KeyLookup(source, None, "KEY_MISSING")
    if not _KEY_RE.match(value):
        # Giá trị sai vẫn có thể là khóa thật dán thừa ký tự → vẫn đăng ký che log.
        if len(value) >= 8:
            register_secret(value)
        return KeyLookup(source, None, "KEY_INVALID")
    register_secret(value)
    return KeyLookup(source, ApiKey(source, value), None)


def load_api_keys(env: Mapping[str, str]) -> dict[str, KeyLookup]:
    """Nạp khóa mọi nguồn đã khai báo (thiếu khóa không làm hỏng nguồn khác)."""
    return {s: load_api_key(s, env) for s in KEY_ENV}


def describe_keys(lookups: Mapping[str, KeyLookup]) -> dict[str, str]:
    """Trạng thái để in log / hiển thị: ``CONFIGURED`` / ``KEY_MISSING`` / ``KEY_INVALID`` —
    không bao giờ có giá trị, độ dài hay ký tự nào của khóa."""
    return {s: ("CONFIGURED" if lk.ok else lk.error_code or "KEY_MISSING")
            for s, lk in sorted(lookups.items())}


# --- Mã lỗi an toàn (không bao giờ chứa thông điệp gốc) ---

def error_code_for_http(status: int) -> str:
    """HTTP status → mã ngắn cho nhật ký lần kiểm (ING-30). Nguồn nào báo khóa sai bằng mã khác
    (vd. 400 kèm thông điệp) thì bộ nạp của nguồn đó tự đổi sang ``AUTH_FAILED``."""
    if status == 401:
        return "AUTH_FAILED"
    if status == 403:
        return "FORBIDDEN"
    if status == 404:
        return "NOT_FOUND"
    if status == 429:
        return "RATE_LIMITED"
    if 500 <= status <= 599:
        return f"HTTP_{status}"
    if 400 <= status <= 499:
        return f"HTTP_{status}"
    return "HTTP_UNEXPECTED"


_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def error_code_for_exception(exc: BaseException) -> str:
    """Ngoại lệ → mã ngắn chỉ dựa vào **loại** lỗi (tên lớp), không đọc thông điệp."""
    if isinstance(exc, TimeoutError) or "Timeout" in type(exc).__name__:
        return "TIMEOUT"
    if isinstance(exc, ConnectionError) or type(exc).__name__ in ("ConnectError",
                                                                   "NetworkError"):
        return "NETWORK_ERROR"
    name = _CAMEL.sub("_", type(exc).__name__).upper()
    name = re.sub(r"[^A-Z0-9_]", "_", name).strip("_") or "ERROR"
    if not name[0].isalpha():
        name = "E_" + name
    return name[:64]
