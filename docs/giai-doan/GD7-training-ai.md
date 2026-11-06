# GĐ7 — Training + AI Service + kiểm soát mô hình (đặc tả 05, 11)

> Một phần của bản đồ việc theo giai đoạn (tách từ `CHECKLIST.md` 2026-11-06). Chỉ mục, nguyên tắc và bất biến: [`README.md`](README.md). Trạng thái chung: `PROGRESS.md`. Ghi chú kỹ thuật: `docs/ghi-chu-ky-thuat.md`.


Mục tiêu: thêm mô hình (LightGBM `pUp/pDown`, Regime HMM/classifier, Fusion meta-model) **chỉ khi** chúng tốt hơn bản luật sau chi phí. Nếu không tốt hơn, giữ bản luật (người dùng quyết định — DEC-10).

| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| DEC-10 | Có làm/giữ mô hình ML không, sau khi so với bản luật | `[!]` | |
| TRN-01 | Dataset point-in-time có phiên bản, nhãn không rò rỉ | `[ ]` | |
| TRN-02 | Train/tune walk-forward | `[ ]` | |
| TRN-03 | Đánh giá cả dự báo và tác động giao dịch sau chi phí | `[ ]` | ← BT |
| TRN-04 | Model registry: code version, data manifest, metrics, giới hạn, người duyệt | `[ ]` | |
| AIS-01 | AI Service phục vụ mô hình đã duyệt | `[ ]` | |
| AIS-02 | Ghi `modelVersion` vào mọi output dùng mô hình | `[ ]` | |
| TEC-08 | LightGBM → `pUp/pDown` (chỉ gọi là xác suất sau hiệu chỉnh) | `[ ]` | |
| REG-03 | Regime bằng HMM/classifier | `[ ]` | |
| FUS-02 | Fusion meta-model | `[ ]` | |
| MQC-01 | Calibration, Brier/log loss, drift PSI, tỷ lệ stale; shadow trước, ngưỡng rollback | `[ ]` | |

| Mã | Tình huống | Hành vi bắt buộc | TT |
| --- | --- | --- | --- |
| 7-C01 | Mô hình chưa hiệu chỉnh | Không gọi là xác suất, không dùng cho quyết định | `[ ]` |
| 7-C02 | Drift vượt ngưỡng | Cảnh báo, quay về bản luật/phiên bản trước | `[ ]` |
| 7-C03 | Không tái tạo được artifact | Không được phục vụ | `[ ]` |

**Gate GĐ7:** mô hình được duyệt hơn bản luật trên out-of-sample sau chi phí và đã chạy shadow; hoặc người dùng quyết định không dùng ML (DEC-10).
