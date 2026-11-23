# GĐ6 — Backtest (đặc tả 12)

> **DEC-29 (người dùng 2026-11-17): mở GĐ6 song song** ("đang chạy gấp"; đồng ý sửa code cũ nếu cần). Điều kiện như DEC-28: (1) viết kế hoạch `docs/ke-hoach/GD6-ke-hoach.md` ở phiên chat mới, **người dùng duyệt rồi mới code**; (2) code trên **nhánh riêng tách từ `develop`**, chưa gộp vào `develop` tới sau Gate GĐ1 + GĐ2 (sửa code cũ không được làm đổi bản đang kiểm Gate / replay sau NFP); (3) **không đóng GĐ6 trước GĐ5**; việc kiểm trên máy GĐ1/GĐ2 luôn ưu tiên; (4) việc đầu tiên: kiểm trên máy người dùng MT5 tải được bao nhiêu năm nến M15 XAUUSD (giao thức `protocol-1` cần ≥ 2 năm) — **chỉ xuất file, không nạp vào DB đang chạy** trong đợt đếm 5 ngày.

> Một phần của bản đồ việc theo giai đoạn (tách từ `CHECKLIST.md` 2026-11-06). Chỉ mục, nguyên tắc và bất biến: [`README.md`](README.md). Trạng thái chung: `PROGRESS.md`. Ghi chú kỹ thuật: `docs/ghi-chu-ky-thuat.md`.


| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| BT-01 | Replay theo `available_at` với snapshot + policy/model version lịch sử | `[ ]` | SAMPLE → "không có giá trị đánh giá" |
| BT-02 | Mô phỏng spread thật, slippage (lớn hơn lúc ra tin), commission/swap, độ trễ, fill một phần, giờ thị trường, margin | `[ ]` | |
| BT-03 | Báo cáo: giả định, khoảng dữ liệu, bias còn lại, kết quả theo regime | `[ ]` | |
| BT-04 | Tiêu chí đạt do người dùng duyệt: walk-forward, out-of-sample, số lệnh tối thiểu, drawdown tối đa | `[ ]` | 17/11 tiêu chí T1–T8 đã duyệt + khóa trước khi chạy: `docs/thiet-ke/38-giao-thuc-danh-gia.md` (`protocol-1`); còn: báo cáo GĐ6 đạt |
| MOD-03 | Mode BACKTEST nối với backtest | `[ ]` | |

| Mã | Tình huống | Hành vi bắt buộc | TT |
| --- | --- | --- | --- |
| 6-C01 | Rò rỉ tương lai | Test tự động: thêm dữ liệu tương lai không đổi kết quả quá khứ | `[ ]` |
| 6-C02 | Gap cuối tuần, ngày lễ, tuần lệch DST | Mô phỏng đúng | `[ ]` |
| 6-C03 | Thiếu dữ liệu một đoạn | Không giao dịch trong đoạn thiếu, ghi vào báo cáo | `[ ]` |
| 6-C04 | Quá khớp (quá nhiều tham số / tối ưu trên toàn bộ dữ liệu) | Bắt buộc out-of-sample; cảnh báo | `[ ]` |
| 6-C05 | Kết quả không đạt tiêu chí | Quay lại GĐ5, **không** sang GĐ8 | `[ ]` |

**Gate GĐ6:** báo cáo đạt BT-04 và được người dùng duyệt.

## Nhật ký

- **2026-11-17** — Bản nháp kế hoạch [`docs/ke-hoach/GD6-ke-hoach.md`](../ke-hoach/GD6-ke-hoach.md) (chưa code, chờ người dùng duyệt). Việc đầu: bước 0 — xuất nến XAUUSD M15 (+ H1 / H4 / D1) từ MT5 ra file, đọc thử bằng `import-csv --dry-run` (không mở DB), không nạp. Điểm mở lịch kinh tế lịch sử → Q1 của kế hoạch.
- **2026-11-17** — Người dùng **duyệt cả bản** kế hoạch (Q0 = A). Tiếp: bước 0 trên máy người dùng.
- **2026-11-23** — Người dùng chọn code ngay phần không cần dữ liệu thật (nhánh `gd6-backtest`). Bước 1 xong: thiết kế [`39-backtest.md`](../thiet-ke/39-backtest.md).
