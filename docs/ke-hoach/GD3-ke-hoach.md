# GĐ3 — 6 analyst bằng luật: kế hoạch + checklist

> Tạo 2026-11-14. Nguồn sự thật cho mã việc / case: [`docs/giai-doan/GD3-analyst.md`](../giai-doan/GD3-analyst.md). Đặc tả: `docs/huong-dan-chuc-nang/04-cac-analyst.md`. Xong bước nào tick ở **cả hai** file.
>
> **Bắt đầu song song GĐ1 + GĐ2 (DEC-22, người dùng 2026-11-14):** kế hoạch trước, analyst **Lịch sự kiện** làm đầu tiên. **GĐ3 không đóng trước GĐ1 rồi GĐ2.** Việc kiểm trên máy của GĐ1/GĐ2 vẫn theo [`lich-kiem-tren-may.md`](lich-kiem-tren-may.md) — ưu tiên hơn GĐ3; dựng lại máy người dùng cho GĐ3 chỉ khi cần kiểm, mỗi lần ngắn, **không** dựng lại trong đêm 6a (16→17/11) và tránh khung công bố.

## Ý tưởng chính

- **Analyst là người quan sát, không phải người chặn.** Chặn mở lệnh mới vẫn chỉ do Safety / làn nhanh (DEC-20) quyết. Cờ của analyst (vd. `EVENT_WINDOW`) để Fusion / Risk (GĐ4–5) đọc; **cùng một hàm nguồn** với làn nhanh (bảng lịch hợp nhất + `event_importance`) để hai bên không lệch nhau.
- **Mọi analyst dùng chung khung** (ANA-01): `AnalystOutput`, hết hạn, `sourceStatus`, phiên bản, lưu chỉ-thêm, point-in-time (`known_at <= as_of`), chạy qua orchestrator (job đã có sẵn ở GĐ2: `EVENT_CALENDAR`, `REGIME`, `MACRO`, `POSITIONING`, `NEWS` — hiện ghi `NO_HANDLER`).
- **Không có xác suất khi chưa hiệu chỉnh.** `confidence` = chất lượng / độ đủ của dữ liệu đầu vào (như Technical), ghi rõ không phải xác suất đúng.
- **Thiếu dữ liệu → nói thiếu**: không forecast → `surprise` = "không đủ dữ liệu" (DEC-01); COT trễ → không coi là thời gian thực; LLM lỗi → `MISSING`.

## Thứ tự làm (mỗi bước: thiết kế → code + test (gồm trường hợp xấu) + soát lại kịch bản riêng → tick → commit → push develop → kiểm CI)

### Bước 1 — Khung chung cho analyst không theo nguồn giá (ANA-01; 3-C01..C07)
- [x] 1a — Thiết kế `docs/thiet-ke/27-khung-analyst.md`: analyst theo nguồn giá (Technical, Regime) vs. toàn cục (Event, Macro, Positioning, News) — khóa lưu, `output_id` (phiên bản + as_of + hash đầu vào), hết hạn, sự kiện `OUTPUT_EXPIRED` cho analyst toàn cục
- [x] 1b — Migration (nếu cần) + store SQL + bản bộ nhớ, chỉ-thêm; **bộ test chung** 3-C01..C07 chạy được cho mọi analyst (thiếu input, cũ, thiếu lịch sử, spike, SAMPLE, thêm dữ liệu tương lai không đổi kết quả, đổi phiên bản giữ output cũ) (2026-11-14: `analysts/framework.py` — `Scope` / `GLOBAL_SCOPE` (`*`,`*`,`GLOBAL`,`""`), `output_id` xác định, `InputCheck` → `assess` (thiếu / cũ / thiếu lịch sử / cực đoan / SAMPLE; `known_at > as_of` → lỗi), `build_output` không xuất đặc trưng khi chặn; kho `append_scoped` / `latest_scoped(known_by=)`; **không cần migration**; 35 test; soát Postgres 16: ghi trùng 8 luồng → 1, trigger chặn sửa/xóa, 300 kết quả ngẫu nhiên bộ nhớ ≡ Postgres)

