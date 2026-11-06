# CHECKLIST — Gold Trading AI

> **Dành cho AI và người phát triển.** Danh sách việc **đã làm / đang dở / chưa làm**, chia theo đúng các khối trong mô hình
> (`docs/mo-hinh/gold-bot-1-tong-the.png`, `docs/mo-hinh/gold-bot-2-market-intelligence.png`) và đặc tả `docs/huong-dan-chuc-nang/01–12`.
> Trạng thái chi tiết, nhật ký và lý do quyết định nằm ở `PROGRESS.md`. File này là **bản đồ việc**; khi hai file mâu thuẫn, kiểm tra code rồi sửa cả hai.
>
> **Cập nhật lần cuối:** 2026-11-06

## Cách đọc và cập nhật

**Trạng thái:** `[x]` xong (có test, đã kiểm chứng) · `[~]` có một phần / bản tối thiểu · `[ ]` chưa làm · `[!]` chờ người dùng (quyết định hoặc thao tác trên máy họ)

**Mã việc:** `<KHỐI>-<số>`, ví dụ `ING-07`. Mã **không bao giờ đổi hoặc dùng lại**; việc mới thêm số tiếp theo của khối. Việc bị bỏ thì giữ dòng, ghi `(bỏ: lý do)`.

**Mỗi việc ghi:** mã · tên · trạng thái · vị trí code · tiêu chí chấp nhận / ghi chú · phụ thuộc (`← MÃ`).

**Quy tắc khi làm một việc:**
1. Đọc `CLAUDE.md` (nguyên tắc thận trọng tài chính) và mục đặc tả tương ứng (cột "Đặc tả").
2. Làm **một** mã việc mỗi lần, có test (gồm trường hợp xấu), kiểm chứng bằng kịch bản riêng.
3. Xong thì đổi trạng thái ở đây, ghi nhật ký ở `PROGRESS.md`, commit có nhắc mã việc (ví dụ `ING-07: ...`), push `develop`.
4. Việc ảnh hưởng quyết định giao dịch (công thức, ngưỡng, chính sách rủi ro) phải ghi lý do ở `docs/thiet-ke/`.

**Bất biến toàn hệ thống** (từ `docs/huong-dan-chuc-nang/README.md`, `01`): point-in-time (`available_at/ingestedAt <= decisionAt`), UTC, idempotent, append-only, LIVE khóa mặc định, Safety + Guardian có quyền chặn cao nhất, không có `MarketView` hợp lệ thì không có tín hiệu, không có phê duyệt Risk thì không gửi lệnh, dữ liệu `SAMPLE` không bao giờ dẫn tới SHADOW/LIVE.

## Tổng quan theo khối của mô hình

| Khối (mô hình) | Mã | Đặc tả | Trạng thái |
| --- | --- | --- | --- |
| Nền tảng chung (contract, cấu hình) | `CORE` | README, 01 | `[x]` |
| Database | `DB` | 01, 02 | `[x]` khung · thiếu bảng lệnh/vị thế |
| Nguồn dữ liệu + Ingestion | `ING` | 02 | `[~]` có giá M15; thiếu tick, tin, lịch, vĩ mô |
| Lịch thị trường | `CAL` | 02 | `[~]` thiếu ngày lễ |
| Event Orchestrator | `ORC` | 03 | `[~]` chỉ có runner polling |
| Làn nhanh (fast lane) | `FAST` | 03, mô hình 2 | `[ ]` |
| Technical analyst | `TEC` | 04.1 | `[~]` v1.2, chưa có pUp/pDown |
| News analyst | `NEWS` | 04.2 | `[ ]` |
| Event & calendar analyst | `EVT` | 04.3 | `[ ]` |
| Macro analyst | `MAC` | 04.4 | `[ ]` |
| Positioning & sentiment analyst | `POSN` | 04.5 | `[ ]` |
| Regime analyst | `REG` | 04.6 | `[ ]` |
| AI Service (serving) | `AIS` | mô hình 1 | `[ ]` |
| Snapshot Builder | `SNP` | 05 | `[~]` có code, chưa nối luồng |
| Data Quality Gate | `DQG` | 05 | `[~]` |
| Fusion (meta-model) | `FUS` | 05 | `[ ]` |
| Kiểm soát chất lượng mô hình | `MQC` | 05, 11 | `[ ]` |
| MarketView | `MKV` | 05 | `[~]` có contract |
| Hồ sơ rủi ro + kế hoạch giao dịch | `RPF` | 07 (mở rộng) | `[!]` hoãn, chờ người dùng |
| Strategy Engine | `STR` | 06 | `[~]` có contract `TradeIntent` |
| Risk Engine | `RSK` | 07 | `[~]` |
| Risk Ledger | `LED` | 07 | `[~]` |
| Safety Supervisor | `SAF` | 08 | `[~]` máy trạng thái xong, chưa có trigger tự động |
| Execution Orchestrator | `EXE` | 09 | `[~]` có Order FSM |
| MT5 Gateway | `GW` | 09 | `[~]` bản chỉ đọc chạy thật |
| MT5 + Guardian EA | `GEA` | 09 | `[~]` bản nháp chưa biên dịch |
| Position Manager | `PSM` | 10 | `[ ]` |
| Performance | `PRF` | 10 | `[ ]` |
| Training + registry | `TRN` | 11 | `[ ]` |
| Dashboard | `DSH` | 12 | `[~]` |
| Mode Manager | `MOD` | 12 | `[x]` |
| Backtest | `BT` | 12 | `[ ]` |
| Vận hành (Docker, CI/CD, bảo mật, runbook) | `OPS` | 12 | `[~]` |

