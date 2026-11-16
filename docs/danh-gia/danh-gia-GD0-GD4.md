# Đánh giá chất lượng độc lập GĐ0 → GĐ4 + khuyến nghị

> **Ngày:** 2026-11-15 · **Commit được đánh giá:** `1a5e974` (nhánh `develop`) · **Prompt:** `docs/prompts/danh-gia-chat-luong-GD0-GD4.md`
> **Pha 1 — chỉ đánh giá, không sửa code.** Mọi khuyến nghị ở mục 5 đang **chờ người dùng duyệt** (Pha 2). Không khuyến nghị nào ở đây là lời hứa lợi nhuận: lợi ích ghi là **kỳ vọng**, phải đo bằng backtest (GĐ6) / paper (GĐ8).

## 0. Tóm tắt một trang

**Kết luận chung.** Phần nền (GĐ0) và dữ liệu (GĐ1) được làm **cẩn thận hơn mức thường gặp**: point-in-time, chỉ-thêm, LIVE khóa, Safety cao nhất, không bịa số, test trường hợp xấu đầy đủ (backend 2261 test đạt, gateway 206, frontend 123; CI xanh). Tôi **không tìm thấy lỗi nào đang gây mất tiền** — đơn giản vì hệ thống **chưa có đường đặt lệnh**. Rủi ro lớn nhất nằm ở **mối nối sắp làm (GĐ5)** và ở **phương pháp**: các luật phân tích là luật sách vở, **chưa có bằng chứng tạo lợi thế**, và một số dữ liệu cần cho backtest **đang không được giữ đủ lâu** (spread, lịch sử giá dài, thông số broker).

**Thang điểm:** 5 = tốt, không thấy vấn đề đáng kể · 4 = tốt, có điểm nhỏ · 3 = đạt cho hiện tại nhưng có khoảng trống sẽ cản giai đoạn sau · 2 = thiếu đáng kể · 1 = không đạt · – = không áp dụng. Bằng chứng từng ô ở mục 2.

| GĐ | 1 Đúng đắn | 2 An toàn tài chính | 3 Phương pháp | 4 Dữ liệu | 5 Vận hành | 6 Kiểm chứng | 7 Bảo mật | 8 Dễ dùng | 9 Bảo trì + tài liệu |
| --- | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: |
| GĐ0 Nền móng | 4 | 5 | – | – | 4 | 4 | 4 | 4 | 3 |
| GĐ1 Dữ liệu vào | 4 | 5 | 3 | 3 | 3 | 4 | 4 | 3 | 3 |
| GĐ2 Orchestrator + làn nhanh | 4 | 4 | 3 | 4 | 4 | 4 | 5 | 4 | 4 |
| GĐ3 6 analyst | 4 | 5 | 3 | 3 | 4 | 4 | 4 | 4 | 3 |
| GĐ4 Snapshot → MarketView | 4 | 4 | 3 | 4 | 4 | 5 | 4 | 3 | 4 |

**5 khuyến nghị quan trọng nhất** (chi tiết mục 5):

1. **KN-01 — BẮT BUỘC (đầu GĐ5):** Risk Engine phải tự hỏi **cổng thật** lúc quyết. Hiện `RiskEngine` hỏi `SafetySupervisor.allows_new_orders()` — hàm này **không thấy lệnh cấm của làn nhanh** (tin CPI/NFP, spread giãn — DEC-20); lệnh cấm chỉ nằm ở `AccountRegistry.allows_new_orders()`. Nối sai là lệnh có thể đi qua giữa giờ ra tin (phát hiện F-02).
2. **KN-02 — BẮT BUỘC (GĐ5):** Tính khối lượng theo **thông số thật của broker** (giá trị tick, cỡ hợp đồng, tiền tài khoản) và **cộng spread + trượt giá + phí** vào rủi ro mỗi lệnh. Hiện là hằng số (`contract_size=100`, `max_spread=0.5`) và rủi ro chỉ tính khoảng cách SL → rủi ro thật **lớn hơn** con số được duyệt.
3. **KN-04 — NÊN, bắt đầu ngay:** Nạp **lịch sử giá dài** (≥ 2–3 năm M15 + H1/H4/D1) từ **broker sẽ giao dịch thật**. Hiện mặc định chỉ 5.000 nến M15 ≈ 52 ngày giao dịch — quá ngắn để backtest qua nhiều trạng thái thị trường.
4. **KN-03 — NÊN, bắt đầu ngay (cần bạn quyết):** Giữ **lâu dài thống kê spread** (theo phút: trung vị / p95 / lớn nhất). Hiện giá theo giây bị **xóa sau 30 ngày** → không có lại được chi phí thật lúc ra tin cho GĐ6.
5. **KN-07 — NÊN, viết trước khi chạy backtest:** **Giao thức đánh giá đăng ký trước** (walk-forward, vùng ngoài mẫu không đụng tới, so với mốc ngẫu nhiên, hiệu chỉnh kiểm định nhiều lần). Bằng chứng: trên dữ liệu mẫu là **bước ngẫu nhiên không có xu hướng thật**, Regime vẫn gắn "TREND rõ" cho **36 %** số nến và Fusion vẫn ra hướng ở ~14 % MarketView — luật ra hướng **cả khi không có gì để đoán**.

**Việc đang chờ bạn:** tài liệu "Quản lý vốn khi trade vàng" (DEC-09) — mục 5.D liệt kê **cần gì** từ tài liệu đó (không tự đặt số). Tính tay theo nguyên tắc bạn đã chốt (rủi ro 0,25–0,5 %/lệnh): với lot nhỏ nhất 0,01 và SL ~19,5 USD (ví dụ RPF-03), cần vốn **≈ 3.900–7.800 USD**; vốn 100 USD thì mỗi lệnh rủi ro ~19,5 % → **không khả thi** theo luật của chính bạn.

## 1. Phạm vi và cách làm

