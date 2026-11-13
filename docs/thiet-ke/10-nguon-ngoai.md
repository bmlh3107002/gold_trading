# Thiết kế — Khung chung cho nguồn dữ liệu ngoài (GĐ1 bước 7, mục 1G)

> Nguồn **không phải nến MT5**: lịch kinh tế (1C), tin (1D), vĩ mô (1E), vị thế/dòng tiền (1F). Bước 7 chỉ dựng **khung chung**; nạp nguồn thật làm ở bước 8–10. Mọi quy tắc ở đây ảnh hưởng tới việc hệ thống "biết" gì tại một thời điểm → ảnh hưởng quyết định giao dịch.

## 1. Lưu trữ point-in-time (7a — DB-08, ING-13, 2026-11-12)

**Bảng** (migration 0012, chỉ thêm — trigger chặn `UPDATE` + `DELETE`; bảng thường, không hypertable vì lượng nhỏ và khóa duy nhất không chứa cột thời gian):

- `external_records`: mỗi dòng là **một revision của một dữ kiện**.
- `external_quarantine`: bản ghi bị từ chối + lý do + nội dung gốc.

**Định danh:**

| Khái niệm | Khóa | Ví dụ |
| --- | --- | --- |
| Dữ kiện | `(source, logical_key)` | `("bls", "CPI:2026-10")` |
| Bản ghi | `(source, logical_key, revision)` — duy nhất | revision 0 = số đầu tiên, 1 = sửa lần 1 |
| `record_id` | duy nhất toàn bảng | do bộ nạp đặt |
| `kind` | `calendar` / `news` / `macro` / `positioning` | cố định theo dữ kiện |

**Thời gian** (tất cả UTC; giờ không có múi giờ → từ chối):

- `event_time`: lúc sự kiện xảy ra (lịch: giờ công bố dự kiến; vĩ mô: cuối kỳ số liệu; tin: giờ đăng).
- `available_at`: lúc **nguồn công bố công khai** (có thể trống = nguồn không cho biết).
- `ingested_at`: lúc hệ thống nhận được.
- **`known_at = max(ingested_at, available_at)`** — chỉ từ lúc này hệ thống mới được dùng bản ghi.

**Quy tắc đọc `as_of(t)`:** chỉ thấy bản ghi có `known_at <= t`; mỗi dữ kiện lấy **revision lớn nhất** trong số đã thấy. Revision đến sau không viết lại quá khứ; revision đến lệch thứ tự (2 trước 1) vẫn đúng.

**Lý do dùng `max` (an toàn, có đánh đổi):**
- Số liệu ngày D mà nguồn ghi công bố D+1 (1E-C01) → nạp sớm cũng không dùng sớm.
- Nạp bù dữ liệu lịch sử hôm nay → `known_at` = hôm nay → **backtest quá khứ không thấy** dữ liệu đó. Đây là giới hạn cố ý: chưa có cách chứng minh thời điểm công bố của dữ liệu nạp bù. Khi làm backtest (GĐ sau) cần quyết định riêng có tin `available_at` của nguồn (ví dụ "vintage" của ALFRED) hay không — không tự đổi quy tắc này.
- Ngoài `calendar`, `ingested_at` và `available_at` không được sớm hơn `event_time` (không biết trước điều chưa xảy ra). Lịch công bố thì được biết trước.

**Ghi (`append`) — kết quả:**

| Kết quả | Khi nào | Xử lý |
| --- | --- | --- |
| `INSERTED` | Dữ kiện/revision mới | Thêm dòng |
| `DUPLICATE` | Cùng định danh + cùng **fingerprint** + cùng `record_id` | Bỏ qua, giữ `ingested_at` đầu tiên (nạp lại → cùng kết quả) |
| `CONFLICT` | Cùng định danh mà khác nội dung (`REVISION_CONFLICT`), `record_id` đã dùng cho dữ kiện khác (`RECORD_ID_CONFLICT`), đổi `kind` (`KIND_CHANGED`) | **Không ghi đè**, vào cách ly. Nguồn sửa số thì bộ nạp phải tạo revision mới |
| `INVALID` | `kind` lạ, số NaN/vô cực, không phải JSON, quá 256 KB, chuỗi quá dài, có ký tự NUL (Postgres không lưu được) | Vào cách ly |

**Fingerprint** = SHA-256 của JSON chuẩn (khóa sắp xếp) gồm `kind`, `event_time`, `available_at`, `payload_version`, `payload`. **Không** gồm `ingested_at`, `raw_ref`, cờ chất lượng, trạng thái nguồn — để nguồn trả lại cùng số liệu lúc khác vẫn là trùng.

**Raw:** cột `raw` (JSON) giữ nguyên nội dung gốc của nguồn (ví dụ giá trị `"."` của FRED) để đối chiếu; không dùng để quyết định.

**Code:** `ingestion/point_in_time.py` (quy tắc chung + bản trong bộ nhớ dùng cho test/tham chiếu), `storage/external_records.py` (bản SQL). Hai bản chạy cùng một bộ test.

**Ghi đồng thời:** hai tiến trình ghi cùng dữ kiện → ràng buộc duy nhất của DB chặn; bên thua kiểm lại và ra `DUPLICATE` hoặc `CONFLICT` (đã kiểm 8 luồng trên Postgres).