---

## CORE — Nền tảng chung

| Mã | Việc | TT | Vị trí | Tiêu chí / ghi chú |
| --- | --- | --- | --- | --- |
| CORE-01 | Data contract Pydantic bất biến | `[x]` | `backend/src/gold_trading/contracts/` | `frozen`, `extra=forbid`, datetime bắt buộc có tz → UTC |
| CORE-02 | Contract là nguồn sự thật → OpenAPI → type TS | `[x]` | `backend/scripts/export_openapi.py`, `contracts/openapi.json`, `frontend/src/api/schema.d.ts` | CI chặn khi lệch (`OPS-05`) |
| CORE-03 | Enum chuẩn: `SourceStatus`, `SafetyState`, `TradingMode` | `[x]` | `common/enums.py` | Không dùng chuỗi tự do cho trạng thái an toàn |
| CORE-04 | Tiện ích thời gian/ID | `[x]` | `common/time.py`, `common/ids.py` | |
| CORE-05 | Tiền/PnL dùng `Decimal` | `[ ]` | — | Giá đang là float (đủ cho hiển thị). **Bắt buộc trước `LED-04`/`PRF-01`** |

## DB — Database

| Mã | Việc | TT | Vị trí | Tiêu chí / ghi chú |
| --- | --- | --- | --- | --- |
| DB-01 | PostgreSQL/TimescaleDB + Alembic | `[x]` | `storage/schema.py`, `backend/migrations/` | Không sửa migration đã có; đổi schema = migration mới |
| DB-02 | Bảng append-only `safety_transitions`, `mode_changes`, `audit_log` (0001) | `[x]` | migration `0001` | Trigger DB chặn UPDATE/DELETE |
| DB-03 | Hypertable `candles` + `candle_quarantine` (0002) | `[x]` | migration `0002` | Append-only |
| DB-04 | Bảng `analyst_outputs` (0003) | `[x]` | migration `0003` | Append-only, idempotent theo hash đầu vào |
| DB-05 | Repository `InMemory` / `Sql` + quy tắc khôi phục khi khởi động | `[x]` | `storage/repository.py` | ACTIVE→PAUSED, HALTED giữ, LIVE→PAPER (có audit) |
| DB-06 | Bảng lệnh, deal, vị thế, reservation, đối soát | `[ ]` | — | ← `EXE-02`, `LED-02` |
| DB-07 | Bảng hồ sơ rủi ro có phiên bản | `[ ]` | — | ← `RPF-01` |
| DB-08 | Bảng tin tức / lịch kinh tế / series vĩ mô | `[ ]` | — | ← `ING-09..12` |
| DB-09 | Sao lưu & khôi phục volume `db_data` | `[ ]` | — | Có script + hướng dẫn, đã diễn tập khôi phục |

## ING — Nguồn dữ liệu và Ingestion (đặc tả 02)

| Mã | Việc | TT | Vị trí | Tiêu chí / ghi chú |
| --- | --- | --- | --- | --- |
| ING-01 | Cửa nạp nến chung `CandleIngestor` | `[x]` | `ingestion/candles.py` | Kiểm tra OHLC, khử trùng, revision, cờ chất lượng, quarantine, payload gốc |
| ING-02 | Point-in-time cho nến (`available_at`) | `[x]` | `storage/candles.py` | Realtime: `available_at=ingested_at`; backfill: `=close_time` + cờ `BACKFILL`; truy vấn qua `store.query(as_of=)` |
| ING-03 | Trùng mâu thuẫn trong cùng batch → cách ly | `[x]` | `ingestion/candles.py` | `CONFLICTING_DUPLICATE`, không tạo revision giả |
| ING-04 | Nguồn dữ liệu mẫu tất định | `[x]` | `ingestion/sources/sample.py`, `ingestion/sample_feed.py` | Seed cố định; luôn gắn nhãn SAMPLE |
| ING-05 | Nguồn CSV xuất từ MT5 + CLI `import-csv` | `[x]` | `ingestion/sources/csv_file.py`, `ingestion/cli.py` | Bắt buộc `--server-tz` IANA; giờ mơ hồ DST bị cách ly; chỉ M1–H1 |
| ING-06 | R1: kiểm tra múi giờ (> 1% nến ngoài giờ → từ chối cả lô) | `[x]` | `csv_file.check_sessions`, `api/ingest.py` | Gợi ý múi giờ khớp nhất |
| ING-07 | Cổng nhận nến từ MT5 Gateway | `[x]` | `api/ingest.py` | Token ≥ 24 ký tự (`hmac.compare_digest`), `dry_run`, tối đa 2.000 nến/lần, chỉ XAUUSD M15, đồng hồ backend làm `ingested_at` |
| ING-08 | Tick / bid / ask / spread sống | `[ ]` | — | Lưu point-in-time; dùng cho kiểm tra trước gửi lệnh (`EXE-03`). ← `GW-08` |
| ING-09 | Lịch kinh tế (CPI, NFP, FOMC…) | `[ ]` | — | `releaseAt`, `actual/forecast/previous`, `importance`; phân biệt "chưa công bố" với 0. ← `DB-08` |
| ING-10 | Tin tức (RSS/báo/Fed) | `[ ]` | — | Khử trùng theo fingerprint, lưu `publishedAt` + `ingestedAt` + URL |
| ING-11 | Vĩ mô: DXY, lợi suất thực 10Y (TIPS), kỳ vọng Fed | `[ ]` | — | Theo `releaseAt`, revision không viết lại quá khứ |
| ING-12 | Vị thế: COT, dòng tiền ETF, NHTW mua vàng | `[ ]` | — | Ghi rõ độ trễ công bố |
| ING-13 | Store point-in-time chung (bản cũ) | `[~]` | `ingestion/point_in_time.py` | Chưa dùng. Quyết định: tái dùng cho `ING-09..12` hoặc xóa |
| ING-14 | Khung H4/D1 theo giờ server broker | `[ ]` | — | Hiện chỉ M1–H1 |