- **Đọc:** `CLAUDE.md`, `PROGRESS.md`, `docs/giai-doan/GD0..GD4` (bảng việc + case + Gate; nhật ký đọc theo chỗ cần), `MT-da-nguoi-dung.md`, kế hoạch GĐ4 + lịch kiểm trên máy, đặc tả `docs/huong-dan-chuc-nang/01–12`, chỉ mục việc GĐ5–GĐ10, thiết kế 03 / 33, mã nguồn các phần được nêu ở mục 2–4.
- **Chạy (trên commit `1a5e974`):** backend `uv run pytest -q` → **2261 passed, 2 skipped** (2 bỏ qua là biến thể "chỉ kho SQL có index" / "không có git checkout" — hợp lý), `ruff` sạch; mt5_gateway **206 passed**, `ruff` sạch; frontend `npm run check` **123 passed**, `npm run build` đạt. CI GitHub Actions run #177 (commit `1a5e974`) **success**.
- **Kịch bản kiểm riêng** (ở scratchpad, không đưa vào repo):
  1. `chk_indicators.py` — EMA / RSI / ATR / ADX / ±DI của dự án so với **TA-Lib 0.8.3** trên 3 chuỗi 3.000 nến (có nến phẳng, khoảng nhảy): EMA, RSI, ATR lệch ≤ 5e-12; ADX / DI lệch tới 0,73 điểm **chỉ ở đoạn khởi động** (TA-Lib khởi tạo bằng tổng 13 giá trị + 1 bước Wilder, dự án theo Wilder gốc tổng 14), hội tụ còn 1e-14 sau ~1.000 nến; Regime dùng cửa sổ 1.184 nến → **khớp**.
  2. `chk_stale_dedupe.py` — Technical + Regime **thật** trên 2.020 nến mẫu; feed ngừng 40 phút giữa giờ mở → kết quả STALE **trùng `output_id`** với kết quả HEALTHY trước đó → **không được lưu** (F-01).
  3. `chk_regime_hours.py` — nhãn Regime theo giờ UTC trên 120 ngày nến mẫu (bước ngẫu nhiên không trôi, có hệ số biến động theo phiên): TREND rõ 36,2 %, TREND mơ hồ 9,8 %, RANGE 54 %; tỉ lệ TREND (gồm mơ hồ) 35 % (giờ Á) ↔ 58 % (17 giờ UTC). **Chỉ minh họa cơ chế** — dữ liệu giả lập, không phải giá thật.
  4. `chk_expired_scan.py` — Postgres 16, 200.000 dòng `analyst_outputs` (~1 năm): truy vấn "kết quả hết hạn" chạy mỗi 2 giây mất **28,9 ms** (quét toàn bảng); thêm index `expires_at` → **0,6 ms** (F-06). DB thử đã xóa.
- **Tra cứu nguồn:** mục 8.

## 2. Bảng chấm điểm có bằng chứng

### GĐ0 — Nền móng

| Tiêu chí | Điểm | Bằng chứng |
| --- | :-: | --- |
| 1 Đúng đắn | 4 | Test khôi phục ACTIVE→PAUSED, LIVE→PAPER, chuỗi `"LIVE"` (0-C01, 0-C02, 0-C21); e2e Keycloak thật trong CI (`ops/scripts/ci_stack.sh`). Trừ 1: `Contract` gốc (`contracts/base.py:6-9`) không kiểm lại khi `model_copy(update=…)` — chỉ `MarketView` tự vá (`contracts/market_view.py:77`); `TradeIntent` (kiểm SL/TP đúng chiều) chưa được bảo vệ (F-10, tiềm ẩn). |
| 2 An toàn tài chính | 5 | LIVE không bao giờ tự bật: `accounts/runtime.py:96-101` (GT_MODE=LIVE → PAPER), `storage/repository.py:1217` (khôi phục LIVE → PAPER); SAMPLE chặn SHADOW/LIVE `api/app.py:271-274`; break-glass chỉ HALT (test quét AST). |
| 5 Vận hành | 4 | `restart: unless-stopped` + healthcheck mọi dịch vụ (`deploy/docker-compose.yml`), sao lưu 24 h × 14 bản + SHA-256 + diễn tập đạt trên máy bạn (DB-09). Trừ 1: thư mục sao lưu **cùng ổ** với DB (`docker-compose.yml:158`) → hỏng ổ là mất cả hai (KN-16); không có cảnh báo ra ngoài (KN-17). |
| 6 Kiểm chứng | 4 | Bảng chỉ-thêm có trigger chặn UPDATE/DELETE (DB-02, 0-C03), audit có actor từ phiên. |
| 7 Bảo mật | 4 | BFF + cookie `__Host-` + `SameSite=Strict`, kiểm Origin (`auth/web.py:111`), `TrustedHostMiddleware` (`api/app.py:554`), token Gateway lưu băm, test quét bí mật trong log (0-C18). Trừ 1: chưa có `Content-Security-Policy` (`frontend/nginx.conf:31-33`); trang quản trị Keycloak mở cho mọi máy trong tailnet (có chống dò mật khẩu). |
| 8 Dễ dùng | 4 | Giao diện tiếng Việt, hộp xác nhận cho thao tác nguy hiểm, hướng dẫn `deploy/README.md` từng bước. |
| 9 Bảo trì + tài liệu | 3 | Trạng thái lệch: `docs/giai-doan/README.md:36-37` (GĐ3 "`[~]` (Technical)", GĐ4 "`[~]`") dù code đã xong; mục "Việc tiếp theo của GĐ0" vẫn ghi chờ người dùng dù đã đóng; `PROGRESS.md` 5.622 byte > quy ước ~5 KB (F-08). |

### GĐ1 — Dữ liệu vào

| Tiêu chí | Điểm | Bằng chứng |
| --- | :-: | --- |
| 1 Đúng đắn | 4 | Bảng case 1A–1G có test; H.15 khớp CSV Bộ Tài chính 12/12; DST ET→UTC kiểm 42/42 ngày; bảng ngày lễ 2026–2027 tôi đối chiếu lại đúng ngày (Good Friday 03/04/2026, 26/03/2027; nghỉ bù 03/07/2026, 18/06/2027, 05/07/2027, 24/12/2027). Trừ 1: nến gap sau khi **Gateway khởi động lại** được gửi `backfill=True` → `available_at = close_time` dù hệ thống biết muộn (`ingestion/candles.py:187-189`, `mt5_gateway/.../sync.py:207`) (F-07); Gate (≥ 5 ngày liên tục, NFP) chưa đạt. |
| 2 An toàn tài chính | 5 | Không có forecast → `INSUFFICIENT_DATA` (1C-C07); nguồn chết lúc công bố → kéo dài cửa sổ chặn (1C-C05); nguồn lịch không khỏe → chặn cả ngày; "0" ≠ "chưa công bố" (1C-C01). |
| 3 Phương pháp | 3 | Chỉ nguồn chính thức (tốt về độ tin), nhưng **thiếu số dự báo** → không đo được mức bất ngờ — trong khi giá kim loại phản ứng với **phần bất ngờ** của tin (Elder, Miao & Ramchander 2012) (DEC-01, quyết định của bạn); thiếu ETF, bán lẻ (hoãn); không có tin địa chính trị. Chỉ số USD tự tính đúng công thức ICE 6 cặp (`market/usd_index.py`). |
| 4 Dữ liệu | 3 | Point-in-time, revision, cách ly tốt. **Thiếu cho backtest:** lịch sử mặc định M15 5.000 nến ≈ 52 ngày, D1 500 (`mt5_gateway/.../config.py:17,121`) (F-05); giá theo giây xóa sau 30 ngày (`storage/quotes.py:109`, `api/app.py:208-212`) (F-04); thông số broker (swap, stops level, đòn bẩy) chỉ giữ trong bộ nhớ (`api/ingest.py:693`); dữ liệu từ MetaQuotes-Demo, chưa phải broker đích; bảng ngày lễ hết ở 2027. |
| 5 Vận hành | 3 | Gateway tự nạp bù từ lịch sử MT5, Task Scheduler khi đăng nhập, đo lệch đồng hồ. Trừ: phụ thuộc máy cá nhân phải **đăng nhập Windows**; chưa có hướng dẫn chống Windows Update tự khởi động lại / tự bật sau mất điện (KN-18); chưa có cảnh báo ra ngoài; Gate 5 ngày chưa chạy. |
| 6 Kiểm chứng | 4 | Lưu payload gốc + revision + `known_at`; test replay ING-34. Trừ 1: spread theo giây chỉ 30 ngày; thông số broker không lưu lịch sử. |
| 7 Bảo mật | 4 | Khóa API chỉ ở `.env`, che theo giá trị và tên tham số, CI quét log với khóa giả (ING-31). Chấp nhận rủi ro điều khoản nguồn (DEC-18) là quyết định của bạn. |
| 8 Dễ dùng | 3 | Trang "Nguồn dữ liệu" rõ. Nhiều bước kiểm bằng lệnh PowerShell + chép kết quả gửi lại (16/11 có 5 việc); lưu ý `findstr` không đọc chữ có dấu — dễ thao tác sai (KN-25). |
| 9 Bảo trì + tài liệu | 3 | File giai đoạn 180 KB; ghi chú lệch (1A-C11 còn ghi "chưa tách nguồn theo server" dù MT-05 lưu trữ xong 11/11; ING-32 còn ghi "hiện tất cả NEEDS_REVIEW"); lịch BLS chép tay phải soát lại hằng năm. |

