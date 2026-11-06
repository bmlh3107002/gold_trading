# GĐ9 — Kết nối lệnh MT5 demo (đặc tả 09)

> Một phần của bản đồ việc theo giai đoạn (tách từ `CHECKLIST.md` 2026-11-06). Chỉ mục, nguyên tắc và bất biến: [`README.md`](README.md). Trạng thái chung: `PROGRESS.md`. Ghi chú kỹ thuật: `docs/ghi-chu-ky-thuat.md`.


| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| GW-10 | **Thành phần đặt lệnh riêng** (gửi/sửa/hủy, map request–ticket, reason code chuẩn, magic number) | `[ ]` | Package mới, tách `mt5_gateway`; bắt buộc MT-17, MT-18 (định tuyến theo liên kết + kiểm login/server trước mọi thao tác); review riêng; mTLS/token |
| EXE-05 | `UNKNOWN` → truy vấn MT5 trước, không retry mù | `[ ]` | |
| LED-03 | Đối soát định kỳ order/deal/position/equity/margin với MT5 | `[ ]` | Lệch nghiêm trọng → HALT + incident |
| SAF-07 | Hành động Safety thật: hủy lệnh chờ, giảm/đóng vị thế, xác nhận từ MT5 | `[ ]` | |
| GEA-01 | Bản nháp Guardian EA | `[~]` | `guardian_ea/GuardianEA.mq5` — chưa biên dịch |
| GEA-02 | Biên dịch, test trên MT5 demo | `[ ]` | |
| GEA-03 | Ngưỡng equity cứng; đóng/hạn chế khi backend mất kết nối | `[ ]` | |
| GEA-04 | Diễn tập định kỳ | `[ ]` | |
| GW-11 | Lịch giao dịch tự động từ MT5 (nếu có cách đọc) | `[ ]` | Hiện chép tay |
| OPS-10 | Chaos test: mất mạng, restart, gửi trùng | `[ ]` | |

| Mã | Tình huống | Hành vi bắt buộc | TT |
| --- | --- | --- | --- |
| 9-C01 | Mất ACK sau khi MT5 đã nhận lệnh | Truy vấn, không tạo lệnh thứ hai | `[ ]` |
| 9-C02 | Requote / market closed / bị từ chối (mã lỗi MT5) | Reason code chuẩn, không retry mù | `[ ]` |
| 9-C03 | Khớp một phần | Ledger cập nhật đúng | `[ ]` |
| 9-C04 | Terminal/Gateway restart giữa lệnh | Đối soát lại trước khi làm tiếp | `[ ]` |
| 9-C05 | **Người dùng tự đặt lệnh tay** trên MT5 | Nhận diện bằng magic number; tính vào exposure; không tự quản lý lệnh lạ | `[ ]` |
| 9-C06 | Ledger lệch MT5 | HALT, khóa lệnh mới, incident | `[ ]` |
| 9-C07 | Backend chết khi đang có vị thế | Guardian EA bảo vệ | `[ ]` |

**Gate GĐ9:** ≥ 2 tuần trên MT5 demo với đối soát sạch; diễn tập kill switch và Guardian đạt. Bao gồm MT-17, MT-18 và case MT-C08..C14: diễn tập đổi tài khoản trên terminal giữa chừng → mọi thao tác bị chặn, không lệnh nào vào MT5 khác; hai người khác login cùng broker không lẫn lệnh.