## CAL — Lịch thị trường

| Mã | Việc | TT | Vị trí | Tiêu chí / ghi chú |
| --- | --- | --- | --- | --- |
| CAL-01 | Lịch tham chiếu theo giờ New York | `[x]` | `market/hours.py` | CN 18:00 → T6 17:00, nghỉ 17:00–18:00, tự xử lý DST |
| CAL-02 | Lịch broker (giờ server) giao với lịch tham chiếu | `[x]` | `market/hours.py` (`BrokerSessions`, `MarketCalendar`) | `GT_BROKER_SESSIONS` + `GT_BROKER_SERVER_TZ`; cấu hình sai → không khởi động. Đã kiểm chứng trên MetaQuotes-Demo |
| CAL-03 | Ngày lễ / đóng cửa sớm | `[ ]` | — | Ví dụ Labor Day 07/09/2026 thiếu 10 nến. Hiện analyst tự chặn (an toàn nhưng gián đoạn) |
| CAL-04 | Dùng `MarketCalendar` cho cờ `GAP` lúc nạp và R1 | `[ ]` | `ingestion/candles.py`, `csv_file.py` | Hiện vẫn dùng lịch tham chiếu |

## ORC — Event Orchestrator (đặc tả 03)

| Mã | Việc | TT | Vị trí | Tiêu chí / ghi chú |
| --- | --- | --- | --- | --- |
| ORC-01 | Runner tối thiểu: chạy Technical khi có nến mới | `[~]` | `analysts/runner.py` | Polling 15 giây |
| ORC-02 | Bảng sự kiện → job theo mô hình | `[ ]` | `orchestrator/` | M15 đóng → Technical → Regime → Fusion; CPI/NFP → fast lane + Event + News; DXY/yield → Macro; COT → Positioning; output hết hạn → invalidate MarketView |
| ORC-03 | `jobKey = eventType + subject + eventVersion + analyzerVersion`, chạy đúng một lần | `[ ]` | | Gửi lại cùng event không nhân đôi output |
| ORC-04 | Debounce theo loại/symbol/time bucket | `[ ]` | | Không bỏ qua sự kiện công bố quan trọng |
| ORC-05 | Deadline, retry giới hạn, exponential backoff, dead-letter | `[ ]` | | Không retry vô hạn; job lỗi phải quan sát được |
| ORC-06 | Ghi `correlationId`, nguyên nhân kích hoạt, phiên bản input/output, trạng thái job | `[ ]` | | Hiển thị ở `DSH-08` |
| ORC-07 | Invalidate MarketView khi output hết hạn | `[ ]` | | ← `MKV-02` |

## FAST — Làn nhanh (mô hình 2)

| Mã | Việc | TT | Vị trí | Tiêu chí / ghi chú |
| --- | --- | --- | --- | --- |
| FAST-01 | Kích hoạt khi CPI/NFP ra, tin nóng cấp cao, spread giãn mạnh, bất ngờ so với dự báo | `[ ]` | | ← `ING-08`, `ING-09` |
| FAST-02 | Xử lý bằng luật (+ FinBERT), **không gọi LLM nặng** | `[ ]` | | Ngân sách độ trễ tính bằng giây |
| FAST-03 | Kết quả: cập nhật `riskFlags`, chặn lệnh 10–15 phút, giảm confidence, đi thẳng Safety (bỏ qua Fusion) | `[ ]` | | ← `SAF-05` |

## Market Intelligence — 6 analyst (đặc tả 04)

Hợp đồng chung: output có `analystId`, `asOf`, `expiresAt`, `confidence`, `features`, `drivers`, `riskFlags`, `sourceStatus`, `qualityFlags`, `version`. Output quá hạn không được Fusion dùng. Contract: `contracts/analyst.py`.

### TEC — Technical analyst (04.1)