### GĐ2 — Event Orchestrator + làn nhanh

| Tiêu chí | Điểm | Bằng chứng |
| --- | :-: | --- |
| 1 Đúng đắn | 4 | `jobKey` duy nhất trên Postgres (8 luồng → 1), debounce không bỏ công bố, deadline / retry / dead-letter (`orchestrator/dispatcher.py`). Đầu mối "thứ tự chữ cái" đã kiểm (mục 4): không có phụ thuộc bị đọc bản cũ. Gate (replay trên máy, độ trễ NFP 04/12) chưa chạy. |
| 2 An toàn tài chính | 4 | Làn nhanh vượt ngân sách 10 s → mặc định chặn (2-C09); đồng hồ lệch → orchestrator dừng → Safety chặn. Trừ 1: lệnh cấm chỉ được `AccountRegistry` đọc; `RiskEngine` lại hỏi `SafetySupervisor` (F-02 → KN-01). |
| 3 Phương pháp | 3 | 15 phút sau số HIGH, spread > 3 × trung vị 60 phút: quy ước hợp lý, có phiên bản (DEC-20) nhưng chưa hiệu chỉnh; RSS 15 phút/lần → thông cáo Fed ngoài lịch có thể biết trễ tới 15 phút (đã nói với bạn). |
| 4 Dữ liệu | 4 | Sự kiện suy từ dữ liệu đã lưu, bảng chỉ-thêm, replay được. |
| 5 Vận hành | 4 | Khôi phục job dở dang sau khởi động lại (2-C05), trang Pipeline. Trừ 1: `expired_unreplaced` quét toàn bảng mỗi 2 giây — 29 ms ở ~1 năm dữ liệu, tăng dần (F-06). |
| 6 Kiểm chứng | 4 | `correlation_id`, nguyên nhân, phiên bản bộ xử lý trong `job_key`, nhật ký từng lần thử. |
| 7 Bảo mật | 5 | Lỗi job chỉ ghi **mã loại lỗi**, không ghi thông điệp (tránh lộ khóa / URL) (`dispatcher.py` `error_code`). |
| 8 Dễ dùng | 4 | Băng "Đang chặn … (tới …)", trang Pipeline. |
| 9 Bảo trì + tài liệu | 4 | Thiết kế 25 đầy đủ, `ROUTER_VERSION` đổi khi đổi bảng định tuyến. |

### GĐ3 — 6 analyst (bản luật)

| Tiêu chí | Điểm | Bằng chứng |
| --- | :-: | --- |
| 1 Đúng đắn | 4 | Chỉ báo khớp TA-Lib (kịch bản 1); mọi analyst có test 3-C01..C10, gồm "thêm dữ liệu tương lai không đổi kết quả cũ". Trừ 1: kết quả STALE với cùng nến **không được lưu** (F-01, kịch bản 2). |
| 2 An toàn tài chính | 5 | Không có xác suất; `confidence` = chất lượng dữ liệu; News mặc định tắt, bài báo là dữ liệu không tin cậy, trần ngân sách cứng; COT gắn `COT_LAGGED`. |
| 3 Phương pháp | 3 | Luật sách vở (EMA 20/50, ADX 25/20 của Wilder, ATR ×2) — hợp lý cho bản đầu và **ghi rõ chưa hiệu chỉnh** (13 chỗ trong 9 module). Thiếu: **phiên giao dịch / giờ trong ngày** (không module nào dùng), chuẩn hóa biến động theo giờ (Batten et al. 2017: biến động kim loại quý có chu kỳ trong ngày); Macro giả định vàng ngược chiều lợi suất thực — quan hệ này **yếu đi rõ từ 2022** (RBC: tương quan ~84 % giai đoạn 2005–2021 → ~3 % 2022–2023); nhãn TREND xuất hiện 36 % trên bước ngẫu nhiên (kịch bản 3). |
| 4 Dữ liệu | 3 | Macro cần ≥ 21 quan sát, COT cần ≥ 52 tuần → phụ thuộc nạp bù `h15-bu` / `cot-bu` (16/11); ETF chưa có. |
| 5 Vận hành | 4 | `ensure_fresh` dự phòng, TTL theo nhịp, lỗi → job thử lại / dead-letter. |
| 6 Kiểm chứng | 4 | `output_id` có phiên bản + băm đầu vào, kho chỉ-thêm, đặc trưng lưu đủ cho GĐ7. Trừ 1: F-01 (mất dấu vết STALE). |
| 7 Bảo mật | 4 | Khóa Anthropic chỉ ở `.env`; chống prompt injection theo thiết kế 32. |
| 8 Dễ dùng | 4 | 6 thẻ tiếng Việt có ghi "chưa hiệu chỉnh"; còn thuật ngữ ADX / Regime / COT. |
| 9 Bảo trì + tài liệu | 3 | Technical chưa chuyển sang khung chung (id kiểu cũ, đường `append` riêng); ngưỡng rải rác, chưa có sổ tham số chung (KN-08). |

### GĐ4 — Snapshot → Quality Gate → Fusion → MarketView

