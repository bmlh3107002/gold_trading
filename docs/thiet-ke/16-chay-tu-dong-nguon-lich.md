# Thiết kế — Chạy tự động các nguồn lịch kinh tế trong backend (GĐ1 bước 8g)

> Code: `backend/src/gold_trading/ingestion/external_runner.py`. Test: `backend/tests/test_external_runner.py`. Nguồn: FOMC (`12-lich-fomc.md`), BEA (`13-bea.md`), DOL (`15-dol.md`). Census (`14-census.md`) **không** chạy (tạm hoãn 2026-11-13: Census chặn Việt Nam).

## 1. Phần 1 — bộ chạy (8g-1, 2026-11-13)

**Bật/tắt:** biến `GT_EXTERNAL_SOURCES` (compose chuyển vào backend). Trống / không đặt = `fed_fomc,bea,dol`; `0` / `off` = tắt; danh sách khác = chỉ những nguồn đó. Tên lạ (kể cả `census`) → **lỗi cấu hình**, backend không khởi động — không âm thầm bỏ qua. Bản `docker-compose.yml` cũ (chưa có biến) vẫn chạy mặc định.

**Việc** (thứ tự chạy trong một nhịp — lịch trước, số sau, vì số BEA/DOL cần lịch để gắn lần công bố):

| Việc | Nguồn trong nhật ký | Khi nào gọi |
| --- | --- | --- |
| Lịch FOMC | `fed_fomc` | lần OK cuối cũ hơn **20 giờ** (TTL 26 giờ → còn 6 giờ cho lỗi tạm); lỗi → thử lại sau **30 phút** |
| Lịch BEA | `bea_schedule` | như trên |
| Lịch DOL (theo quy tắc, không gọi mạng) | `dol_claims_schedule` | như trên |
| Số BEA (cần khóa) | `bea_nipa` | `RELEASE_WINDOW` (90 phút sau giờ công bố GDP/PIO đã xác nhận, **chưa có số của lần đó**): mỗi **60 giây**; `RECONCILE` (lần OK cuối > 7 ngày): thử lại sau **6 giờ** |
| Số DOL | `dol_claims` | `RELEASE_WINDOW` (90 phút sau 8:30 ET thứ Năm, chưa có bản tin phát hành từ 8:30): mỗi **60 giây**; `RELEASE_DAY` (tuần lễ, 8:00–18:00 ET thứ Tư–Sáu, chưa có bản tin phát hành từ 0:00 ET thứ Tư): mỗi **5 phút**; `RECONCILE`: sau 6 giờ |

**Nhịp:** 30 giây. Quyết định "đến hạn" là hàm thuần (`schedule_due`, `values_job_due`, `values_due` của nguồn) chỉ dựa vào **nhật ký lần kiểm đã lưu** (ING-30) và dữ liệu đã lưu → khởi động lại backend không gọi dồn, không mất nhịp.

**"Đã có số của lần công bố này"** đọc từ dữ liệu đã lưu (không giữ trong bộ nhớ): BEA — có bản ghi số mang `release_ref` = sự kiện lịch đó (GDP và PIO cùng giờ là hai lần công bố riêng: có một chưa đủ); DOL — có bản ghi `available_at` ≥ giờ công bố (tuần lễ: ≥ 0:00 ET thứ Tư).

**Lý do các con số:**
- 60 giây trong cửa sổ công bố: độ trễ actual cỡ 1–2 phút là đủ cho GĐ1 (ING-17 đo độ trễ); BEA cho 100 lượt/phút, mỗi lần 2 lượt; thôi gọi ngay khi đã có số (BEA không khuyến khích gọi khi chưa có số mới).
- 5 phút cho ngày tuần lễ DOL: không biết DOL phát hành ngày nào trong 3 ngày; gọi mỗi phút suốt 10 giờ × 3 ngày là ~1.800 lượt tải PDF. Đánh đổi: độ trễ số tuần lễ tới 5 phút — chấp nhận, vì cả ngày đó đã bị coi là ngày rủi ro (chặn cả ngày).
- 6 giờ cho đối chiếu / thiếu khóa: không ghi nhật ký mỗi 30 giây khi người dùng chưa đặt khóa.

**An toàn:**
- Đồng hồ máy chủ bị chặn (`ClockMonitor.ingest_block_reason`) → **không nạp gì** (giờ sai làm sai `ingested_at` = thời điểm "đã biết"). Ghi cảnh báo một lần.
- Lỗi bất ngờ trong một việc (lỗi lập trình) → ghi lần kiểm `ERROR / INTERNAL_ERROR` (chỉ mã, không thông điệp — thông điệp có thể chứa URL kèm khóa), các việc khác vẫn chạy; giãn cách như lỗi thường.
- **Log:** `httpx` ghi URL đầy đủ ở mức INFO — URL BEA chứa khóa (`UserID`). Bộ chạy hạ log `httpx`/`httpcore` xuống WARNING (lớp thứ hai, ngoài bộ che log JSON theo giá trị của ING-31). Phát hiện khi soát lại bằng mạng thật.
- Chỉ đọc trang công khai; không đổi gì ở nguồn.

**Giới hạn:** một tiến trình backend (chạy hai backend cùng DB thì có thể gọi trùng — store chặn ghi trùng, chỉ tốn lượt gọi); lệnh CLI chạy tay song song cũng vậy. Chưa có backoff riêng khi bị giới hạn tần suất (`RATE_LIMITED` dùng chung giãn cách); trang hiển thị trạng thái là DSH-09 (bước 10).
