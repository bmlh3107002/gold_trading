# 11 — Training và quản trị mô hình

## Training offline

Training sử dụng dữ liệu point-in-time đã version hóa và kết quả giao dịch đã đối soát. Mục tiêu là tạo artifact (feature spec, weights/model, calibration, metrics), đăng ký vào model registry và chỉ phục vụ sau khi đạt tiêu chí đánh giá.

## Quy trình phát hành

1. Xác định dataset, khoảng thời gian, source revisions và nhãn không rò rỉ tương lai.
2. Train/tune theo walk-forward; tách train/validation/test theo thời gian.
3. Đánh giá dự báo lẫn tác động giao dịch sau spread/slippage/latency.
4. Đăng ký artifact với code version, data manifest, metrics, limitations và người phê duyệt.
5. Chạy shadow; sau đó canary có giới hạn rủi ro; có điều kiện rollback rõ ràng.

## Kiểm soát

- Không train online trực tiếp từ PnL Live để tự động sửa model.
- Calibration, drift PSI, tỷ lệ missing, hiệu năng theo regime và degradation phải có alert.
- LLM/FinBERT cần version prompt/model, bộ đánh giá chống hallucination/prompt injection và kiểm soát chi phí/timeout.
- Reproducibility: cùng code + config + manifest phải dựng lại được artifact hoặc giải thích sai khác.