| Mã | Việc | TT | Vị trí | Tiêu chí / ghi chú |
| --- | --- | --- | --- | --- |
| TEC-01 | Chỉ báo EMA (khởi tạo SMA), RSI Wilder, ATR Wilder | `[x]` | `analysts/indicators.py` | Đối chiếu thư viện `ta`: ATR lệch 5e-11 |
| TEC-02 | Cổng chất lượng R2–R6 + `CALENDAR_MISMATCH` | `[x]` | `market/quality.py`, `analysts/technical.py` | R2 độ phủ ≥ 99%, R3 spike 8× trung vị, R4 đóng băng, R5 spread, R6 ≥ 250 nến |
| TEC-03 | Xu hướng, cấu trúc, swing (xác nhận sau 3 nến), vùng S/R | `[x]` | `analysts/technical.py` (`technical-1.2.0`) | Vùng ≤ 1 ATR, bỏ swing trên nến spike. Thiết kế: `docs/thiet-ke/03-technical-analyst.md` |
| TEC-04 | Lưu append-only, idempotent, API, thẻ giao diện | `[x]` | `storage/analyst_outputs.py`, `api/analysts.py` | `confidence` = chất lượng dữ liệu, **không phải xác suất** |
| TEC-05 | Theo dõi ngưỡng R3/R5 trên dữ liệu thật vài ngày | `[!]` | | Dữ liệu MetaQuotes-Demo; điều chỉnh thì tăng `VERSION` |
| TEC-06 | Nhận diện pattern nến/giá | `[ ]` | | Không rò rỉ nến tương lai |
| TEC-07 | `volForecast` | `[ ]` | | Đầu vào của `MKV`, `RPF` |
| TEC-08 | Mô hình LightGBM → `pUp`/`pDown` | `[ ]` | | **Chỉ gọi là xác suất sau khi đã hiệu chỉnh (calibration) trên dữ liệu thật**. ← `TRN-01..04`, `AIS-01` |

### NEWS — News analyst, LLM (04.2)

| Mã | Việc | TT | Vị trí | Tiêu chí / ghi chú |
| --- | --- | --- | --- | --- |
| NEWS-01 | Lọc trùng, nhận diện thực thể | `[ ]` | | ← `ING-10` |
| NEWS-02 | FinBERT lọc trước → LLM trích stance, impact, novelty, horizon, `newsShock` | `[ ]` | | Có citation bài gốc |
| NEWS-03 | Kiểm soát: giới hạn token/timeout, chống prompt injection, lưu prompt/model version | `[ ]` | | Không dùng LLM ở fast lane |

### EVT — Event & calendar analyst (04.3) — **ưu tiên cao**

| Mã | Việc | TT | Vị trí | Tiêu chí / ghi chú |
| --- | --- | --- | --- | --- |
| EVT-01 | Phân loại sự kiện FOMC/NFP/CPI, mức quan trọng | `[ ]` | | Luật cứng, **không cần LLM**. ← `ING-09` |
| EVT-02 | Cửa sổ rủi ro trước/sau công bố → cờ `EVENT_WINDOW` | `[ ]` | | Risk Engine đã chờ sẵn cờ này |
| EVT-03 | So sánh actual – forecast → surprise direction, `eventRisk` | `[ ]` | | Phân biệt "chưa công bố" với actual = 0 |

### MAC — Macro analyst (04.4)

| Mã | Việc | TT | Vị trí | Tiêu chí / ghi chú |
| --- | --- | --- | --- | --- |
| MAC-01 | Đồng bộ DXY, lợi suất thực 10Y, kỳ vọng Fed theo thời điểm công bố | `[ ]` | | ← `ING-11` |
| MAC-02 | Thay đổi/độ bất thường, macro bias, cờ stress thanh khoản | `[ ]` | | TTL phù hợp dữ liệu tần suất thấp |

### POSN — Positioning & sentiment analyst (04.5)

| Mã | Việc | TT | Vị trí | Tiêu chí / ghi chú |
| --- | --- | --- | --- | --- |
| POSN-01 | Z-score lịch sử COT, ETF flow, NHTW mua vàng | `[ ]` | | ← `ING-12` |
| POSN-02 | Crowding risk, giả thuyết contrarian ở cực trị | `[ ]` | | COT trễ lớn, không coi là thời gian thực |

### REG — Regime analyst (04.6)

| Mã | Việc | TT | Vị trí | Tiêu chí / ghi chú |
| --- | --- | --- | --- | --- |
| REG-01 | Phân loại `TREND|RANGE|RISK_OFF|HIGH_VOL` (HMM hoặc classifier) | `[ ]` | | Đầu vào: returns, volatility, output Technical |
| REG-02 | Trọng số gợi ý cho Fusion, giám sát drift/chuyển regime | `[ ]` | | Confidence thấp khi xác suất các lớp gần nhau |

## AIS — AI Service (mô hình 1)

| Mã | Việc | TT | Vị trí | Tiêu chí / ghi chú |
| --- | --- | --- | --- | --- |
| AIS-01 | Dịch vụ Python phục vụ mô hình đã đăng ký (serving) | `[ ]` | | Chỉ nạp artifact từ registry đã duyệt. ← `TRN-04` |
| AIS-02 | Ghi `modelVersion` vào mọi output dùng mô hình | `[ ]` | | |

## SNP / DQG / FUS / MQC / MKV — Snapshot → MarketView (đặc tả 05)

