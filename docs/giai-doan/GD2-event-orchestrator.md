# GĐ2 — Event Orchestrator + Làn nhanh (đặc tả 03)

> **Bắt đầu 2026-11-13 song song GĐ1 (DEC-19).** Kế hoạch + checklist: [`docs/ke-hoach/GD2-ke-hoach.md`](../ke-hoach/GD2-ke-hoach.md).
>
> Một phần của bản đồ việc theo giai đoạn (tách từ `CHECKLIST.md` 2026-11-06). Chỉ mục, nguyên tắc và bất biến: [`README.md`](README.md). Trạng thái chung: `PROGRESS.md`. Ghi chú kỹ thuật: `docs/ghi-chu-ky-thuat.md`.


| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| ORC-01 | Runner tối thiểu (polling 15 giây cho Technical) | `[x]` | 2026-11-14 (bước 3): thay bằng `orchestrator/runner.py` (nến M15 đóng → job TECHNICAL); vòng cũ còn làm đường lui `GT_ORCHESTRATOR=0`; chờ kiểm trên máy |
| ORC-02 | Bảng sự kiện → job đúng mô hình: M15 đóng → Technical → Regime → Fusion; CPI/NFP → làn nhanh + Event + News; DXY/yield → Macro; COT → Positioning; output hết hạn → invalidate MarketView | `[~]` | 2026-11-14 (bước 1c + 2): sự kiện từ dữ liệu + bảng định tuyến `routes_for` (`orchestrator/dispatcher.py`, `docs/thiet-ke/25-…` mục 5); Fusion / invalidate MarketView ở bước 3 / GĐ4 |
| ORC-03 | `jobKey = eventType + subject + eventVersion + analyzerVersion`, hiệu lực đúng một lần | `[x]` | 2026-11-13 (1b): `job_key_for`, khóa chính DB → tạo đúng một lần (kể cả 8 luồng cùng lúc trên Postgres) |
| ORC-04 | Debounce theo loại/symbol/time bucket, không bỏ sự kiện công bố quan trọng | `[x]` | 2026-11-14: cùng loại job + chủ thể, sự kiện mới hơn → `SUPERSEDED`; công bố / lịch / tin không bao giờ |
| ORC-05 | Deadline, retry giới hạn, exponential backoff, dead-letter | `[x]` | 2026-11-14: deadline 30 s, 3 lần, backoff 10 s × 2^(n−1) trần 5 phút, `DEAD`; quá deadline không dùng kết quả |
| ORC-06 | Ghi `correlationId`, nguyên nhân, phiên bản input/output, trạng thái job | `[x]` | 2026-11-14: `correlation_id` = sự kiện gốc, nguyên nhân = sự kiện (`event_id`, loại, chủ thể, phiên bản), phiên bản bộ xử lý trong `job_key`, `output_ref`, nhật ký trạng thái |
| ORC-07 | Invalidate MarketView khi output hết hạn | `[~]` | 2026-11-14 (bước 3): sự kiện `OUTPUT_EXPIRED` (hết hạn mà chưa có kết quả mới) → job `INVALIDATE_MARKETVIEW` + tính lại; bộ xử lý invalidate có khi có MarketView (GĐ4) |
| ORC-08 | Lưu job bền vững (restart không mất, không chạy lại job đã xong) | `[x]` | 2026-11-13 (1b): bảng chỉ-thêm `orchestrator_jobs` (khóa `job_key`) + `orchestrator_job_attempts` (trạng thái = dòng mới nhất), migration 0014; phần chạy lại / quá deadline ở bước 2 |
| DSH-08 | Hiển thị trạng thái pipeline/job, dead-letter | `[ ]` | |
| FAST-01 | Làn nhanh kích hoạt khi: CPI/NFP vừa ra, tin nóng cấp cao, spread giãn mạnh, bất ngờ so dự báo | `[ ]` | |
| FAST-02 | Xử lý bằng luật (+ FinBERT nếu có), **không gọi LLM nặng**; ngân sách độ trễ tính bằng giây | `[ ]` | |
| FAST-03 | Kết quả: cập nhật `riskFlags`, chặn lệnh 10–15 phút, giảm confidence, đi thẳng Safety (bỏ qua Fusion) | `[ ]` | |

