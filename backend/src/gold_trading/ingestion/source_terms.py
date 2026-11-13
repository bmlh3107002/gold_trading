"""Giấy phép / điều khoản sử dụng từng nguồn ngoài (ING-32, DEC-02, DEC-05).

Danh sách đầy đủ + bằng chứng + ngày kiểm: ``docs/thiet-ke/11-dieu-khoan-nguon.md``.

Quy tắc: một nguồn chỉ **bật** được (``SourceSpec.enabled``) khi điều khoản của nhà cung cấp
đã được đọc nguyên văn và ghi ``VERIFIED``. ``NEEDS_REVIEW`` (chưa đọc nguyên văn) và
``BLOCKED`` (điều khoản có điều cấm / chưa rõ có cho tải tự động) → ``SourceRegistry`` từ chối
bật. Nguồn tắt thì được khai báo trước. Hướng an toàn: thiếu bằng chứng → không bật.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class TermsStatus(StrEnum):
    VERIFIED = "VERIFIED"          # đã đọc nguyên văn, cho phép dùng như dự định
    NEEDS_REVIEW = "NEEDS_REVIEW"  # mới có bằng chứng gián tiếp, phải đọc nguyên văn trước khi bật
    BLOCKED = "BLOCKED"            # điều khoản cấm / có dấu hiệu cấm tải tự động


@dataclass(frozen=True)
class SourceTerms:
    provider: str
    status: TermsStatus
    checked_on: date
    doc_anchor: str  # mục trong docs/thiet-ke/11-dieu-khoan-nguon.md

    def __post_init__(self) -> None:
        if not isinstance(self.status, TermsStatus):
            object.__setattr__(self, "status", TermsStatus(self.status))


_CHECKED = date(2026, 11, 13)


def _t(provider: str, status: TermsStatus) -> SourceTerms:
    return SourceTerms(provider, status, _CHECKED, f"#{provider}")


# Đổi trạng thái = sửa file thiết kế (bằng chứng, ngày) + đây, cùng một commit.
SOURCE_TERMS: dict[str, SourceTerms] = {t.provider: t for t in (
    _t("fred", TermsStatus.BLOCKED),     # nguyên văn 2026-11-13: cấm lưu vào DB, cấm dùng cho AI
    _t("bls", TermsStatus.VERIFIED),     # 2026-11-13: DEC-18 (người dùng chấp nhận rủi ro);
                                         # public domain, ghi nguồn BLS
    _t("bea", TermsStatus.VERIFIED),     # nguyên văn 2026-11-13; phải hiện câu ghi nguồn BEA
    _t("census", TermsStatus.VERIFIED),  # nguyên văn 2026-11-13; phải hiện câu ghi nguồn Census
    _t("dol", TermsStatus.VERIFIED),     # nguyên văn 2026-11-13: public domain; chỉ bản tin PDF
    _t("fed", TermsStatus.VERIFIED),     # nguyên văn 2026-11-13: public domain, ghi nguồn Board
    _t("treasury", TermsStatus.VERIFIED),  # 2026-11-13: không thấy điều cấm; DEC-18 người dùng
                                           # chấp nhận rủi ro điều khoản (dự án cá nhân)
    _t("cftc", TermsStatus.VERIFIED),    # nguyên văn 2026-11-13 (máy người dùng): public domain
    _t("gld", TermsStatus.BLOCKED),      # nguyên văn 2026-11-13: cấm tự tải, cấm dùng kiếm tiền
    _t("iau", TermsStatus.BLOCKED),
)}


def terms_problem(provider: str, terms: dict[str, SourceTerms]) -> str | None:
    """Lý do không được bật nguồn của ``provider``, hoặc None nếu được bật."""
    t = terms.get(provider)
    if t is None:
        return f"chưa ghi điều khoản cho nhà cung cấp {provider!r} (ING-32)"
    if t.status is not TermsStatus.VERIFIED:
        return f"điều khoản {provider!r} đang {t.status.value} (ING-32)"
    return None