| Mã | Việc | TT | Vị trí | Tiêu chí / ghi chú |
| --- | --- | --- | --- | --- |
| SNP-01 | Snapshot Builder: gom output còn hạn thành ảnh chụp bất biến | `[~]` | `intelligence/snapshot_builder.py`, `contracts/snapshot.py` | Có code + test, **chưa nối vào luồng chạy** |
| SNP-02 | Lưu snapshot + manifest input để tái dựng | `[ ]` | | `snapshotId`, `eventTime`, `availableAt`, `expiresAt` |
| DQG-01 | Kiểm tra nguồn bắt buộc/tùy chọn, TTL, `sourceStatus` | `[x]` | `intelligence/quality_gate.py` | Thiếu nguồn bắt buộc → `REJECTED` |
| DQG-02 | Kiểm tra schema, outlier, xung đột timestamp | `[ ]` | | |
| DQG-03 | Chính sách degrade có phiên bản + audit lý do | `[ ]` | | Không tự chữa dữ liệu |
| FUS-01 | Fusion đơn giản (luật, không ML) → `MarketView` đầu tiên | `[ ]` | `intelligence/` | Chỉ dùng output hợp lệ đã qua Gate; bất đồng → giảm confidence. MarketView từ SAMPLE phải mang cờ để Risk chặn ở SHADOW/LIVE |
| FUS-02 | Meta-model Fusion | `[ ]` | | ← `TRN`, `MQC` |
| MQC-01 | Calibration, Brier/log loss, drift PSI, tỷ lệ stale | `[ ]` | | Model mới chạy shadow trước, có ngưỡng rollback |
| MKV-01 | Contract `MarketView` | `[x]` | `contracts/market_view.py` | `bias`, `pUp/pDown`, `confidence`, `regime`, `volForecast`, `drivers`, `riskFlags`, `qualityFlags` |
| MKV-02 | Lưu, hết hạn, invalidate MarketView | `[ ]` | | Strategy kiểm `expiresAt` khi tạo intent; Risk/Execution kiểm lại trước gửi |
| MKV-03 | Hiển thị MarketView trên trang Tổng quan | `[~]` | `frontend/` | Khung có sẵn, chưa có dữ liệu thật. ← `FUS-01` |

## RPF — Hồ sơ rủi ro + kế hoạch giao dịch (việc ③b, mở rộng của 07)

**`[!]` Tạm hoãn, chờ người dùng trả lời:** vốn; mục tiêu 4–5% theo ngày/tuần/tháng; lỗ tối đa mỗi lệnh; ngưỡng dừng ngày/tuần; giữ lệnh trong ngày hay qua đêm; broker, đòn bẩy, phí hoa hồng.

| Mã | Việc | TT | Vị trí | Tiêu chí / ghi chú |
| --- | --- | --- | --- | --- |
| RPF-01 | Hồ sơ rủi ro có phiên bản (vốn, mục tiêu, lỗ tối đa lệnh/ngày/tuần, broker) | `[!]` | | Append-only, có audit. ← `DB-07` |
| RPF-02 | Đề xuất SL theo ATR, TP theo R:R, lot theo rủi ro, thời gian giữ lệnh ước tính | `[ ]` | | Làm tròn **xuống** theo `volume_step`; lot < tối thiểu → báo **không khả thi**, không làm tròn lên |
| RPF-03 | Kết luận khả thi, giải thích bằng số cụ thể | `[ ]` | | Ví dụ: vốn 100$, ATR ~13$, lot 0,01 → một lệnh SL 1,5 ATR mất ~20% vốn |
| RPF-04 | Nhãn "chỉ minh họa" khi dùng dữ liệu SAMPLE | `[ ]` | | |
| RPF-05 | Trang giao diện nhập hồ sơ và xem kế hoạch | `[ ]` | `frontend/` | Trang "Rủi ro" (`DSH-05`) |

## STR — Strategy Engine (đặc tả 06)

| Mã | Việc | TT | Vị trí | Tiêu chí / ghi chú |
| --- | --- | --- | --- | --- |
| STR-01 | Contract `TradeIntent` (validate SL/TP theo chiều lệnh) | `[x]` | `contracts/trade_intent.py` | |
| STR-02 | Điều kiện vào: MarketView còn hạn, confidence đạt ngưỡng theo regime, không có riskFlags cấm | `[ ]` | `strategy/` | ← `MKV-02` |
| STR-03 | Sinh intent: entry, SL, TP, `riskBudgetRequested`, `expiry`, `idempotencyKey` | `[ ]` | | Không tự suy volume cuối cùng |
| STR-04 | Chống intent trùng cho cùng strategy/symbol/horizon | `[ ]` | | |
| STR-05 | Ghi audit, gửi Risk, ghi lý do khi bị từ chối | `[ ]` | | |

## RSK — Risk Engine (đặc tả 07)

| Mã | Việc | TT | Vị trí | Tiêu chí / ghi chú |
| --- | --- | --- | --- | --- |
| RSK-01 | Kiểm Safety, hết hạn intent/MarketView, riskFlags, spread | `[x]` | `risk/engine.py` | |
| RSK-02 | Sizing theo rủi ro, volume step/min/max, hạn mức tổng | `[x]` | `risk/engine.py` (`RiskPolicy`, `SymbolSpec`) | XAUUSD `contract_size=100`, `volume_step=0.01`. Giữ `ledger.lock` khi tính headroom + reserve |
| RSK-03 | Margin/leverage | `[ ]` | | |
| RSK-04 | Exposure ròng/gộp, correlation/concentration | `[ ]` | | |
| RSK-05 | Hạn mức ngày, drawdown | `[ ]` | | ← `RPF-01`, `LED-04` |
| RSK-06 | Kết quả `REDUCED` + TTL quyết định + gắn policy version | `[ ]` | | |
| RSK-07 | Đọc cờ `EVENT_WINDOW`, `WIDE_SPREAD`, `HIGH_VOLATILITY` từ MarketView thật | `[ ]` | | ← `EVT-02`, `FUS-01` |