| Mã | Tình huống | Hành vi bắt buộc | TT |
| --- | --- | --- | --- |
| 2-C01 | Cùng sự kiện tới nhiều lần | Một output | `[x]` 2026-11-14 (bước 2): một job, một lần thành công; 2026-11-13 (1b, 1c): một sự kiện (khóa `event_id`), một job (`job_key`); output ở bước 2–3 |
| 2-C02 | Sự kiện tới sai thứ tự | Xử lý theo thứ tự nhân quả, ổn định khi replay | `[x]` 2026-11-14 (bước 2): chạy theo thứ tự nhân quả; 2026-11-13 (1b, 1c): thứ tự `(known_at, loại, chủ thể, phiên bản)` không phụ thuộc thứ tự ghi; quét chia nhỏ = một lần replay; xử lý theo thứ tự ở bước 2 |
| 2-C03 | Dồn dập sự kiện | Debounce, không bỏ sự kiện quan trọng | `[x]` 2026-11-14: nạp bù 20 nến → 1 lần Technical; 20 công bố → 20 lần |
| 2-C04 | Analyst lỗi / quá hạn deadline | Retry giới hạn → dead-letter, nguồn coi là MISSING, không dùng output cũ quá hạn | `[~]` 2026-11-14: retry giới hạn → `DEAD`, quá deadline không dùng kết quả; phía dùng output (coi MISSING, TTL) ở GĐ4 Quality Gate |
| 2-C05 | Restart giữa lúc chạy job | Tiếp tục hoặc chạy lại an toàn, không nhân đôi | `[x]` 2026-11-14: `RUNNING` chưa quá deadline → chờ; quá → `DEADLINE_EXCEEDED` rồi thử lại; job xong không chạy lại |
| 2-C06 | Output hết hạn mà không tính lại được | MarketView bị invalidate → không có tín hiệu | `[~]` 2026-11-14: sự kiện + job invalidate + tính lại có test; chặn tín hiệu thật khi có MarketView / Fusion (GĐ4) |
| 2-C07 | Sự kiện xảy ra khi thị trường đóng | Vẫn xử lý; cờ áp dụng khi mở cửa | `[ ]` |
| 2-C08 | Hai công bố cùng phút | Một cửa sổ chặn gộp | `[ ]` |
| 2-C09 | Làn nhanh vượt ngân sách độ trễ | Cảnh báo; Safety mặc định chặn tới khi xử lý xong | `[ ]` |

**Gate GĐ2:** replay event log ghi lại từ GĐ1 cho kết quả giống hệt; không nhân đôi output; đo được độ trễ làn nhanh trên một lần công bố CPI/NFP đã ghi, nằm trong ngân sách.

### Nhật ký GĐ2