| Tiêu chí | Điểm | Bằng chứng |
| --- | :-: | --- |
| 1 Đúng đắn | 4 | Lỗi 5b (Technical id kiểu cũ → không bao giờ có MarketView) đã sửa, `kiem-mv` tái dựng 542/542. Trừ 1: **không có test hồi quy đầu-cuối được commit** chạy analyst thật → MarketView; `tests/test_fusion_runner.py` vẫn dùng output tự dựng (`out(...)`) — đúng loại bẫy của bài học 5b (F-09). |
| 2 An toàn tài chính | 4 | Hợp đồng bắt `p_up/p_down = null` + cờ `UNCALIBRATED`/`UNVALIDATED_RULES`; Risk chặn SHADOW/LIVE; Gate `REJECTED` vô hiệu MarketView còn hạn. Trừ 1: thẻ hiện **"Độ tin cậy 90 %" cạnh "LONG"** (`frontend/src/pages/overview/MarketViewCard.tsx:119`) — người chưa trade dễ đọc thành "90 % giá tăng" (F-03); Risk nhận MarketView do bên gọi đưa. |
| 3 Phương pháp | 3 | DEC-26 (giá dẫn, nhóm khác chỉ hạ; Technical + Regime là **một** nhóm) là cách thận trọng, tránh đếm phiếu tương quan — đúng tinh thần đặc tả 05. Nhưng hướng gốc là luật theo xu hướng **chưa kiểm chứng**; hệ số 0,9 / 0,5 / 30 phút (`quality_gate.py:85`, `fusion.py:26,28`) chưa có giao thức hiệu chỉnh cụ thể. |
| 4 Dữ liệu | 4 | Snapshot + manifest + báo cáo Gate + MarketView + lý do vô hiệu đều chỉ-thêm → GĐ6/GĐ7 dùng lại được. |
| 5 Vận hành | 4 | Fusion là việc mỗi nhịp, lỗi một nguồn không chặn nguồn khác, khởi động lại tính lại idempotent. |
| 6 Kiểm chứng | 5 | `kiem-mv` dựng lại snapshot + tính lại Gate + Fusion so bản đã lưu; id xác định. |
| 7 Bảo mật | 4 | API MarketView theo tài khoản qua `Guard`. |
| 8 Dễ dùng | 3 | F-03; còn chữ tiếng Anh "LONG / SHORT / Regime / MarketView / Bias thị trường"; có chú thích nhưng chú thích ẩn trên điện thoại. |
| 9 Bảo trì + tài liệu | 4 | Thiết kế 33 kỹ; đầu file GĐ4 còn ghi "chờ người dùng duyệt trước khi code". |

## 3. Phát hiện

| Mã | Mức | Phát hiện | Bằng chứng | Hậu quả | Đề xuất |
| --- | --- | --- | --- | --- | --- |
| F-01 | Thấp | Kết quả **STALE** của Technical / Regime khi feed ngừng (cùng nến cuối) có **cùng `output_id`** với kết quả HEALTHY trước đó → kho bỏ qua, không lưu | Kịch bản 2: "cùng output_id với lần 1? True — lưu được? False"; id: `analysts/technical.py:193`, băm `analysts/regime.py:138` không gồm trạng thái; `storage/analyst_outputs.py:197` | MarketView **không** bị ảnh hưởng (kết quả hết hạn bị loại → `REJECTED`). Thẻ hiện "hết hạn" thay vì "dữ liệu cũ"; mất dấu vết STALE cho kiểm toán / GĐ7 | KN-15 |
| F-02 | **Cao (tiềm ẩn)** | `RiskEngine` hỏi `SafetySupervisor.allows_new_orders()` — chỉ xét ACTIVE, **không** xét lệnh cấm làn nhanh (DEC-20) | `risk/engine.py:73` → `safety/supervisor.py:67`; lệnh cấm chỉ ở `accounts/runtime.py:153-166`. RSK-01 `[x]` ghi "Kiểm Safety" dễ hiểu nhầm là đã đủ | Chưa gây hại (chưa có luồng lệnh). Nếu GĐ5 nối theo kiểu dữ liệu hiện tại → lệnh **lọt qua giữa giờ ra tin / spread giãn** | KN-01 |
| F-03 | Trung bình | "Độ tin cậy" hiện dạng **phần trăm** cạnh hướng LONG/SHORT | `MarketViewCard.tsx:118-119` `formatPercent(view.confidence)`; chú thích "không phải xác suất" chỉ trong tooltip | Người chưa trade đọc thành xác suất thắng → tin sai vào một con số chưa hiệu chỉnh (trái tinh thần CLAUDE.md) | KN-13 |
| F-04 | Trung bình | Spread theo giây bị **xóa sau 30 ngày**, không có bản tổng hợp lâu dài | `storage/quotes.py:109`, `api/app.py:208-212`; ING-33 (bạn chọn giữ 30 ngày) | GĐ6 không có phân bố spread thật theo giờ / quanh tin cho mô hình chi phí; dữ liệu đã xóa không lấy lại được | KN-03 (cần bạn quyết) |
| F-05 | Trung bình | Lịch sử giá ngắn: M15 5.000 nến (~52 ngày), H1 2.000, H4 1.000, D1 500 | `mt5_gateway/src/mt5_gateway/config.py:17,121` | Backtest GĐ6 chỉ phủ 1 trạng thái thị trường → kết quả không đáng tin | KN-04 |
| F-06 | Thấp | `expired_unreplaced` (mỗi 2 giây) quét toàn bảng `analyst_outputs` — không có index `expires_at` | Kịch bản 4: 28,9 ms → 0,6 ms khi có index (200.000 dòng, Postgres 16) | Tốn CPU tăng theo thời gian; chưa ảnh hưởng đúng / sai | KN-20 |
| F-07 | Thấp | Nến gap gửi lại khi **Gateway khởi động lại** mang `available_at = close_time` (cờ `BACKFILL`) dù hệ thống biết muộn | `ingestion/candles.py:187-189`; `sync.py:207-216` gửi `backfill=True` | Replay "như hệ thống đã thấy" lạc quan hơn thực tế quanh lúc mất kết nối (đặc tả 02: "dữ liệu đến muộn phải mang `ingestedAt` thực tế để backtest không nhìn trước") | KN-24 |
| F-08 | Thấp | Trạng thái / ghi chú lệch code | mục 2 GĐ0-9, GĐ1-9; `deploy/docker-compose.yml:114` ghi "chưa nhận người dùng thứ hai… (DEC-12)" trong khi DEC-12 đã chốt | Người đọc sau hiểu sai tiến độ | KN-22 |
| F-09 | Thấp | Không có test đầu-cuối được commit với analyst **thật** → MarketView | `tests/test_fusion_runner.py` dùng `out(...)` tự dựng; kiểm đầu-cuối 5b / 6 chỉ ở kịch bản soát | Lỗi loại 5b có thể tái phát mà test vẫn xanh | KN-14 |
| F-10 | Thấp (tiềm ẩn) | `model_copy(update=…)` của hợp đồng gốc không kiểm lại | `contracts/base.py:6-9`; chỉ `MarketView` vá | GĐ5 dùng `TradeIntent` / `RiskDecision` có thể lén tạo bản ghi sai (vd. SL sai chiều) | KN-21 |

Không có phát hiện nào thuộc loại **nhìn trước tương lai trong quyết định thật** hay **bịa số**.

## 4. Kết quả kiểm các đầu mối đã biết

