# GĐ4 — Snapshot → Quality Gate → Fusion → MarketView: kế hoạch + checklist

> Tạo 2026-11-15. Nguồn sự thật cho mã việc / case: [`docs/giai-doan/GD4-snapshot-fusion-marketview.md`](../giai-doan/GD4-snapshot-fusion-marketview.md). Đặc tả: `docs/huong-dan-chuc-nang/05-snapshot-fusion-marketview.md`. Xong bước nào tick ở **cả hai** file.
>
> **Làm song song GĐ1 + GĐ2 + GĐ3 (DEC-23, người dùng 2026-11-15).** **Không đóng GĐ4 trước GĐ1 → GĐ2 → GĐ3.** Việc kiểm trên máy của các giai đoạn trước theo [`lich-kiem-tren-may.md`](lich-kiem-tren-may.md) được ưu tiên; dựng lại máy người dùng cho GĐ4 chỉ khi cần kiểm, mỗi lần ngắn, **không** dựng lại trong đêm 6a (16→17/11) và tránh khung công bố.

## Quyết định người dùng đã chốt (2026-11-15)

| Mã | Câu hỏi | Chốt |
| --- | --- | --- |
| DEC-24 | Analyst nào bắt buộc cho Quality Gate | **Bắt buộc: Technical, Lịch sự kiện (Event), Regime.** Tùy chọn: Macro, Positioning (COT), News. Bắt buộc thiếu / hết hạn / không `HEALTHY` → `REJECTED`, không có MarketView |
| DEC-25 | Fusion có ra hướng khi chưa backtest | **Có — "nghiêng theo luật", gắn nhãn chưa kiểm chứng** (cờ `UNVALIDATED_RULES`). Chỉ dùng cho xem / PAPER / backtest; **Risk chặn ở SHADOW/LIVE** tới khi backtest GĐ6 đạt và người dùng duyệt (đổi cờ = quyết định mới, ghi vào file giai đoạn) |
| DEC-26 | Cách gộp khi chưa có trọng số hiệu chỉnh | **Giá dẫn, nhóm khác chỉ hạ.** Hướng chỉ lấy từ giá (Technical: xu hướng + đa khung, khi Regime là `TREND` cùng chiều). Macro / COT / News ngược chiều chỉ được **hạ confidence hoặc đưa về `NEUTRAL`**, không bao giờ tự tạo hướng. Không dùng trọng số đặt tay; bảng trọng số Regime (`regime-weights-0-neutral`) không dùng để tạo hướng |
| DEC-27 | `pUp` / `pDown` khi chưa hiệu chỉnh | **Để trống** (`null`) + cờ `UNCALIBRATED`. Thẻ hiện "Chưa có — chưa hiệu chỉnh". Chỉ điền khi GĐ7 hiệu chỉnh xong trên dữ liệu thật |

## Ý tưởng chính

- **MarketView theo nguồn giá** (MT-05 / DEC-14: mỗi tài khoản theo giá broker của mình). Một snapshot = output Technical / Regime / Macro **của đúng nguồn giá đó** + output toàn cục Event / Positioning / News (`GLOBAL_SCOPE`, thiết kế 27). Không trộn nguồn giá.
- **Point-in-time tuyệt đối.** Snapshot tại `at` chỉ lấy output đã ghi (`known_by`) và còn hiệu lực tại `at`; thêm output "tương lai" vào kho rồi dựng lại tại `at` cũ → cùng kết quả. Lưu **manifest** (danh sách `output_id`) — output analyst đã chỉ-thêm nên tái dựng được từ manifest.
- **Quality Gate không tự chữa dữ liệu**; mọi quyết định (`ACCEPTED` / `DEGRADED` / `REJECTED`) có lý do, có phiên bản chính sách, được lưu chỉ-thêm để audit.
- **Fusion bằng luật, minh bạch, có phiên bản.** Không xác suất (DEC-27), `confidence` = chất lượng / mức đồng thuận của đầu vào (không phải xác suất đúng), luôn mang cờ `UNVALIDATED_RULES` + `UNCALIBRATED` cho tới GĐ6/GĐ7. Bất đồng → hạ confidence / `NEUTRAL` (4-C03). Mọi ngưỡng / hệ số là **giá trị khởi đầu chưa hiệu chỉnh**, ghi rõ trong thiết kế.
- **Mặc định an toàn:** không có MarketView còn hạn → không có tín hiệu. Cờ rủi ro (vd. `EVENT_WINDOW`) và cờ chất lượng (`SAMPLE_DATA`, `UNVALIDATED_RULES`) truyền xuống để Risk chặn. Chặn lệnh vẫn do Safety / làn nhanh (DEC-20) và Risk — Fusion chỉ mô tả.
- **Ngoài phạm vi GĐ4:** Fusion bằng mô hình / xác suất hiệu chỉnh, MQC (calibration, Brier, PSI) → GĐ7; Strategy → GĐ5; backtest → GĐ6.

