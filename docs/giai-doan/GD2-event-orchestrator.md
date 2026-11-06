# GĐ2 — Event Orchestrator + Làn nhanh (đặc tả 03)

> Một phần của bản đồ việc theo giai đoạn (tách từ `CHECKLIST.md` 2026-11-06). Chỉ mục, nguyên tắc và bất biến: [`README.md`](README.md). Trạng thái chung: `PROGRESS.md`. Ghi chú kỹ thuật: `docs/ghi-chu-ky-thuat.md`.


| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| ORC-01 | Runner tối thiểu (polling 15 giây cho Technical) | `[~]` | `analysts/runner.py` — sẽ được thay |
| ORC-02 | Bảng sự kiện → job đúng mô hình: M15 đóng → Technical → Regime → Fusion; CPI/NFP → làn nhanh + Event + News; DXY/yield → Macro; COT → Positioning; output hết hạn → invalidate MarketView | `[ ]` | `orchestrator/` |
| ORC-03 | `jobKey = eventType + subject + eventVersion + analyzerVersion`, hiệu lực đúng một lần | `[ ]` | |
| ORC-04 | Debounce theo loại/symbol/time bucket, không bỏ sự kiện công bố quan trọng | `[ ]` | |
| ORC-05 | Deadline, retry giới hạn, exponential backoff, dead-letter | `[ ]` | |
| ORC-06 | Ghi `correlationId`, nguyên nhân, phiên bản input/output, trạng thái job | `[ ]` | |
| ORC-07 | Invalidate MarketView khi output hết hạn | `[ ]` | |
| ORC-08 | Lưu job bền vững (restart không mất, không chạy lại job đã xong) | `[ ]` | |
| DSH-08 | Hiển thị trạng thái pipeline/job, dead-letter | `[ ]` | |
| FAST-01 | Làn nhanh kích hoạt khi: CPI/NFP vừa ra, tin nóng cấp cao, spread giãn mạnh, bất ngờ so dự báo | `[ ]` | |
| FAST-02 | Xử lý bằng luật (+ FinBERT nếu có), **không gọi LLM nặng**; ngân sách độ trễ tính bằng giây | `[ ]` | |
| FAST-03 | Kết quả: cập nhật `riskFlags`, chặn lệnh 10–15 phút, giảm confidence, đi thẳng Safety (bỏ qua Fusion) | `[ ]` | |

| Mã | Tình huống | Hành vi bắt buộc | TT |
| --- | --- | --- | --- |
| 2-C01 | Cùng sự kiện tới nhiều lần | Một output | `[ ]` |
| 2-C02 | Sự kiện tới sai thứ tự | Xử lý theo thứ tự nhân quả, ổn định khi replay | `[ ]` |
| 2-C03 | Dồn dập sự kiện | Debounce, không bỏ sự kiện quan trọng | `[ ]` |
| 2-C04 | Analyst lỗi / quá hạn deadline | Retry giới hạn → dead-letter, nguồn coi là MISSING, không dùng output cũ quá hạn | `[ ]` |
| 2-C05 | Restart giữa lúc chạy job | Tiếp tục hoặc chạy lại an toàn, không nhân đôi | `[ ]` |
| 2-C06 | Output hết hạn mà không tính lại được | MarketView bị invalidate → không có tín hiệu | `[ ]` |
| 2-C07 | Sự kiện xảy ra khi thị trường đóng | Vẫn xử lý; cờ áp dụng khi mở cửa | `[ ]` |
| 2-C08 | Hai công bố cùng phút | Một cửa sổ chặn gộp | `[ ]` |
| 2-C09 | Làn nhanh vượt ngân sách độ trễ | Cảnh báo; Safety mặc định chặn tới khi xử lý xong | `[ ]` |

**Gate GĐ2:** replay event log ghi lại từ GĐ1 cho kết quả giống hệt; không nhân đôi output; đo được độ trễ làn nhanh trên một lần công bố CPI/NFP đã ghi, nằm trong ngân sách.
