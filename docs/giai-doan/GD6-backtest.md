# GĐ6 — Backtest (đặc tả 12)

> Một phần của bản đồ việc theo giai đoạn (tách từ `CHECKLIST.md` 2026-11-06). Chỉ mục, nguyên tắc và bất biến: [`README.md`](README.md). Trạng thái chung: `PROGRESS.md`. Ghi chú kỹ thuật: `docs/ghi-chu-ky-thuat.md`.


| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| BT-01 | Replay theo `available_at` với snapshot + policy/model version lịch sử | `[ ]` | SAMPLE → "không có giá trị đánh giá" |
| BT-02 | Mô phỏng spread thật, slippage (lớn hơn lúc ra tin), commission/swap, độ trễ, fill một phần, giờ thị trường, margin | `[ ]` | |
| BT-03 | Báo cáo: giả định, khoảng dữ liệu, bias còn lại, kết quả theo regime | `[ ]` | |
| BT-04 | Tiêu chí đạt do người dùng duyệt: walk-forward, out-of-sample, số lệnh tối thiểu, drawdown tối đa | `[ ]` | |
| MOD-03 | Mode BACKTEST nối với backtest | `[ ]` | |

| Mã | Tình huống | Hành vi bắt buộc | TT |
| --- | --- | --- | --- |
| 6-C01 | Rò rỉ tương lai | Test tự động: thêm dữ liệu tương lai không đổi kết quả quá khứ | `[ ]` |
| 6-C02 | Gap cuối tuần, ngày lễ, tuần lệch DST | Mô phỏng đúng | `[ ]` |
| 6-C03 | Thiếu dữ liệu một đoạn | Không giao dịch trong đoạn thiếu, ghi vào báo cáo | `[ ]` |
| 6-C04 | Quá khớp (quá nhiều tham số / tối ưu trên toàn bộ dữ liệu) | Bắt buộc out-of-sample; cảnh báo | `[ ]` |
| 6-C05 | Kết quả không đạt tiêu chí | Quay lại GĐ5, **không** sang GĐ8 | `[ ]` |

**Gate GĐ6:** báo cáo đạt BT-04 và được người dùng duyệt.