## Thứ tự làm (mỗi bước: thiết kế → code + test (gồm trường hợp xấu) + soát lại kịch bản riêng → tick → commit → push develop → kiểm CI)

### Bước 1 — Thiết kế tổng thể + sửa hợp đồng MarketView (DEC-24..27; MKV-01)
- [ ] 1a — Thiết kế `docs/thiet-ke/33-snapshot-fusion-marketview.md`: phạm vi theo nguồn giá; khi nào sinh MarketView (sau mỗi lần một analyst đầu vào có kết quả mới — job `FUSION` trong orchestrator, debounce); `expiresAt` = sớm nhất trong hạn các output **bắt buộc** đã dùng (và không quá TTL cố định); khóa lưu + `market_view_id` xác định (phiên bản Fusion + nguồn + `as_of` + hash manifest) để idempotent; bảng luật Fusion (bước 4) viết trước khi code; chính sách Quality Gate `quality-policy-1` (bước 3)
- [ ] 1b — Hợp đồng `MarketView`: `p_up` / `p_down` cho phép `null` (DEC-27), thêm nguồn giá (`source`, `feed_id`, `timeframe`), `quality_policy_version`, giữ `model_version` (= phiên bản Fusion); kiểm hợp lệ: có số xác suất thì phải có cờ đã hiệu chỉnh — GĐ4 luôn `null`. Xuất OpenAPI + `npm run gen:api`; thẻ Tổng quan tạm hiện "Chưa có — chưa hiệu chỉnh" thay ô xác suất. Test: hợp đồng từ chối số xác suất khi đang `UNCALIBRATED`

### Bước 2 — Snapshot Builder theo phạm vi + lưu manifest (SNP-01, SNP-02; 4-C06)
- [ ] Chọn output mới nhất **đã biết** (`latest_scoped(known_by=at)`) và còn hiệu lực cho mỗi analyst, đúng phạm vi (theo nguồn giá / toàn cục); `available_at` = `at`; manifest = `{analyst: output_id}` + phiên bản từng analyst; cờ `SAMPLE_DATA` nếu bất kỳ đầu vào nào từ SAMPLE (4-C06)
- [ ] Migration bảng `market_snapshots` (chỉ-thêm, trigger chặn sửa/xóa, duy nhất theo id) + store SQL + bản bộ nhớ; hàm **tái dựng** snapshot từ manifest
- [ ] Test xấu: thêm output tương lai không đổi snapshot cũ; output đã hết hạn / chưa ghi tại `at` không được chọn; trùng ghi → 1 bản; nguồn giá khác không lọt vào; output analyst bị xóa khỏi kho (giả lập) → tái dựng báo lỗi, không đoán
- [ ] Soát riêng: Postgres + **TimescaleDB qua CI**; dựng từ manifest = dựng trực tiếp trên N thời điểm ngẫu nhiên