| Đầu mối | Kết quả |
| --- | --- |
| Job cùng sự kiện chạy theo **thứ tự chữ cái** (`dispatcher.py:228`) | Không thấy phụ thuộc đọc bản cũ: (a) `REGIME` trước `TECHNICAL` — Regime không dùng Technical; Regime dùng Macro `known_by = giờ đóng nến` (`regime.py:242`) → **luôn là Macro của nến trước** (trễ 1 nến, tất định, ghi vào thiết kế nên nêu rõ); (b) `EVENT_CALENDAR` trước `FAST_LANE` — analyst Lịch tự tính cửa sổ từ bản ghi lịch, không đọc lệnh cấm đã ghi; (c) `INVALIDATE_MARKETVIEW` trước job tính lại — an toàn (vô hiệu trước, MarketView mới sinh ở nhịp sau); (d) Fusion là việc mỗi nhịp chạy sau mọi job; Technical ≠ Regime nến → `TIMESTAMP_CONFLICT` chặn. |
| `output_id` kiểu cũ của Technical | `_check_scope` chỉ dùng trong `append_scoped`; Technical đi đường `append` riêng → không bị chặn; Snapshot kiểm phạm vi bằng cột kho, `_belongs` nhận dạng kiểu cũ. Không còn chỗ nào kiểm phạm vi chỉ bằng id. Liên quan: F-01 (id không gồm trạng thái). |
| Bộ đệm `_last` của `FusionRunner` (`fusion_runner.py:48`) | Khóa `(snapshot_id, report_id)` không gồm thời điểm. Vì hạn snapshot = hạn sớm nhất của đầu vào bắt buộc (≤ ~17 phút) < trần 30 phút, đầu vào hết hạn luôn làm snapshot đổi → không có khoảng trống sai. Lỗi → xóa đệm; khởi động lại → tính lại idempotent. **Không có lỗi**; chỉ lưu ý: nếu sau này một analyst bắt buộc có TTL > 30 phút thì có thể hở MarketView (hướng an toàn). |
| `model_copy` không kiểm lại | Mã chạy thật chỉ dùng ở `api/accounts.py:534` (model trạng thái Gateway, không có kiểm tra cần bảo vệ). Rủi ro là tiềm ẩn cho GĐ5 → F-10. |
| Risk Engine chưa dùng trong luồng thật | Đúng; thêm hai lỗ hổng thiết kế phải xử lý trước khi nối: F-02 và cách tính rủi ro (KN-02). |
| Hệ số GĐ4 chưa hiệu chỉnh | Đúng, ghi rõ trong mã + thiết kế 33 §115; thiếu **giao thức** hiệu chỉnh cụ thể → KN-07, KN-08. |

## 5. Khuyến nghị

Ký hiệu công sức: S (≤ 1 buổi), M (vài buổi), L (≥ 1 tuần). "Cần bạn quyết": có / không.

### 5.A BẮT BUỘC trước khi nối Strategy → Risk → lệnh (đầu GĐ5)

| Mã | Việc | GĐ | Lợi ích kỳ vọng + bằng chứng | Cách đo | Công sức | Rủi ro | Cần bạn quyết |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **KN-01** | Risk Engine tự đọc cổng thật lúc quyết: `AccountRegistry.allows_new_orders(tài khoản)` (Safety + khóa người dùng + lệnh cấm làn nhanh) và `MarketViewStore.current(nguồn, now)` (thấy bị vô hiệu); bỏ tham số `SafetySupervisor` / MarketView do bên gọi đưa. Sửa ghi chú RSK-01 | GĐ5 | Chặn lệnh trong giờ ra tin / spread giãn như DEC-20 đã chốt (F-02) | Test: lệnh cấm làn nhanh đang hiệu lực + Safety ACTIVE → `REJECTED`; MarketView bị vô hiệu sau khi tạo intent → `REJECTED` | S | Thấp | không |
| **KN-02** | Khối lượng theo thông số **thật** của broker (giá trị tick / cỡ hợp đồng / tiền tài khoản từ GW-09, không hằng số `engine.py:42`), rủi ro mỗi lệnh = khoảng SL **+ spread + trượt giá ước tính + phí**; ngưỡng spread theo phân bố của chính broker thay cho `0,5` cố định (`engine.py:28`) | GĐ5 | Rủi ro thật không vượt mức duyệt (0,25–0,5 %); hiện `engine.py:100` chỉ tính khoảng SL → rủi ro bị **đánh giá thấp** | Test tính tay: tài khoản USD / tài khoản khác tiền / broker 1 lot ≠ 100 oz; so lỗ thật trong paper (GĐ8) với rủi ro được duyệt | M | Thấp | không |

### 5.B Bắt đầu ngay vì cần thời gian tích lũy

| Mã | Việc | GĐ | Lợi ích kỳ vọng + bằng chứng | Cách đo | Công sức | Rủi ro | Cần bạn quyết |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **KN-03** | Lưu **vĩnh viễn** thống kê spread theo phút cho mọi nguồn (trung vị, p95, lớn nhất, số tick, bid/ask đầu–cuối); giữ nguyên xóa giá theo giây sau 30 ngày (hoặc nâng hạn giữ) | GĐ1 (ING-08/33) | Mô hình chi phí GĐ6 dùng spread **thật** theo giờ và quanh tin; biến động + khối lượng tăng mạnh lúc ra tin (Elder et al. 2012) nên spread trung bình không đại diện. Ước ~1.380 dòng/ngày/nguồn — nhỏ so với 0,6 GB/năm đã đo | Phân bố spread theo giờ / theo cửa sổ tin trong báo cáo GĐ6 | S–M | Thấp | **có** — đổi chính sách ING-33 bạn đã chốt |
| **KN-04** | Nạp **lịch sử dài** (M15 ≥ 2–3 năm + H1/H4/D1) từ **broker sẽ giao dịch thật** — tăng `GT_HISTORY_BARS` / trần khung lớn hoặc nhập CSV xuất từ MT5 (ING-05), nhãn `BACKFILL` | GĐ1 | Backtest phủ nhiều trạng thái (xu hướng, đi ngang, biến động cao); 52 ngày hiện có không đủ (F-05) | Báo cáo GĐ6 ghi khoảng dữ liệu + số đoạn của từng regime | S (cấu hình) + kiểm trên máy | Lịch sử broker demo có thể khác broker thật | **có** — chọn broker đích (một phần DEC-09) |
| **KN-05** | Lưu lịch sử **thông số broker + tài khoản** (chỉ-thêm, ghi khi đổi): swap long/short, stops / freeze level, cỡ hợp đồng, giá trị tick, đòn bẩy, margin; equity theo giờ | GĐ1 (GW-09) | Swap đổi theo lãi suất; GĐ5 (RSK-03/08/09), GĐ6 (chi phí qua đêm), GĐ9 (đối soát) cần giá trị **tại thời điểm** — hiện chỉ trong bộ nhớ (`api/ingest.py:693`) | Truy được swap tại ngày bất kỳ sau khi bắt đầu lưu | S | Thấp | không |
| KN-06 | Nhập tay số dự báo (ING-18) cho CPI / NFP / FOMC / PCE trước mỗi kỳ | GĐ1 | Chỉ có ích nếu chiến lược muốn **giao dịch sau tin**: phản ứng giá gắn với phần bất ngờ (Elder et al. 2012). Nếu chiến lược chỉ **tránh** tin thì không cần. Không có nguồn lịch sử dự báo miễn phí → càng muộn càng ít dữ liệu | Số kỳ có dự báo; tương quan bất ngờ ↔ biến động sau tin trên dữ liệu của bạn | S + công nhập mỗi tuần | Nhập sai số | **có** — liên quan DEC-01 |

### 5.C Chuẩn bị cho GĐ6 (backtest đáng tin)

