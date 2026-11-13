# GĐ2 — Event Orchestrator + Làn nhanh (đặc tả 03)

> **Bắt đầu 2026-11-13 song song GĐ1 (DEC-19).** Kế hoạch + checklist: [`docs/ke-hoach/GD2-ke-hoach.md`](../ke-hoach/GD2-ke-hoach.md).
>
> Một phần của bản đồ việc theo giai đoạn (tách từ `CHECKLIST.md` 2026-11-06). Chỉ mục, nguyên tắc và bất biến: [`README.md`](README.md). Trạng thái chung: `PROGRESS.md`. Ghi chú kỹ thuật: `docs/ghi-chu-ky-thuat.md`.


| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| ORC-01 | Runner tối thiểu (polling 15 giây cho Technical) | `[~]` | `analysts/runner.py` — sẽ được thay |
| ORC-02 | Bảng sự kiện → job đúng mô hình: M15 đóng → Technical → Regime → Fusion; CPI/NFP → làn nhanh + Event + News; DXY/yield → Macro; COT → Positioning; output hết hạn → invalidate MarketView | `[ ]` | `orchestrator/` |
| ORC-03 | `jobKey = eventType + subject + eventVersion + analyzerVersion`, hiệu lực đúng một lần | `[x]` | 2026-11-13 (1b): `job_key_for`, khóa chính DB → tạo đúng một lần (kể cả 8 luồng cùng lúc trên Postgres) |
| ORC-04 | Debounce theo loại/symbol/time bucket, không bỏ sự kiện công bố quan trọng | `[ ]` | |
| ORC-05 | Deadline, retry giới hạn, exponential backoff, dead-letter | `[ ]` | |
| ORC-06 | Ghi `correlationId`, nguyên nhân, phiên bản input/output, trạng thái job | `[ ]` | |
| ORC-07 | Invalidate MarketView khi output hết hạn | `[ ]` | |
| ORC-08 | Lưu job bền vững (restart không mất, không chạy lại job đã xong) | `[~]` | 2026-11-13 (1b): bảng chỉ-thêm `orchestrator_jobs` (khóa `job_key`) + `orchestrator_job_attempts` (trạng thái = dòng mới nhất), migration 0014; phần chạy lại / quá deadline ở bước 2 |
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

### Nhật ký GĐ2

- **2026-11-13** — **Bắt đầu GĐ2 (DEC-19).** Người dùng cho làm GĐ2 song song vì GĐ1 chỉ còn kiểm / chờ ngày công bố; Gate GĐ1 chưa đóng và là điều kiện của Gate GĐ2. Lập `docs/ke-hoach/GD2-ke-hoach.md` (6 bước). Ý tưởng chính: sự kiện suy ra từ dữ liệu đã lưu theo `known_at` (replay được, không nhân đôi), nhật ký sự kiện + job chỉ-thêm, làn nhanh chỉ dùng luật (ngưỡng hỏi người dùng ở bước 4).
- **2026-11-13** — **Bước 1a + 1b: nhật ký sự kiện + job (ORC-03, ORC-06 phần lưu, ORC-08 phần lưu).** Thiết kế `docs/thiet-ke/25-event-orchestrator.md`. Migration 0014: `orchestrator_events` (event_id = sha256(loại|chủ thể|phiên bản), duy nhất), `orchestrator_jobs` (job_key khóa chính), `orchestrator_job_attempts` (trạng thái PENDING / RUNNING / SUCCEEDED / FAILED / DEAD / NO_HANDLER / SUPERSEDED, mã lỗi ngắn bắt buộc khi FAILED / DEAD) — cả ba chỉ-thêm. `orchestrator/model.py` (bộ nhớ) + `storage/orchestrator.py` (SQL), thứ tự nhân quả `(known_at, loại, chủ thể, phiên bản)`. Test 36 (bộ nhớ + SQLite): ghi trùng, thứ tự ổn định khi ghi xáo trộn, lọc cửa sổ, sự kiện tương lai ẩn, giờ không múi giờ, giờ New York → UTC, job tạo một lần, nhật ký lần thử cùng giờ giữ thứ tự ghi, mã lỗi chứa URL bị từ chối. **Soát lại** (Postgres 16): 8 luồng ghi cùng sự kiện / job → đúng 1; UPDATE / DELETE bị trigger chặn; ràng buộc chặn trạng thái lạ + FAILED thiếu mã; `alembic check` không lệch; xuống 0013 rồi lên lại.