## LED — Risk Ledger (đặc tả 07)

| Mã | Việc | TT | Vị trí | Tiêu chí / ghi chú |
| --- | --- | --- | --- | --- |
| LED-01 | Reserve/release append-only trong bộ nhớ | `[x]` | `risk/ledger.py` | Test đồng thời: hai intent không vượt hạn mức |
| LED-02 | Lưu ledger vào DB (`PortfolioState`, `RiskReservation`) | `[ ]` | | ← `DB-06` |
| LED-03 | Đối soát định kỳ với MT5 (order/deal/position/equity/margin) | `[ ]` | | Lệch nghiêm trọng → Safety hạn chế/halt + incident. ← `GW-09` |
| LED-04 | Fill/đóng lệnh → exposure và PnL (Decimal) | `[ ]` | | ← `CORE-05` |
| LED-05 | Recover sau crash giữa reserve và gửi lệnh | `[ ]` | | Bằng idempotency key + đối soát broker |

## SAF — Safety Supervisor (đặc tả 08)

| Mã | Việc | TT | Vị trí | Tiêu chí / ghi chú |
| --- | --- | --- | --- | --- |
| SAF-01 | Máy trạng thái ACTIVE/PAUSED/HALTED, ghi trước khi đổi | `[x]` | `safety/supervisor.py` | HALTED → ACTIVE cần xác nhận người vận hành |
| SAF-02 | Lưu bền + khôi phục khi khởi động | `[x]` | `storage/repository.py` | Khởi động lại luôn về PAUSED nếu đang ACTIVE |
| SAF-03 | Kill switch trên Dashboard có xác nhận + audit | `[x]` | `frontend/`, `POST /api/safety` | Chưa có xác thực người dùng (`OPS-07`) |
| SAF-04 | Trigger tự động: dữ liệu STALE / mất Gateway | `[ ]` | | |
| SAF-05 | Trigger tự động: tin nóng, sự kiện cấp cao | `[ ]` | | ← `FAST-03`, `EVT-02` |
| SAF-06 | Trigger tự động: spread bất thường, equity/margin/drawdown | `[ ]` | | ← `ING-08`, `LED-03` |
| SAF-07 | Hành động: hủy lệnh chờ, giảm/đóng vị thế theo policy, thông báo | `[ ]` | | Idempotent, xác nhận kết quả từ MT5. ← `EXE-01` |

## EXE — Execution Orchestrator (đặc tả 09)

| Mã | Việc | TT | Vị trí | Tiêu chí / ghi chú |
| --- | --- | --- | --- | --- |
| EXE-01 | Order FSM: REQUESTED → … → FILLED / REJECTED / CANCELLED / EXPIRED / UNKNOWN | `[x]` | `execution/order_fsm.py` | |
| EXE-02 | Execution Orchestrator: chỉ nhận intent đã Risk duyệt + Safety cho phép | `[ ]` | `execution/` | ← `RSK`, `SAF` |
| EXE-03 | Kiểm tra trước gửi: hạn approval, Safety, quote mới, spread, volume step, SL/TP hợp lệ, kết nối MT5 | `[ ]` | | Bỏ lệnh nếu spread giãn hoặc giá chạy xa so với lúc nến đóng. ← `ING-08` |
| EXE-04 | Command riêng cho sửa SL/TP, hủy, đóng; idempotency key + precondition + audit | `[ ]` | | |
| EXE-05 | `UNKNOWN` → truy vấn MT5 trước, không retry mù | `[ ]` | | Mất ACK không tạo lệnh thứ hai |

## GW — MT5 Gateway (đặc tả 09, thiết kế `docs/thiet-ke/09a-mt5-gateway-chi-doc.md`)