| Mã | Việc | GĐ | Lợi ích kỳ vọng + bằng chứng | Cách đo | Công sức | Rủi ro | Cần bạn quyết |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **KN-07** | **Giao thức đánh giá đăng ký trước** (viết trước khi xem kết quả): walk-forward; một đoạn ngoài mẫu **không đụng tới** tới lần cuối; số lệnh tối thiểu; chỉ số sau chi phí (kỳ vọng / lệnh, sụt giảm lớn nhất, hệ số lợi nhuận); **so với mốc**: vào lệnh ngẫu nhiên cùng SL/TP/thời gian giữ, không lọc, mua giữ; hiệu chỉnh kiểm định nhiều lần (Deflated Sharpe, PBO bằng CSCV); kết quả theo regime và theo phiên | GĐ6 (viết cuối GĐ5) | Tránh "backtest đẹp do khớp quá mức": PBO = xác suất chiến lược tốt nhất trong mẫu thua ở ngoài mẫu (Bailey et al. 2017). Bằng chứng nội bộ: luật hiện tại ra hướng cả trên **bước ngẫu nhiên** (36 % nến TREND rõ — kịch bản 3; 27 LONG + 51 SHORT / 544 MarketView trong lần soát 5b trên dữ liệu mẫu) | Có báo cáo PBO + Deflated Sharpe + so mốc ngẫu nhiên; tiêu chí BT-04 bạn duyệt **trước** khi chạy | M | Không phát hiện được lợi thế (đó là kết quả trung thực) | **có** — duyệt tiêu chí (BT-04) |
| KN-08 | **Sổ tham số** chung: mọi ngưỡng chưa hiệu chỉnh (13 chỗ ghi "chưa hiệu chỉnh" trong 9 module + DEC-20 + R3/R5) với giá trị, phiên bản, lý do, tham số nào được phép tối ưu ở GĐ6 | GĐ5 (tài liệu) | Mỗi tham số được tối ưu thêm làm tăng nguy cơ khớp quá mức (Bailey et al. 2017); biết rõ "bao nhiêu nút vặn" trước khi vặn | Số tham số tối ưu ghi trong báo cáo GĐ6 | S | Thấp | không |
| KN-09 | Khớp lệnh trong nến: M15 không cho biết SL hay TP chạm trước. GĐ6 dùng quy tắc bảo thủ (cùng nến chạm cả hai → tính SL trước) và/hoặc nạp thêm M1 (Gateway hiện từ chối M1 — `tests/test_multi_terminal.py:270`) | GĐ6 (+ GĐ1 nếu nạp M1) | Tránh kết quả lạc quan giả do thứ tự chạm trong nến | So kết quả M15-bảo thủ với M1 trên cùng đoạn | S (quy tắc) / M (M1) | M1 tăng dung lượng ~15× M15 | **có** — nạp M1 hay không |
| KN-10 | Yếu tố **phiên giao dịch / giờ trong ngày**: đặc trưng phiên (Á / London / New York, giờ ra tin 8:30 ET, giờ fix London) + so biến động với **cùng khung giờ** các ngày trước | GĐ3 (phiên bản mới) → đo GĐ6 | Biến động kim loại quý có chu kỳ trong ngày (Batten et al. 2017); không chuẩn hóa thì HIGH_VOL / TREND nghiêng theo giờ (kịch bản 3: TREND 35 % giờ Á ↔ 58 % 17 h UTC trên dữ liệu mẫu — chỉ minh họa cơ chế) | Hiệu quả theo phiên trong báo cáo GĐ6; tỉ lệ nhãn theo giờ trên dữ liệu thật (`cli nguong` mở rộng) | M | Thêm tham số (đưa vào KN-08) | không |
| KN-11 | Đo vai trò Macro trong Fusion (bỏ / giữ "Macro ngược chiều → × 0,5") | GĐ6 | Quan hệ vàng – lợi suất thực yếu đi rõ từ 2022 (RBC: ~84 % → ~3 %) → luật "ngược chiều lý thuyết" có thể hạ nhầm tín hiệu tốt | Thí nghiệm bỏ-từng-phần (ablation) trên ngoài mẫu | S | Thấp | không |

### 5.D Quản lý vốn (DEC-09) — cần gì từ tài liệu "Quản lý vốn khi trade vàng"

Nguyên tắc đã chốt: rủi ro **0,25–0,5 %/lệnh** + ngưỡng lỗ ngày / tuần là **luật cứng**; 4–5 %/ngày chỉ tham khảo, không dùng để nới rủi ro. **KN-12 (BẮT BUỘC trước Gate GĐ5, cần bạn):** tôi **không tự đặt số**; khi bạn gửi lại tài liệu, cần lấy ra (hoặc bạn trả lời trực tiếp):

1. Vốn thật dự định + **tiền tệ tài khoản**; broker, loại tài khoản (Standard / ECN / cent), đòn bẩy, lot nhỏ nhất, bước lot, cỡ hợp đồng XAUUSD, phí / lot, swap.
2. Rủi ro mỗi lệnh chốt ở **0,25 % hay 0,5 %** (hay theo bậc).
3. Ngưỡng lỗ **ngày** và **tuần** (con số), mốc reset (giờ nào, múi giờ nào), làm gì khi chạm (dừng tới kỳ sau; mở lại tự động hay phải bấm).
4. Chuỗi thua liên tiếp: sau bao nhiêu lệnh thì giảm rủi ro / dừng; điều kiện quay lại mức cũ.
5. Sụt giảm tối đa từ đỉnh (drawdown) → dừng hẳn, chờ xem xét.
6. Số lệnh mở cùng lúc / tổng rủi ro mở tối đa; có cho thêm lệnh cùng chiều không.
7. Giữ lệnh qua đêm / cuối tuần / qua tin lớn: cấm hay cho (kèm cách tính rủi ro gap).
8. Có tăng rủi ro khi đang lãi không (khuyến nghị thận trọng: **không** tăng sau thua; tăng sau lãi chỉ theo luật viết sẵn).
9. Rút lợi nhuận / nạp thêm vốn ảnh hưởng mức rủi ro thế nào.

**Khả thi theo số học (tính tay, giả định ghi rõ):** XAUUSD 0,01 lot = 1 oz (khi 1 lot = 100 oz — phải kiểm lại theo broker) → mỗi 1 USD giá chạy = 1 USD lãi/lỗ. Với SL = 1,5 × ATR M15 và ATR ≈ 13 USD (con số ví dụ của RPF-03, **chưa đo trên dữ liệu thật**) → SL ≈ 19,5 USD/lệnh ở lot nhỏ nhất. Vốn tối thiểu = 19,5 / 0,5 % ≈ **3.900 USD**; ở 0,25 % ≈ **7.800 USD** (chưa cộng spread + phí). Vốn 100 USD → mỗi lệnh rủi ro ~19,5 % vốn → hệ thống phải **từ chối** (5-C01). GĐ5 tính lại bằng ATR thật của broker.

### 5.E NÊN (nâng rõ chất lượng)