- **2026-11-13** — **Bắt đầu GĐ2 (DEC-19).** Người dùng cho làm GĐ2 song song vì GĐ1 chỉ còn kiểm / chờ ngày công bố; Gate GĐ1 chưa đóng và là điều kiện của Gate GĐ2. Lập `docs/ke-hoach/GD2-ke-hoach.md` (6 bước). Ý tưởng chính: sự kiện suy ra từ dữ liệu đã lưu theo `known_at` (replay được, không nhân đôi), nhật ký sự kiện + job chỉ-thêm, làn nhanh chỉ dùng luật (ngưỡng hỏi người dùng ở bước 4).
- **2026-11-13** — **Bước 1a + 1b: nhật ký sự kiện + job (ORC-03, ORC-06 phần lưu, ORC-08 phần lưu).** Thiết kế `docs/thiet-ke/25-event-orchestrator.md`. Migration 0014: `orchestrator_events` (event_id = sha256(loại|chủ thể|phiên bản), duy nhất), `orchestrator_jobs` (job_key khóa chính), `orchestrator_job_attempts` (trạng thái PENDING / RUNNING / SUCCEEDED / FAILED / DEAD / NO_HANDLER / SUPERSEDED, mã lỗi ngắn bắt buộc khi FAILED / DEAD) — cả ba chỉ-thêm. `orchestrator/model.py` (bộ nhớ) + `storage/orchestrator.py` (SQL), thứ tự nhân quả `(known_at, loại, chủ thể, phiên bản)`. Test 36 (bộ nhớ + SQLite): ghi trùng, thứ tự ổn định khi ghi xáo trộn, lọc cửa sổ, sự kiện tương lai ẩn, giờ không múi giờ, giờ New York → UTC, job tạo một lần, nhật ký lần thử cùng giờ giữ thứ tự ghi, mã lỗi chứa URL bị từ chối. **Soát lại** (Postgres 16): 8 luồng ghi cùng sự kiện / job → đúng 1; UPDATE / DELETE bị trigger chặn; ràng buộc chặn trạng thái lạ + FAILED thiếu mã; `alembic check` không lệch; xuống 0013 rồi lên lại.
- **2026-11-13** — **Bước 1c: bộ quét sinh sự kiện (ORC-02 phần nguồn).** `orchestrator/scanner.py`: nến (theo `max(ingested_at, available_at)`) + bản ghi ngoài (theo `known_at`) → 6 loại sự kiện, mốc = `known_at` lớn nhất − 15 phút chồng lấn, lần đầu 2 ngày, replay theo `since`; ghi theo lô (bỏ khóa đã có). Thêm `known_between` cho store nến + store bản ghi ngoài (cả hai bản). Test 13. **Soát lại** Postgres: 35.327 sự kiện (7 × 5.000 nến nạp bù + nguồn ngoài GĐ1) trong 2,5 giây, = bộ nhớ, quét lại không thêm. **Lỗi trong test khi viết:** kịch bản quét chia nhỏ không quét tới đúng mốc dữ liệu; nến thử chưa đóng bị từ chối — sửa test. **Giới hạn:** commit chậm > 15 phút bị bỏ sót ở chế độ thường (replay bắt được); sau nạp bù lớn mỗi lần quét ~2 giây trong 15 phút.
- **2026-11-14** — **Bước 2: bộ điều phối job (ORC-02 phần định tuyến, ORC-04, ORC-05, ORC-06, ORC-08; 2-C01..C05).** `orchestrator/dispatcher.py`: bảng định tuyến theo đặc tả 03, `NO_HANDLER` cho loại job chưa có bộ xử lý, debounce chỉ cho nến / số vĩ mô, chạy theo thứ tự nhân quả, deadline + retry + backoff + dead-letter, mã lỗi chỉ từ loại lỗi, khôi phục job dở dang khi khởi động lại (migration 0015: chỉ mục `created_at`). Test 22. **Soát lại:** 40 kịch bản ngẫu nhiên + Postgres — mọi bất biến giữ (thiết kế `25-…` mục 5). Chưa chạy tự động (bước 3).
- **2026-11-14** — **Bước 3: orchestrator chạy trong backend (ORC-01, ORC-07; 2-C06).** `orchestrator/runner.py`: nhịp 10 giây quét + điều phối; job `TECHNICAL` thay vòng 15 giây (đường lui `GT_ORCHESTRATOR=0`); sự kiện `OUTPUT_EXPIRED` từ `analyst_outputs` (hết hạn mà chưa có kết quả mới) → `INVALIDATE_MARKETVIEW` (`NO_HANDLER` tới GĐ4) + tính lại. Test 11 + 1 (bộ nhớ). **Soát lại** Postgres: 6 giờ dữ liệu — cùng 24 kết quả như vòng cũ; nhịp đầu 3,6 s, sau ≤ 0,4 s. **Lỗi tìm được:** RAM giữ mọi sự kiện đã xử lý → sửa. Chờ kiểm trên máy (mục 1 file kế hoạch GĐ2).