| Mã | Việc | TT | Vị trí | Tiêu chí / ghi chú |
| --- | --- | --- | --- | --- |
| GW-01 | Gateway **chỉ đọc**: bọc `READ_ONLY_FUNCTIONS`, test quét mã nguồn chặn hàm giao dịch | `[x]` | `mt5_gateway/src/mt5_gateway/reader.py` | **Không thêm đặt lệnh vào package này** |
| GW-02 | Quy đổi giờ server (IANA) → UTC, chỉ lấy nến đã đóng (`start_pos=1`) | `[x]` | `timeconv.py`, `reader.py` | Giờ mơ hồ DST bị bỏ, không đoán |
| GW-03 | `check` 9 bước, `run` nạp bù 5.000 nến rồi 5 giây/lần, backoff, heartbeat | `[x]` | `checks.py`, `sync.py`, `cli.py` | |
| GW-04 | Chạy với MT5 demo thật (MetaQuotes-Demo, XAUUSD M15) | `[x]` | | check 9/9, 5.000 nến, 0 cách ly, tự kết nối lại |
| GW-05 | Người dùng đổi token ingest (token cũ đã lộ trong chat) | `[!]` | `.env`, `gateway.env` | Lệnh đổi đã gửi; chờ xác nhận dòng "2. Token" ĐẠT |
| GW-06 | Chạy như dịch vụ Windows, đóng gói `.exe` | `[ ]` | | Build trên runner Windows |
| GW-07 | Hàng đợi bền vững trên đĩa | `[ ]` | | Hiện gián đoạn > 5 giờ phải chạy lại `run` để nạp bù |
| GW-08 | Gửi giá sống bid/ask/spread + thông tin tài khoản sang backend | `[ ]` | | Vẫn chỉ đọc. Phải có trước `EXE-03` |
| GW-09 | Đọc order/deal/position/equity để đối soát | `[ ]` | | Vẫn chỉ đọc. ← dùng cho `LED-03` |
| GW-10 | **Thành phần đặt lệnh riêng** (gửi/sửa/hủy, map request–ticket, reason code chuẩn) | `[ ]` | package mới, tách khỏi `mt5_gateway` | Làm **sau cùng**, review riêng, mTLS/token |
| GW-11 | Lịch giao dịch lấy tự động từ MT5 (R12) | `[ ]` | | Python MT5 không đọc được Sessions; hiện chép tay (`CAL-02`) |

## GEA — MT5 + Guardian EA (đặc tả 09)

| Mã | Việc | TT | Vị trí | Tiêu chí / ghi chú |
| --- | --- | --- | --- | --- |
| GEA-01 | Bản nháp Guardian EA | `[~]` | `guardian_ea/GuardianEA.mq5` | **Chưa biên dịch, chưa test** |
| GEA-02 | Biên dịch và test trên MT5 demo | `[ ]` | | |
| GEA-03 | Ngưỡng equity cứng, đóng/hạn chế khi control plane mất kết nối | `[ ]` | | Cấu hình có phiên bản, quy tắc tối giản |
| GEA-04 | Diễn tập định kỳ | `[ ]` | | Điều kiện của `LIVE_CHECKLIST.guardian_ea_tested` |

## PSM — Position Manager (đặc tả 10)

| Mã | Việc | TT | Vị trí | Tiêu chí / ghi chú |
| --- | --- | --- | --- | --- |
| PSM-01 | Đề xuất BE, trailing, time-stop, chốt/giảm vị thế | `[ ]` | `position/` | Chỉ **đề xuất**; mọi sửa SL/TP qua Risk/Execution/Safety |
| PSM-02 | Không nới rộng rủi ro; time-stop theo giờ khớp thực tế | `[ ]` | | Restart không lặp command |

## PRF — Performance (đặc tả 10)

| Mã | Việc | TT | Vị trí | Tiêu chí / ghi chú |
| --- | --- | --- | --- | --- |
| PRF-01 | PnL thực hiện/chưa thực hiện, drawdown, hit rate, expectancy, MAE/MFE, chi phí, slippage | `[ ]` | `performance/` | Từ ledger đã đối soát; khớp deal MT5 sau phí/swap |
| PRF-02 | Tách paper / shadow / live; theo strategy/regime | `[ ]` | | Không tự động đổi mô hình hay thông số LIVE |

## TRN — Training + registry (đặc tả 11)

| Mã | Việc | TT | Vị trí | Tiêu chí / ghi chú |
| --- | --- | --- | --- | --- |
| TRN-01 | Dataset point-in-time có phiên bản, nhãn không rò rỉ tương lai | `[ ]` | | |
| TRN-02 | Train/tune walk-forward, tách theo thời gian | `[ ]` | | |
| TRN-03 | Đánh giá cả dự báo lẫn tác động giao dịch sau spread/slippage/độ trễ | `[ ]` | | ← `BT-01` |
| TRN-04 | Model registry: code version, data manifest, metrics, giới hạn, người duyệt | `[ ]` | | Shadow → canary → rollback |

## DSH — Dashboard (đặc tả 12) — chỉ dùng web, không làm app mobile/PWA

| Mã | Việc | TT | Vị trí | Tiêu chí / ghi chú |
| --- | --- | --- | --- | --- |
| DSH-01 | Theme AurumDesk, i18n tiếng Việt, responsive (desktop/tablet/mobile) | `[x]` | `frontend/` | Quy ước theme ở `PROGRESS.md` |
| DSH-02 | Trang Tổng quan: metric, điều khiển Safety/Mode, lịch sử | `[x]` | `frontend/src/pages/` | |
| DSH-03 | Trang Thị trường: nến M15, EMA/RSI, S/R, thẻ Technical, chất lượng dữ liệu, trạng thái MT5 | `[x]` | `frontend/src/pages/MarketPage.tsx` | Vạch ngày theo giờ máy người xem (`components/chart/chartTime.ts`) |
| DSH-04 | Trang Lệnh & vị thế | `[ ]` | | Hiện ghi "Sắp có". ← `EXE-02` |
| DSH-05 | Trang Rủi ro | `[ ]` | | ← `RPF-05`, `LED-02` |
| DSH-06 | Trang Nhật ký (audit, incident) | `[ ]` | | Mọi cảnh báo liên kết tới audit/incident |
| DSH-07 | Hiển thị giá sống bid/ask/spread | `[ ]` | | ← `GW-08` |
| DSH-08 | Trạng thái pipeline/job, chênh lệch đối soát | `[ ]` | | ← `ORC-06`, `LED-03` |

