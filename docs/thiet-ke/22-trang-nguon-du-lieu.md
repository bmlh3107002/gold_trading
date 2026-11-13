# Thiết kế — Trang "Nguồn dữ liệu" (GĐ1 bước 10e — DSH-09)

> Tạo 2026-11-13. Code: `backend/src/gold_trading/ingestion/source_overview.py`, `backend/src/gold_trading/api/data_sources.py`, `frontend/src/pages/SourcesPage.tsx`. Test: `backend/tests/test_data_sources.py`, `frontend/src/pages/SourcesPage.test.tsx`.

## 1. Mục đích + phạm vi

Một trang cho người dùng thấy từng **nguồn ngoài** (lịch kinh tế, số vĩ mô, vị thế COT, tin chính thức) đang khỏe hay không: trạng thái, lần nhận cuối, độ trễ dữ liệu, lỗi gần nhất, số bản ghi bị cách ly. **Chỉ đọc**, không có nút điều khiển.

Không gồm giá MT5 (nến, bid/ask): trạng thái giá theo từng tài khoản đã có ở trang Thị trường + băng Gateway (DEC-14 — mỗi tài khoản một nguồn giá), không lặp lại ở đây.

## 2. Nguồn sự thật — không có quy tắc riêng cho trang

- Danh sách nguồn = `SourceRegistry` của **chính bộ chạy tự động** (`ExternalSourceRunner.registry`, gồm cả nguồn tin từ `news_sources.json`, cả nguồn khai báo mà đang tắt).
- Trạng thái = `source_status.evaluate(...)` tại `as_of = now` — **cùng hàm** mà phần còn lại của hệ thống dùng (ING-30). Trang không tự suy luận "khỏe / cũ".
- Số cách ly = đếm bảng `external_quarantine` theo nguồn (`quarantine_counts`, có ở cả store SQL lẫn bộ nhớ): 7 ngày gần nhất và tổng, chỉ tính bản ghi có `received_at <= as_of`.

## 3. API `GET /api/data-sources`

- Mọi người dùng đã đăng nhập (ADMIN + USER) — không chứa dữ liệu tài khoản. Chưa đăng nhập → 401 (phụ thuộc chung của app).
- Trả `as_of`, `runner_enabled` (False khi `GT_EXTERNAL_SOURCES=0` → danh sách rỗng, trang báo rõ), `quarantine_window_days` (7), và mỗi nguồn: `name`, `kind`, `provider`, `terms_status`, `enabled`, `status`, `reason`, `flags`, `last_check_at`, `last_ok_at`, `last_error_code`, `failures_since_ok`, `latest_event_at`, `fetch_ttl_seconds`, `data_ttl_seconds`, `receive_age_seconds`, `data_age_seconds`, `quarantine_7d`, `quarantine_total`.
- **Không lộ khóa / URL:** `last_error_code` là mã ngắn đã bị chặn định dạng ở ING-30 (code + DB); test thử ghi mã chứa URL + khóa → bị từ chối, phản hồi không chứa khóa.

| Cột trên trang | Trường | Ý nghĩa |
| --- | --- | --- |
| Trạng thái | `status` + `reason` | Khỏe / Cũ / Thiếu / Hỏng + lý do tiếng Việt (mã lạ → hiện nguyên mã); thêm "N lần lỗi gần đây" khi cờ `RECENT_FAILURES` |
| Lần nhận cuối | `last_ok_at`, `receive_age_seconds` | Lần tải OK cuối + "cách đây …" |
| Độ trễ dữ liệu | `data_age_seconds` | `as_of − event_time` mới nhất đã biết. **Lịch** → "—" (sự kiện lịch ở tương lai, không có nghĩa) |
| Lỗi gần nhất | `last_error_code` | Mã lỗi cuối cùng từng gặp (có thể từ trước lần OK cuối) |
| Cách ly (7 ngày / tổng) | `quarantine_7d`, `quarantine_total` | Đỏ khi 7 ngày > 0 |

## 4. Giao diện

- Menu "Nguồn dữ liệu" (`#sources`) cho USER, sau "Thị trường". ADMIN không thấy (DEC-16: ADMIN chỉ có trang Quản trị; API vẫn cho ADMIN đọc).
- Tải lại 30 giây/lần (`usePolling`); mất kết nối → giữ số cũ, băng kết nối chung báo.
- Tên nguồn tiếng Việt cho 10 nguồn hiện có; nguồn mới thêm qua file cấu hình mà chưa có bản dịch → hiện nguyên mã (không vỡ trang).

## 5. Kiểm chứng (2026-11-13)

- Backend 12 test (bộ nhớ + SQLite): 6 nguồn đủ trạng thái (HEALTHY, STALE quá TTL, MISSING lỗi chết FORBIDDEN, MISSING chưa kiểm, tắt + điều khoản BLOCKED, INVALID, cờ PARTIAL_INVALID / RECENT_FAILURES), cách ly 7 ngày / tổng / sau `as_of` không tính, point-in-time (tính tại `as_of` cũ không thấy lần kiểm / bản ghi / cách ly sau đó), lần kiểm + dữ liệu tương lai bị bỏ qua; API: USER đọc được, ADMIN đọc được, bộ chạy tắt → rỗng, chưa đăng nhập → 401, không lộ khóa.
- Frontend 3 test: bảng 4 nguồn (khỏe / cũ có lỗi gần đây / thiếu có cách ly / mã lạ), lịch không hiện độ trễ, bộ chạy tắt; `formatAge` ở các biên (59 s, 60 s, 3599 s, 3600 s, 47 giờ, 48 giờ).
- **Soát lại** (kịch bản riêng, Postgres 16 + nguồn thật Fed / Bộ Tài chính / H.15): bộ chạy tải thật, ép 2 bản cách ly → với từng nguồn, `last_ok_at`, `latest_event_at`, số cách ly 7 ngày, tuổi lần nhận khớp truy vấn SQL viết tay.
- **Giới hạn:** "độ trễ" là tuổi dữ liệu mới nhất, chưa phải độ trễ công bố → nhận của từng số (đo riêng cho CPI/NFP khi có BLS — ING-17); chưa có lịch sử trạng thái theo thời gian (biểu đồ) — để sau nếu cần.