**Chưa làm ở 7a:** xóa theo hạn giữ (ING-33, bước 10 — khi cần sẽ là ngoại lệ có ghi lý do như `quote_seconds`); nối vào bộ nạp nguồn thật (bước 8–10).

## 2. Trạng thái nguồn + TTL riêng (7b — ING-30, 2026-11-13)

**Nhật ký lần kiểm** (migration 0013, bảng `external_source_checks`, chỉ thêm — trigger chặn `UPDATE` + `DELETE`): mỗi lần bộ nạp gọi một nguồn ghi một dòng `(source, checked_at, outcome, error_code, inserted, duplicate, conflict, invalid)`. `outcome`:

| `outcome` | Khi nào |
| --- | --- |
| `OK` | Nguồn trả lời, đọc được (kể cả không có gì mới) |
| `ERROR` | Không lấy được: mạng, HTTP lỗi, khóa sai... |
| `INVALID` | Lấy được nhưng hỏng; hoặc **mọi** bản ghi bị từ chối (`ALL_RECORDS_REJECTED`). Một phần hỏng → vẫn `OK`, kèm cờ `PARTIAL_INVALID` / `CONFLICT_SEEN` |

**`error_code` chỉ là mã ngắn** `[A-Z][A-Z0-9_]{0,63}` (ví dụ `TIMEOUT`, `HTTP_503`, `AUTH_FAILED`) — code và DB đều chặn thông điệp lỗi gốc, vì thông điệp có thể chứa URL kèm khóa API (FRED để khóa trong URL). Lý do: an toàn ING-31.

**Không lưu trạng thái** — tính lại tại mọi `as_of` từ nhật ký (chỉ lần kiểm có `checked_at <= as_of`) và từ dữ liệu đã biết. Tính lại quá khứ → cùng kết quả; lần kiểm ghi sau không viết lại quá khứ.

**Cấu hình mỗi nguồn** (`SourceSpec`): `fetch_ttl` = lâu nhất kể từ lần kiểm OK cuối; `data_ttl` (tùy chọn) = lâu nhất kể từ `event_time` của dữ kiện mới nhất đã biết (bắt trường hợp nguồn vẫn trả lời nhưng không có số mới — công bố trễ, chính phủ đóng cửa, 1F-C02). TTL > 0 và ≤ 400 ngày; lịch (`calendar`) không có `data_ttl` (sự kiện ở tương lai). Tên nguồn trùng → lỗi cấu hình. TTL cụ thể đặt khi thêm từng nguồn (bước 8–10), kèm lý do.

**Thứ tự quyết định** (gặp điều nào trước thì dừng):

| # | Điều kiện | Trạng thái | `reason` |
| --- | --- | --- | --- |
| 1 | Nguồn không khai báo / đang tắt | MISSING | `UNKNOWN_SOURCE` / `DISABLED` |
| 2 | Chưa kiểm lần nào | MISSING | `NEVER_CHECKED` |
| 3 | Sau lần OK cuối có lỗi "chết" (`AUTH_FAILED`, `KEY_MISSING`, `SOURCE_DISCONTINUED`, `FORBIDDEN`) | MISSING (ngay, không chờ TTL) | mã lỗi |
| 4 | Sau lần OK cuối có lần `INVALID` | INVALID | mã lỗi |
| 5 | Chưa OK lần nào | MISSING | `NEVER_OK` |
| 6 | Lần OK cuối cũ hơn `fetch_ttl` | STALE | `FETCH_TTL_EXPIRED` |
| 7 | Có `data_ttl`, chưa có dữ kiện / dữ kiện mới nhất cũ hơn `data_ttl` | MISSING / STALE | `NO_DATA` / `DATA_TTL_EXPIRED` |
| 8 | Còn lại | HEALTHY | `OK` |

**Lý do + đánh đổi:**
- Lỗi tạm (mạng, 5xx, `RATE_LIMITED`) **không** đổi trạng thái ngay — đó là ý nghĩa của TTL; còn hạn thì HEALTHY kèm cờ `RECENT_FAILURES`, quá hạn → STALE. Lỗi "chết" và dữ liệu hỏng không tự hết theo thời gian → báo ngay (hướng an toàn). Lỗi tạm đến sau không che lỗi chết.
- Đúng bằng TTL vẫn còn hạn (`>` mới hết). TTL tính theo thời gian thật (UTC), đổi giờ DST không làm lệch.
- Độ cũ dữ liệu đo bằng `event_time` (không phải `known_at`): nạp bù hôm nay một báo cáo cũ **không** làm nguồn "mới". Chỉ tính dữ kiện đã biết tại `as_of` và `event_time <= as_of`.
- Cùng `checked_at` thì thứ tự ghi (`seq`) quyết định.

**Code:** `ingestion/source_status.py` (quy tắc + nhật ký trong bộ nhớ), `storage/source_checks.py` (SQL), `latest_event_time` ở cả hai store bản ghi. Hai bản chạy cùng bộ test. **Chưa làm:** nối vào bộ nạp thật + đặt TTL từng nguồn (bước 8–10); backoff khi bị giới hạn tần suất (1D-C05, bộ nạp tin); hiển thị (DSH-09); hạn giữ nhật ký (ING-33).