| Mã | Việc | GĐ | Lợi ích kỳ vọng + bằng chứng | Cách đo | Công sức | Rủi ro | Cần bạn quyết |
| --- | --- | --- | --- | --- | --- | --- | --- |
| KN-13 | Thẻ "Nhận định thị trường": bỏ dạng % của "Độ tin cậy" (đổi tên "Chất lượng dữ liệu & đồng thuận", thang Cao / Trung bình / Thấp); "LONG / SHORT" → "Nghiêng tăng / Nghiêng giảm (chưa kiểm chứng)" | GĐ4 | Tránh đọc nhầm thành xác suất thắng (F-03) | Test giao diện: không có ký tự "%" cạnh nhận định; hỏi lại bạn có hiểu đúng không | S | Thấp | không |
| KN-14 | Test hồi quy **đầu-cuối** được commit: nến → Technical / Regime / Lịch **thật** → orchestrator → MarketView (+ trường hợp lịch hỏng → vô hiệu) | GĐ4 | Lỗi loại 5b không tái phát âm thầm (F-09) | Test đỏ khi cố ý đổi id Technical | S | Thấp | không |
| KN-15 | Đưa trạng thái đánh giá (vd. `expected_last_close`, trạng thái nguồn) vào phần băm `output_id` của Technical / Regime (tăng phiên bản) để kết quả STALE được lưu | GĐ3 | Dấu vết đầy đủ cho kiểm toán + GĐ7; thẻ báo đúng "dữ liệu cũ" (F-01) | Kịch bản 2 cho "lưu được? True" | S | Đổi phiên bản → id mới (đúng quy tắc 3-C07) | không |
| KN-16 | Sao lưu **ra ngoài ổ máy** (thư mục đồng bộ OneDrive / Google Drive, hoặc ổ USB / ổ thứ hai), chép tự động hằng ngày | Vận hành (GĐ0 DB-09) | Hỏng ổ / mất máy không mất cả DB lẫn bản sao lưu (0-C04 mới phủ mất volume) | Diễn tập khôi phục từ bản ở nơi thứ hai | S | Bản sao lưu chứa dữ liệu tài khoản → nơi lưu phải riêng tư | **có** — chọn nơi lưu |
| KN-17 | Cảnh báo ra ngoài (vd. Telegram / email) khi backend / Gateway / MT5 mất > N phút, sao lưu lỗi, ổ gần đầy | GĐ8 (OPS-09) — có thể làm sớm | Biết ngay khi hở dữ liệu ban đêm → giữ được chuỗi "≥ 5 ngày liên tục" và dữ liệu tích lũy | Số sự cố được báo / số sự cố thật | M | Cần token bot (nhập qua form bảo mật, không qua chat) | **có** — làm sớm hơn GĐ8 hay không |
| KN-18 | Hướng dẫn Windows: giờ hoạt động / tạm hoãn Windows Update trong đợt kiểm; BIOS "bật lại khi có điện"; Docker Desktop "Start when you sign in"; cân nhắc tự đăng nhập Windows | Vận hành (tài liệu) | Gateway chạy khi **đăng nhập** (GW-06) → máy tự khởi động lại mà không ai đăng nhập là mất dữ liệu | Số lần hở dữ liệu do khởi động lại | S | Tự đăng nhập giảm bảo mật máy | **có** — tự đăng nhập hay không |
| KN-19 | Ghim phiên bản khi dựng trong đợt kiểm Gate (`GT_BRANCH` = tag, compose đã hỗ trợ) thay vì `develop` mới nhất | Vận hành | Không đưa code chưa chắc chắn vào giữa đợt đếm 5 ngày | — | S | Quên đổi tag khi cần bản sửa lỗi | không |

### 5.F CÓ THỂ

| Mã | Việc | GĐ | Ghi chú | Công sức |
| --- | --- | --- | --- | --- |
| KN-20 | Index `expires_at` cho `analyst_outputs` (migration mới) | GĐ2 | F-06: 29 ms → 0,6 ms / lần | S |
| KN-21 | `Contract.model_copy` luôn kiểm lại (đưa bản vá của `MarketView` lên lớp gốc) | GĐ0 | F-10, nên làm trước khi GĐ5 dùng `TradeIntent` | S |
| KN-22 | Dọn trạng thái / ghi chú lệch; rút `PROGRESS.md` < 5 KB | Tài liệu | F-08 | S |
| KN-23 | `LIVE_CHECKLIST`: mục đo được bằng máy (`reconciliation_clean`, `required_sources_healthy`) do hệ thống tự kiểm, không chỉ tick tay (`modes/manager.py:85`) | GĐ10 | | M |
| KN-24 | Quy ước point-in-time cho nến `BACKFILL` sau khi Gateway khởi động lại (backend coi nến mới hơn nến cuối đã biết là "tới muộn", hoặc backtest dùng `max(ingested_at, available_at)`) | GĐ6 (+ GĐ1) | F-07 | S |
| KN-25 | Gom lệnh kiểm trên máy (replay, `kiem-mv`, `dung-luong`, `nguong`) thành một lệnh / trang "Tự kiểm" chỉ đọc, xuất một file | Vận hành | Giảm thao tác PowerShell cho bạn | M |
| KN-26 | Thêm `Content-Security-Policy`; cân nhắc giới hạn trang quản trị Keycloak | GĐ0 | | S |

## 6. Giai đoạn sau cần gì từ GĐ0–GĐ4 — đang lưu đủ chưa

| GĐ sau cần | Đang có | Thiếu → KN |
| --- | --- | --- |
| GĐ5: thông số broker, equity, margin | Đọc mỗi nhịp tim (GW-09) | Không lưu lịch sử → KN-05; sizing hằng số → KN-02 |
| GĐ5: cổng chặn lúc quyết | Safety + lệnh cấm làn nhanh + MarketView `current()` | Risk chưa đọc đúng cổng → KN-01 |
| GĐ6: giá dài, nhiều regime | M15 ~52 ngày, D1 500 | KN-04 |
| GĐ6: spread / trượt giá thật | Spread theo giây 30 ngày; spread mỗi nến M15 (ý nghĩa giá trị MT5 cần xác minh) | KN-03 |
| GĐ6: swap / phí theo thời điểm | Không lưu | KN-05 |
| GĐ6: thứ tự chạm SL / TP trong nến | Chỉ M15 | KN-09 |
| GĐ6 / GĐ7: đầu vào + quyết định lịch sử | analyst output, snapshot, báo cáo Gate, MarketView, lý do vô hiệu — đều chỉ-thêm | Kết quả STALE không lưu → KN-15 |
| GĐ7: nhãn không rò rỉ | Nến có `available_at`, revision | Quy ước nến BACKFILL → KN-24 |
| GĐ7: mức bất ngờ của tin | Không có dự báo (DEC-01) | KN-06 (tùy chiến lược) |
| GĐ8 / GĐ10: cảnh báo, checklist | Dashboard | KN-17, KN-23 |

## 7. Những gì đã kiểm mà không thấy vấn đề