### Bước 2 — Analyst Lịch sự kiện (EVT-01..04; 3-C09)
- [ ] 2a — Thiết kế `docs/thiet-ke/28-event-analyst.md`: input = bảng lịch hợp nhất (GĐ1, `economic_calendar`) tại `as_of`; output `eventRisk` (mức cao nhất trong khung sắp tới), sự kiện kế tiếp + phút còn lại, cửa sổ đang mở / giờ kết thúc, cờ `EVENT_WINDOW` / `EVENT_SOON`, `surprise` = `INSUFFICIENT_DATA` (DEC-01); phân biệt "chưa công bố" với actual = 0; hoãn / hủy / đổi giờ (REMOVED, revision); công bố lúc thị trường đóng (3-C09); hết hạn = sớm nhất trong {mốc cửa sổ kế tiếp, TTL cố định}
- [ ] 2b — Code `analysts/event.py` + handler job `EVENT_CALENDAR` (+ tính lại khi hết hạn); test gồm DST, công bố trùng phút, lịch nguồn mâu thuẫn (3-C08), lịch hỏng / nguồn lịch lỗi → `STALE`/`MISSING`; soát lại: so cờ analyst với cửa sổ làn nhanh trên cùng dữ liệu → khớp 100 %
- [ ] 2c — API + thẻ giao diện (ANA-02); kiểm trên máy (DOL 19/11 hoặc dịp sau)

### Bước 3 — Regime bằng luật (REG-01, REG-02)
- [ ] Thiết kế + code: `TREND/RANGE/RISK_OFF/HIGH_VOL` từ biến động (ATR / độ lệch chuẩn lợi suất), độ dốc xu hướng, output Technical; ngưỡng là **giá trị khởi đầu chưa hiệu chỉnh** (ghi rõ, có phiên bản); không có "xác suất" (bản HMM ở GĐ7); trọng số gợi ý cho Fusion chỉ là bảng có phiên bản

### Bước 4 — Macro (MAC-01, MAC-02)
- [ ] Từ H.15 (lợi suất, lợi suất thực 10Y nếu có) + chỉ số USD đã nạp ở GĐ1, đồng bộ theo giờ công bố; thay đổi / độ bất thường (z-score theo cửa sổ), macro bias, cờ stress; TTL theo tần suất dữ liệu; revision không viết lại quá khứ

### Bước 5 — Positioning (POSN-01, POSN-02)
- [ ] COT vàng: z-score lịch sử, cực trị, crowding; đánh dấu rõ độ trễ (chốt thứ Ba, công bố thứ Sáu); ETF / NHTW **phụ thuộc quyết định ở Gate GĐ1** — chưa có thì `MISSING`, không đoán

### Bước 6 — News (DEC-08; NEWS-01..04; 3-C10) — cần người dùng chốt DEC-08 trước
- [ ] Hỏi DEC-08 (nhà cung cấp LLM + ngân sách tháng) → thiết kế → lọc trùng, lọc trước bằng luật, LLM trích stance/impact có trích dẫn, giới hạn token / timeout, chống prompt injection (3-C10), lưu prompt + phiên bản mô hình; lỗi / hết ngân sách → `MISSING`

### Bước 7 — Technical còn lại (TEC-05, TEC-06, TEC-07, TEC-09)
- [ ] TEC-05 theo dõi R3/R5 trên dữ liệu thật; TEC-07 `volForecast` bằng luật (ghi rõ không phải mô hình); TEC-09 đa khung H1/H4/D1; TEC-06 mẫu hình (chỉ sau khi đủ nến xác nhận)

### Bước 8 — Gate GĐ3
- [ ] 6 analyst có thiết kế + test case + thẻ giao diện; mọi case 3-C01..C10 có test
- [ ] Chạy song song trên dữ liệu thật ≥ 5 ngày giao dịch; mỗi output truy được về input
- [ ] **Gate GĐ1 và GĐ2 đã đóng** (DEC-22)
- [ ] Người dùng xác nhận

## Kiểm trên máy người dùng (điền khi tới)

(chưa có)

## Prompt cho phiên mới
Đọc CLAUDE.md, PROGRESS.md, rồi docs/ke-hoach/GD3-ke-hoach.md và chỉ các mục liên quan của docs/giai-doan/GD3-analyst.md. Làm bước tiếp theo chưa tick. GĐ3 làm song song GĐ1/GĐ2 (DEC-22) — việc kiểm trên máy của GĐ1/GĐ2 theo docs/ke-hoach/lich-kiem-tren-may.md được ưu tiên; GĐ3 không đóng trước GĐ1, GĐ2. Analyst chỉ quan sát, không tự chặn lệnh (chặn do Safety / làn nhanh DEC-20). Không forecast → surprise "không đủ dữ liệu" (DEC-01). Quy trình: thiết kế → code + test (gồm trường hợp xấu) + soát lại kịch bản riêng → tick ở cả hai file, ghi nhật ký GĐ3, cập nhật PROGRESS.md ngắn gọn → chạy test → commit (nhắc mã việc) → push develop → kiểm CI. Người dùng không rành kỹ thuật: tiếng Việt đơn giản, mỗi lần hỏi một câu. Không bao giờ yêu cầu dán mật khẩu / token / khóa API vào chat.