## MOD — Mode Manager (đặc tả 12)

| Mã | Việc | TT | Vị trí | Tiêu chí / ghi chú |
| --- | --- | --- | --- | --- |
| MOD-01 | Mode BACKTEST/PAPER/SHADOW/LIVE (`common/enums.py`), LIVE khóa, approver khác actor, đủ `LIVE_CHECKLIST` | `[x]` | `modes/manager.py` | |
| MOD-02 | Chặn SHADOW/LIVE khi dùng dữ liệu SAMPLE | `[x]` | `api/app.py` (`mode_guard`) | |
| MOD-03 | Mode BACKTEST nối với `BT` | `[ ]` | | ← `BT-01` |

## BT — Backtest (đặc tả 12)

| Mã | Việc | TT | Vị trí | Tiêu chí / ghi chú |
| --- | --- | --- | --- | --- |
| BT-01 | Replay theo `available_at`, dùng snapshot + policy/model version lịch sử | `[ ]` | | Kết quả trên SAMPLE ghi "không có giá trị đánh giá" |
| BT-02 | Mô phỏng spread, slippage, commission/swap, độ trễ, fill một phần, giờ thị trường, margin | `[ ]` | | |
| BT-03 | Báo cáo: giả định, khoảng dữ liệu, bias còn lại, kết quả theo regime | `[ ]` | | |

## OPS — Vận hành, bảo mật, CI/CD (đặc tả 12)

| Mã | Việc | TT | Vị trí | Tiêu chí / ghi chú |
| --- | --- | --- | --- | --- |
| OPS-01 | Docker compose: db + backend + frontend, migration tự chạy | `[x]` | `docker-compose.yml`, `deploy/docker-compose.yml`, `backend/scripts/entrypoint.sh` | DB không mở cổng ra host |
| OPS-02 | Bản deploy build thẳng từ GitHub, không cần clone | `[x]` | `deploy/`, `deploy/README.md` | |
| OPS-03 | Truy cập qua Tailscale bằng `DASHBOARD_BIND` | `[x]` | compose, `deploy/README.md` | Mặc định `127.0.0.1`. **Không dùng `0.0.0.0`** khi chưa có `OPS-07` |
| OPS-04 | Lịch giờ broker + token qua `.env` | `[x]` | compose | `GT_DATA_SOURCE`, `GT_INGEST_TOKEN`, `GT_BROKER_SESSIONS`, `GT_BROKER_SERVER_TZ` |
| OPS-05 | CI GitHub Actions: backend, gateway, frontend, lệch contract, build Docker | `[x]` | `.github/workflows/ci.yml` | Lần đầu 4/4 xanh (2026-11-06) |
| OPS-06 | CD tự deploy lên máy Windows | `[!]` | — | **Tạm hoãn.** Đã chốt thiết kế: Task Scheduler 5 phút; chỉ deploy commit `develop` có CI xanh; build đúng commit (`GT_BRANCH=<sha>`); kiểm `/api/health`; không deploy khi mode LIVE; không thử lại commit lỗi; không dùng self-hosted runner (repo public); script PowerShell chỉ ASCII, test trên runner `windows-latest` |
| OPS-07 | Xác thực API + Dashboard | `[ ]` | | **Bắt buộc trước khi mở rộng truy cập** và trước SHADOW/LIVE |
| OPS-08 | Runbook sự cố, on-call, diễn tập kill switch | `[ ]` | `docs/` | Điều kiện `LIVE_CHECKLIST` |
| OPS-09 | Thông báo sự cố (mất MT5, giá cũ, Safety tự dừng) | `[ ]` | | Xét lại khi có đặt lệnh |
| OPS-10 | Chaos test: mất mạng, restart, gửi trùng | `[ ]` | | |

---

## Thứ tự đề xuất (đường găng tới paper trading)

```text
[!] GW-05, TEC-05 (việc nhỏ chờ người dùng)
 → [!] RPF-01..05   Hồ sơ rủi ro + kế hoạch (chờ người dùng trả lời)
 → ING-09 → EVT-01..03 → RSK-07      Lịch kinh tế, chặn quanh tin lớn
 → ORC-02..07                        Orchestrator đầy đủ
 → SNP-02 → FUS-01 → MKV-02..03      MarketView đầu tiên
 → STR-02..05 + BT-01..03            Strategy + Backtest có chi phí thật
 → OPS-07                            Xác thực API
 → GW-08 → ING-08 → EXE-03 → DSH-07  Giá sống
 → OPS-06                            CD (khi người dùng muốn làm lại)
 → GW-09 → LED-02..05 → EXE-02..05   Đối soát + Execution (vẫn PAPER)
 → GEA-02..04 → SAF-04..07           Guardian + trigger tự động
 → GW-10                             Đặt lệnh thật — làm SAU CÙNG
```

Trước khi bật LIVE: đủ 7 mục `LIVE_CHECKLIST` trong `modes/manager.py` (`reconciliation_clean`, `required_sources_healthy`, `kill_switch_tested`, `guardian_ea_tested`, `risk_limits_approved`, `model_versions_approved`, `on_call_ready`) và mục "Checklist trước LIVE" ở `docs/huong-dan-chuc-nang/12-van-hanh-kiem-thu.md`.