### Bước 3 — Quality Gate đầy đủ (DQG-01 theo DEC-24, DQG-02, DQG-03; 4-C01, 4-C02, 4-C07; 2-C04 phía dùng)
- [ ] Chính sách `quality-policy-1`: bắt buộc Technical / Event / Regime; tùy chọn Macro / Positioning / News với hệ số hạ confidence khi thiếu / cũ (**giá trị khởi đầu chưa hiệu chỉnh**, chốt + ghi lý do trong thiết kế 33). Analyst lỗi / dead-letter = `MISSING`, không dùng output cũ quá hạn (2-C04)
- [ ] DQG-02: schema (output thiếu đặc trưng Fusion cần → coi như không hợp lệ, có lý do), outlier (cờ `SPIKE_IN_INPUT` / `EXTREME_INPUT` của analyst → truyền + hạ theo chính sách), **xung đột timestamp** (4-C07): Technical và Regime phải tính trên **cùng một nến đóng**; lệch → `REJECTED` `TIMESTAMP_CONFLICT` (chờ lần sau, an toàn); output tùy chọn lệch quá tuổi cho phép → cờ; `as_of` > `at` → lỗi lập trình
- [ ] DQG-03: lưu `QualityReport` chỉ-thêm (verdict, lý do, phiên bản chính sách, snapshot) — audit
- [ ] Test mọi nhánh + soát kịch bản riêng (ma trận thiếu / cũ / lỗi × bắt buộc / tùy chọn)

### Bước 4 — Fusion bằng luật (FUS-01; 4-C03, 4-C04)
- [ ] `intelligence/fusion.py`, phiên bản `fusion-rules-1.0.0`, theo DEC-25/26: hướng gốc từ Technical (xu hướng M15 + `mtf_alignment` không `CONFLICT`) **chỉ khi** Regime `TREND` cùng chiều; `RANGE` / `HIGH_VOL` / `RISK_OFF` / mơ hồ → `NEUTRAL`. Macro (`HEADWIND` khi đang nghiêng mua…), COT cực trị ngược chiều, News trái chiều → hạ confidence; nhiều nhóm cùng ngược → `NEUTRAL` + driver `ANALYSTS_DISAGREE` (4-C03). Các analyst cùng từ giá (Technical + Regime) **không** được tính là nhiều phiếu độc lập
- [ ] `confidence` = min(chất lượng các đầu vào bắt buộc) × hệ số Quality Gate × hệ số bất đồng — không phải xác suất; `p_up` / `p_down` = `null`; cờ `UNVALIDATED_RULES`, `UNCALIBRATED` luôn có; `risk_flags` = hợp cờ rủi ro các analyst (`EVENT_WINDOW`, `EVENT_SOON`, cờ làn nhanh…) (4-C04); `vol_forecast` từ Technical TEC-07; `drivers` truy được về từng analyst
- [ ] Test: bảng luật đầy đủ tính tay (mỗi ô một test), bất đồng, cửa sổ sự kiện, SAMPLE, thiếu tùy chọn; **soát riêng**: viết lại luật độc lập (bảng tra thuần) so trên hàng nghìn tổ hợp ngẫu nhiên → khớp 100 %

### Bước 5 — Lưu, hết hạn, vô hiệu MarketView + phía dùng (MKV-02; 4-C05, 4-C06; ORC-02 / ORC-07 / 2-C06 phần GĐ4)
- [ ] Migration `market_views` (chỉ-thêm) + bảng vô hiệu (chỉ-thêm); job `FUSION` trong bộ định tuyến (sau Technical / Regime / Event / Macro / Positioning / News có kết quả mới, debounce) — tăng `ROUTER_VERSION`; bộ xử lý `INVALIDATE_MARKETVIEW` (output bắt buộc hết hạn mà chưa có mới → vô hiệu; không còn MarketView còn hạn → không tín hiệu)
- [ ] `latest_valid(nguồn giá, at)`: chỉ trả MarketView còn hạn, chưa bị vô hiệu, đúng nguồn
- [ ] Risk (phần tối thiểu cho 4-C05/4-C06, không làm thêm chính sách GĐ5): kiểm lại `expiresAt` lúc quyết (đã có), **chặn ở SHADOW/LIVE** khi MarketView có `SAMPLE_DATA` hoặc `UNVALIDATED_RULES` (DEC-25); test hết hạn giữa chừng
- [ ] Soát riêng: orchestrator thật trên Postgres, nạp từng nến 1–2 ngày → MarketView không trùng, tính lại tại đúng thời điểm cùng id; tắt một analyst bắt buộc → vô hiệu đúng lúc, không còn MarketView còn hạn

