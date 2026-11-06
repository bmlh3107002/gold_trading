# GĐ10 — SHADOW → LIVE (đặc tả 12)

> Một phần của bản đồ việc theo giai đoạn (tách từ `CHECKLIST.md` 2026-11-06). Chỉ mục, nguyên tắc và bất biến: [`README.md`](README.md). Trạng thái chung: `PROGRESS.md`. Ghi chú kỹ thuật: `docs/ghi-chu-ky-thuat.md`.


| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| LIVE-01 | Đủ 7 mục `LIVE_CHECKLIST` (`reconciliation_clean`, `required_sources_healthy`, `kill_switch_tested`, `guardian_ea_tested`, `risk_limits_approved`, `model_versions_approved`, `on_call_ready`) | `[ ]` | `modes/manager.py` |
| LIVE-02 | SHADOW trên tài khoản thật (không gửi lệnh) và so với paper | `[ ]` | |
| LIVE-03 | LIVE canary: khối lượng nhỏ nhất, hạn mức thấp, điều kiện rollback rõ | `[ ]` | |
| OPS-13 | Runbook đầy đủ + người trực + quyền dừng khẩn | `[ ]` | |

| Mã | Tình huống | Hành vi bắt buộc | TT |
| --- | --- | --- | --- |
| 10-C01 | Mở khóa LIVE thiếu mục checklist / cùng một người duyệt | Từ chối | `[x]` |
| 10-C02 | Restart khi đang LIVE | Về PAPER | `[x]` |
| 10-C03 | Vi phạm hạn mức canary | Tự HALT | `[ ]` |

**Gate GĐ10:** người dùng phê duyệt hai bước; mọi mục "Checklist trước LIVE" ở `docs/huong-dan-chuc-nang/12-van-hanh-kiem-thu.md` đạt.