- Chỉ báo EMA / RSI / ATR / ADX / ±DI so TA-Lib (kịch bản 1).
- Công thức chỉ số USD: hằng số 50,14348112 và 6 trọng số đúng công thức ICE; thiếu / lệch nến / cũ > 30 phút → "không đủ dữ liệu" (`market/usd_index.py`).
- Bảng ngày lễ 2026–2027: đúng ngày + quy tắc nghỉ bù.
- LIVE không tự bật (biến môi trường, khôi phục, chuỗi), SAMPLE chặn SHADOW / LIVE, break-glass chỉ HALT.
- Point-in-time khi đọc nến (`available_at ≤ as_of`, revision mới nhất đã biết), snapshot ném lỗi khi `as_of > at`, Gate ném lỗi khi đánh giá trước lúc snapshot tồn tại.
- Analyst Lịch: hạn kết quả rơi đúng **đầu cửa sổ** sắp tới → MarketView hết hạn đúng lúc cửa sổ mở (`analysts/event.py` phần "hết hạn").
- Quality Gate / Fusion: luật đúng thiết kế 33; `report_id` / `market_view_id` xác định; Gate `REJECTED` vô hiệu MarketView còn hạn.
- Host / Origin / cookie / che bí mật trong log; `X-Forwarded-Host` từ client không vượt được `TrustedHostMiddleware` (kiểm theo `Host`).
- Index tra cứu `analyst_outputs` theo (analyst, symbol, khung, nguồn, feed, as_of) có sẵn.
- CI xanh trên commit đánh giá; bộ test đều đạt như `PROGRESS.md` ghi.

## 8. Giới hạn của lần đánh giá

- **Không có dữ liệu giá thật.** Yêu cầu tải dữ liệu vàng 15 phút công khai để đo trên giá thật **bị từ chối quyền** trong phiên này; mọi con số về nhãn Regime / tỉ lệ hướng là trên **dữ liệu mẫu giả lập** (chỉ chứng minh cơ chế, không phải độ lớn thật). Cần đo lại trên dữ liệu máy bạn (`cli nguong`, `kiem-mv`).
- Không chạy lại trên **TimescaleDB** (chỉ có ở CI — CI xanh); kịch bản 4 chạy trên Postgres 16 thường.
- Không kiểm trên **máy Windows**: Gateway, Task Scheduler, Tailscale, sao lưu chỉ đánh giá qua mã + tài liệu + nhật ký bạn đã kiểm.
- Không soát lại từng dòng lịch chép tay (BLS 2026–2027) và các bộ đọc nguồn (BEA, DOL, CFTC) ngoài việc đọc test + nhật ký.
- Không đọc toàn bộ nhật ký GĐ1 (180 KB); đánh giá dựa trên bảng việc / case và phần nhật ký liên quan.
- Mức độ quan trọng của từng khuyến nghị là **nhận định chuyên môn**; lợi ích chỉ được xác nhận sau GĐ6 / GĐ8.

## 9. Nguồn tham khảo

- Bailey, D., Borwein, J., López de Prado, M., Zhu, Q. (2017). *The Probability of Backtest Overfitting*. Journal of Computational Finance 20(4). [SSRN](https://papers.ssrn.com/abstract=2326253) · [Risk.net](https://www.risk.net/journal-of-computational-finance/2471206/the-probability-of-backtest-overfitting)
- Bailey, D., López de Prado, M. (2014). *The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality*. Journal of Portfolio Management 40(5).
- Elder, J., Miao, H., Ramchander, S. (2012). *Impact of macroeconomic news on metal futures*. Journal of Banking & Finance 36(1), 51–65. [RePEc](https://ideas.repec.org/a/eee/jbfina/v36y2012i1p51-65.html)
- Batten, J., Lucey, B., McGroarty, F., Peat, M., Urquhart, A. (2017) — tính chu kỳ trong ngày của lợi suất và biến động vàng / bạc / bạch kim / palađi giao ngay, 15 năm dữ liệu 5 phút. [bản PDF](https://reading-clone.eprints-hosting.org/79175/1/BattenLuceyMcGroartyPeatUrquhart2017.pdf)
- RBC Wealth Management, *Gold's regime change?* (tương quan vàng – lợi suất thực theo giai đoạn). [RBC](https://www.rbcwealthmanagement.com/en-ca/insights/golds-regime-change)
- TA-Lib 0.8.3 (bản Python) — dùng làm cách tính tham chiếu cho chỉ báo.

## 10. Trạng thái thực hiện khuyến nghị (Pha 2)

Người dùng chọn từng cái; khuyến nghị thuộc GĐ5+ chỉ được ghi thành mục việc trong file giai đoạn tương ứng khi được đồng ý.

| Mã | Mức | GĐ | Trạng thái |
| --- | --- | --- | --- |
| KN-01 | BẮT BUỘC | GĐ5 | đã ghi thành **RSK-10** trong `GD5-ke-hoach-giao-dich.md` (15/11), chưa code |
| KN-02 | BẮT BUỘC | GĐ5 | đã ghi thành **RSK-11** trong `GD5-ke-hoach-giao-dich.md` (15/11), chưa code |
| KN-03 | NÊN (ngay) | GĐ1 | chờ bạn quyết (ING-33) |
| KN-04 | NÊN (ngay) | GĐ1 | tiêu chí chọn sàn đã ghi ở GĐ5 (16/11); chờ người dùng chọn sàn (kiểm demo sau 24/11) |
| KN-05 | NÊN (ngay) | GĐ1 | chờ duyệt |
| KN-06 | CÓ THỂ | GĐ1 | chờ bạn quyết (DEC-01) |
| KN-07 | NÊN | GĐ6 | chờ duyệt |
| KN-08 | NÊN | GĐ5 | chờ duyệt |
| KN-09 | NÊN | GĐ6 | chờ bạn quyết (M1) |
| KN-10 | NÊN | GĐ3 → GĐ6 | chờ duyệt |
| KN-11 | NÊN | GĐ6 | chờ duyệt |
| KN-12 | BẮT BUỘC (Gate GĐ5) | GĐ5 | chờ tài liệu của bạn |
| KN-13 | NÊN | GĐ4 | **xong** (16/11) — Cao / Trung bình / Thấp + "Nghiêng tăng / giảm"; nhật ký GĐ4 (MKV-03) |
| KN-14 | NÊN | GĐ4 | **xong** (16/11, nhánh riêng — chờ sau Gate GĐ1 + GĐ2); nhật ký GĐ4 |
| KN-15 | NÊN | GĐ3 | **xong** (16/11, nhánh riêng — chờ sau Gate GĐ1 + GĐ2); `technical-1.6.0`, `regime-1.2.0`; nhật ký GĐ3 |
| KN-16 | NÊN | Vận hành | **hoãn** — người dùng chọn chưa làm (16/11); hỏi lại trước khi chạy thật |
| KN-17 | NÊN | GĐ8 (sớm?) | chờ bạn quyết |
| KN-18 | NÊN | Vận hành | chờ bạn quyết |
| KN-19 | NÊN | Vận hành | chờ duyệt |
| KN-21 | CÓ THỂ | GĐ0 | **xong** (16/11, nhánh riêng — chờ sau Gate GĐ1 + GĐ2); nhật ký GĐ0 |
| KN-20, 22..26 | CÓ THỂ | xem 5.F | chờ duyệt |