### Bước 6 — API + thẻ Tổng quan (MKV-03)
- [ ] `GET /api/accounts/{id}/market-view/latest` (chỉ chủ tài khoản, nguồn giá của tài khoản — MT-05) thay `market_view` TODO trong trạng thái tài khoản; khi `REJECTED` / hết hạn trả lý do
- [ ] Thẻ "Nhận định thị trường": nghiêng + nhãn **"Theo luật — chưa kiểm chứng"**, xác suất "Chưa có — chưa hiệu chỉnh", độ tin cậy (chú thích: chất lượng dữ liệu, không phải xác suất), regime, biến động, lý do (drivers), cờ rủi ro / chất lượng, hết hạn; không có → "Chưa có nhận định" + lý do (vd. "Thiếu Lịch sự kiện"); nhãn "Dữ liệu mẫu" khi SAMPLE. OpenAPI + `npm run gen:api`; test API + giao diện

### Bước 7 — Gate GĐ4
- [ ] Mọi case 4-C01..C07 có test (ghi tên test vào bảng case)
- [ ] MarketView sinh liên tục trên dữ liệu thật, vô hiệu đúng, tái dựng được từ manifest, hiển thị trên Tổng quan (kiểm trên máy — mục dưới)
- [ ] **Gate GĐ1 → GĐ2 → GĐ3 đã đóng** (DEC-23)
- [ ] Người dùng xác nhận

## Kiểm trên máy người dùng (điền chi tiết khi tới)

1. **Sau bước 6** — đi cùng một lần dựng lại đã có trong lịch (không dựng thêm, không trong đêm 6a, tránh khung công bố): trang **Tổng quan**, thẻ **"Nhận định thị trường"** có nhãn "Theo luật — chưa kiểm chứng", ô xác suất "Chưa có — chưa hiệu chỉnh", "Tính lúc" cập nhật ít nhất 15 phút / lần khi thị trường mở. Thẻ báo "Chưa có nhận định" → chụp màn hình gửi người phát triển (đọc lý do).
2. **Trong một khung công bố tin lớn** (vd. DOL thứ Năm hoặc NFP 04/12): thẻ hiện cờ "Đang trong cửa sổ công bố" cùng lúc với băng đỏ.
3. **Tái dựng:** lệnh chỉ đọc (viết ở bước 2/5) dựng lại một MarketView từ manifest và so — người phát triển gửi lệnh cụ thể khi tới.

## Prompt cho phiên mới
Đọc CLAUDE.md, PROGRESS.md, rồi docs/ke-hoach/GD4-ke-hoach.md và chỉ các mục liên quan của docs/giai-doan/GD4-snapshot-fusion-marketview.md. Làm bước tiếp theo chưa tick. GĐ4 làm song song (DEC-23) — việc kiểm trên máy của GĐ1/GĐ2/GĐ3 theo docs/ke-hoach/lich-kiem-tren-may.md được ưu tiên; GĐ4 không đóng trước GĐ1 → GĐ2 → GĐ3. Theo DEC-24..27: bắt buộc Technical/Event/Regime; Fusion "nghiêng theo luật" có cờ UNVALIDATED_RULES, bị chặn ở SHADOW/LIVE; giá dẫn, Macro/COT/News chỉ hạ confidence hoặc về NEUTRAL; pUp/pDown để null + cờ UNCALIBRATED. Không bịa số, không gọi là xác suất, không nhìn trước tương lai. Quy trình: thiết kế → code + test (gồm trường hợp xấu) + soát lại kịch bản riêng → tick ở cả hai file, ghi nhật ký GĐ4, cập nhật PROGRESS.md ngắn gọn → chạy test → commit (nhắc mã việc) → push develop → kiểm CI. Người dùng không rành kỹ thuật: tiếng Việt đơn giản, mỗi lần hỏi một câu. Không bao giờ yêu cầu dán mật khẩu / token / khóa API vào chat.
