# GĐ1 — Dữ liệu vào (đặc tả 02): đủ 4 nhóm nguồn của mô hình

> Một phần của bản đồ việc theo giai đoạn (tách từ `CHECKLIST.md` 2026-11-06). Chỉ mục, nguyên tắc và bất biến: [`README.md`](README.md). Trạng thái chung: `PROGRESS.md`. Ghi chú kỹ thuật: `docs/ghi-chu-ky-thuat.md`.


Mô hình yêu cầu: **Giá MT5** (OHLC, tick) · **Tin tức** (báo, RSS, Fed) · **Lịch kinh tế** (số liệu công bố) · **Vĩ mô, vị thế** (DXY, TIPS, COT).

### Quyết định cần người dùng chốt trước khi làm GĐ1

| Mã | Câu hỏi | Gợi ý (phải xác minh giấy phép/điều khoản trước khi dùng) | TT |
| --- | --- | --- | --- |
| DEC-01 | Nguồn **lịch kinh tế**, đặc biệt **số dự báo (forecast/consensus)** | **Chỉ nguồn chính thức Mỹ**: lịch công bố BLS (CPI, NFP…), BEA (GDP, PCE), Fed (FOMC) + số actual qua API miễn phí của các cơ quan này. **Không có forecast** → `EVT-03`/ING-18 ghi "không đủ dữ liệu" (1C-C07); cửa sổ rủi ro quanh giờ công bố vẫn đầy đủ. Lý do: miễn phí (DEC-06), giấy phép rõ, ổn định. Có thể thêm nhập tay forecast sau | `[x]` 2026-11-07 |
| DEC-02 | Nguồn **tin tức** | **Chỉ thông cáo chính thức** qua RSS: Fed (tuyên bố, biên bản, phát biểu), Bộ Tài chính Mỹ, BLS. Chưa có tin địa chính trị (biến cố chỉ thấy qua giá/spread). **Yêu cầu người dùng: nguồn tin phải cấu hình được** (danh sách nguồn trong cấu hình, bật/tắt, thêm nguồn mới không cần sửa code; mỗi nguồn ghi giấy phép — ING-32), không gắn cứng một nguồn | `[x]` 2026-11-07 |
| DEC-03 | Nguồn **DXY** | **Tự tính từ giá MT5** theo công thức công khai của DXY (6 cặp: EURUSD, USDJPY, GBPUSD, USDCAD, USDSEK, USDCHF); nếu broker có symbol chỉ số USD thì dùng để đối chiếu. Nhãn rõ: "chỉ số USD tự tính", không gọi là DXY chính thức. Thiếu cặp nào / nến không cùng thời điểm → "không đủ dữ liệu", không nội suy. Cần người dùng kiểm tra broker có đủ 6 cặp. Không dùng chỉ số USD rộng FRED (cập nhật tuần) | `[x]` 2026-11-07 |
| DEC-04 | Nguồn **kỳ vọng lãi suất Fed** | **Proxy từ FRED (miễn phí, cần khóa — DEC-07):** lợi suất 2 năm + lãi suất Fed hiện hành; chênh lệch (2 năm − lãi suất Fed) < 0 → thị trường nghiêng về cắt, > 0 → giữ/tăng. Ghi rõ là **proxy**, số ngày làm việc trước, `available_at` = lúc FRED công bố. **Không** quy đổi thành "xác suất Fed cắt lãi" (chưa hiệu chỉnh). FedWatch không có API miễn phí | `[x]` 2026-11-07 |
| DEC-05 | Nguồn **NHTW mua vàng / dòng tiền ETF** | **Chỉ ETF:** lượng vàng nắm giữ hằng ngày do quỹ GLD và IAU tự công bố (miễn phí; kiểm điều khoản tải từng quỹ trước khi bật — ING-32); `available_at` = lúc quỹ công bố (sau đóng cửa Mỹ). **NHTW: hoãn** (dữ liệu IMF theo tháng, trễ 1–2 tháng, ít giá trị cho giao dịch ngắn hạn) | `[x]` 2026-11-07 |
| DEC-06 | Ngân sách: chấp nhận nguồn trả phí không, tối đa bao nhiêu/tháng | **0 đồng — chỉ dùng nguồn miễn phí.** Hệ quả: không có tin tổng hợp thời gian thực; thiếu dữ liệu nào thì ghi "không đủ dữ liệu", không đoán. Có thể thêm nguồn trả phí sau mà không làm lại | `[x]` 2026-11-07 |
| DEC-07 | Đăng ký khóa API miễn phí (ví dụ FRED) — người dùng tự đăng ký, khóa để trong `.env`, không gửi qua chat | **Đăng ký 3 khóa miễn phí: FRED** (lợi suất, lợi suất thực, lãi suất Fed — bắt buộc), **BLS** (CPI, NFP từ nguồn gốc), **BEA** (GDP, PCE từ nguồn gốc). Khóa chỉ trong `.env` (ING-31), không log, không commit; hướng dẫn người dùng đăng ký từng khóa khi tới phần 1C/1E. Thiếu/sai khóa → nguồn MISSING + cảnh báo (1E-C05). Nguồn không cần khóa: RSS Fed/Bộ Tài chính/BLS, COT (CFTC), GLD/IAU, MT5 | `[x]` 2026-11-07 |

### Chuyển từ GĐ0 (2026-11-06)

- **Đa tài khoản** (thuộc GĐ1, chi tiết ở [`MT-da-nguoi-dung.md`](MT-da-nguoi-dung.md)): MT-05 (nguồn giá theo broker/server, **DEC-14 đã chốt 2026-11-07: mỗi tài khoản theo giá broker của mình**, nhiều nguồn giá song song, không trộn), MT-12..15 (Gateway báo danh tính terminal, liên kết MT5, phát hiện đổi tài khoản, nhiều terminal MT5 trên một máy). Người dùng muốn **một Gateway quản lý nhiều terminal** (mỗi terminal một nhánh, token riêng).
- **1A-C21** (mới, ghi ở bảng 1A): nến cuối tuần bị giữ lại tới thứ Hai.
- **Câu hỏi còn treo cho người dùng:** token Gateway do ADMIN phát (hiện tại, DEC-16) hay mỗi USER tự lấy — người dùng chưa chọn, giữ ADMIN phát. Tài khoản trống `u-…` của Lord Trade: người dùng tạm giữ.

### 1A — Giá MT5 (OHLC, tick, spread, thông tin symbol/tài khoản)

| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| ING-01 | Cửa nạp nến chung: kiểm tra, khử trùng, revision, cờ chất lượng, quarantine, payload gốc | `[x]` | `ingestion/candles.py` |
| ING-02 | Point-in-time cho nến (`available_at`; backfill = `close_time` + cờ `BACKFILL`) | `[x]` | `storage/candles.py` |
| ING-03 | Trùng mâu thuẫn trong cùng batch → cách ly `CONFLICTING_DUPLICATE` | `[x]` | |
| ING-04 | Nguồn dữ liệu mẫu tất định (luôn gắn nhãn SAMPLE) | `[x]` | `ingestion/sources/sample.py` |
| ING-05 | Nguồn CSV + CLI `import-csv` (bắt buộc `--server-tz`) | `[x]` | `ingestion/sources/csv_file.py`, `ingestion/cli.py` |
| ING-06 | R1 kiểm tra múi giờ (> 1% nến ngoài giờ → từ chối cả lô) | `[x]` | `csv_file.check_sessions` |
| ING-07 | Cổng nhận nến từ Gateway (token, dry_run, ≤ 2.000 nến, đồng hồ backend) | `[x]` | `api/ingest.py` |
| GW-01 | Gateway chỉ đọc, test quét mã nguồn chặn hàm giao dịch | `[x]` | `mt5_gateway/` — **không thêm đặt lệnh vào package này** |
| GW-02 | Quy đổi giờ server IANA → UTC, chỉ nến đã đóng | `[x]` | `timeconv.py`, `reader.py` |
| GW-03 | `check` 9 bước, `run` nạp bù + 5 giây/lần, backoff, heartbeat | `[x]` | |
| GW-04 | Chạy thật với MetaQuotes-Demo XAUUSD M15 | `[x]` | 9/9, 5.000 nến, tự kết nối lại |
| ING-14 | Khung **H1, H4, D1** (cho Regime và bối cảnh khung lớn), căn theo giờ server broker | `[~]` | Code + test xong 2026-11-07 (`market/timeframes.py`, `api/ingest.py`, Gateway `GT_TIMEFRAMES`). Chờ kiểm trên máy người dùng (MetaQuotes-Demo) |
| GW-08 | Gateway gửi **tick/bid/ask/spread sống** (vẫn chỉ đọc) | `[ ]` | |
| ING-08 | Nạp và lưu tick/bid/ask/spread point-in-time | `[ ]` | Lưu gọn (lấy mẫu hoặc tổng hợp theo giây), có chính sách giữ dữ liệu |
| GW-09 | Gateway đọc thông tin tài khoản (equity, margin, đòn bẩy) và symbol (stops level, freeze level, swap, commission nếu có) | `[ ]` | Vẫn chỉ đọc; dùng cho GĐ5 và đối soát GĐ9 |
| GW-06 | Gateway chạy như dịch vụ Windows, tự khởi động cùng máy | `[ ]` | Đóng gói `.exe` build trên runner Windows |
| GW-07 | Hàng đợi bền vững trên đĩa + tự nạp bù khi gián đoạn dài | `[ ]` | Hiện gián đoạn > 5 giờ phải chạy lại `run` |
| ING-15 | Nhận diện **đổi tài khoản / đổi broker / đổi symbol** → tách nguồn dữ liệu, không trộn | `[ ]` | Khóa nguồn theo (server, symbol); đổi thì cần xác nhận người dùng |
| ING-16 | Phát hiện lệch đồng hồ Gateway ↔ backend ↔ server MT5 | `[ ]` | Liên quan OPS-12 |

| Mã | Tình huống | Hành vi bắt buộc | TT |
| --- | --- | --- | --- |
| 1A-C01 | Nến chưa đóng / thời gian ở tương lai | Cách ly `BAR_NOT_CLOSED` | `[x]` |
| 1A-C02 | Nến trùng giống hệt / khác giá (khác batch / cùng batch) | Bỏ qua / revision mới / cách ly `CONFLICTING_DUPLICATE` | `[x]` |
| 1A-C03 | OHLC sai (high < low, giá ≤ 0, NaN/Inf, volume âm, thời gian không tz, lệch khung) | Cách ly với lý do cụ thể | `[x]` |
| 1A-C04 | Spike (nến/khoảng nhảy > 8× trung vị) | Gắn cờ, hạ độ tin cậy, không tạo S/R | `[x]` |
| 1A-C05 | Feed đóng băng (≥ 4 nến giống hệt) | `FROZEN_FEED`, analyst STALE | `[x]` |
| 1A-C06 | Thiếu nến giữa phiên | R2 chặn nếu độ phủ < 99% | `[x]` |
| 1A-C07 | Tuần lệch DST châu Âu/Mỹ; giờ mơ hồ/không tồn tại ở giờ server | Quy đổi đúng / bỏ nến mơ hồ, không đoán | `[x]` |
| 1A-C08 | Broker đổi múi giờ server (khác `GT_SERVER_TZ`) khi đang chạy | Phát hiện qua tick sống định kỳ (không chỉ lúc `check`) → dừng gửi + cảnh báo | `[~]` (chỉ kiểm lúc khởi động) |
| 1A-C09 | Gateway tắt lâu (> 5 giờ, > 5.000 nến) | Tự nạp bù toàn bộ khoảng thiếu khi chạy lại; vẫn thiếu → báo rõ | `[~]` |
| 1A-C10 | MT5 mất kết nối / terminal tắt / đăng xuất | Heartbeat STALE sau 30 giây, Dashboard báo mất kết nối, analyst STALE | `[~]` (chưa có trigger Safety — GĐ8) |
| 1A-C11 | Đổi tài khoản demo → thật, hoặc đổi broker | Tách nguồn, không trộn; tài khoản thật → cảnh báo rõ | `[~]` (có cảnh báo REAL, chưa tách nguồn) |
| 1A-C12 | Symbol tên khác (`XAUUSDm`, `XAUUSD.r`) | Cấu hình `GT_BROKER_SYMBOL`, lưu chuẩn thành `XAUUSD` | `[x]` |
| 1A-C13 | Tick đảo thứ tự / trùng / bid > ask / spread âm | Bỏ tick lỗi + đếm, không đổi thứ tự lịch sử | `[ ]` |
| 1A-C14 | Spread giãn lúc rollover (đầu phiên) hoặc ra tin | Gắn cờ `WIDE_SPREAD`; lưu đúng giá trị thật | `[~]` (R5 trên nến) |
| 1A-C15 | Tick vẫn tới khi lịch nói đóng cửa | Lưu kèm cờ, không tính là thị trường mở; nhiều lần → `CALENDAR_MISMATCH` | `[ ]` |
| 1A-C16 | Dữ liệu tới muộn (sau khi analyst đã chạy) | Lưu với `available_at` thật, không viết lại quá khứ | `[x]` |
| 1A-C17 | Backend khởi động lại giữa lúc nạp batch | Gửi lại không nhân đôi | `[x]` |
| 1A-C18 | Token sai/thiếu, batch quá lớn, symbol/khung không đúng | 401 / 413-422 / từ chối, ghi lại | `[x]` |
| 1A-C19 | Nến D1/H4 căn theo giờ server khác nửa đêm UTC | Lưu đúng `open_time` theo broker, không tự cắt lại | `[x]` (`tests/test_higher_timeframes.py`) |
| 1A-C20 | Đồng hồ máy chạy Gateway lệch | Backend dùng đồng hồ của mình; lệch lớn → cảnh báo | `[~]` |
| 1A-C21 | Nến cuối phiên trước cuối tuần / ngày lễ (MT5 vẫn coi là vị trí 0 "đang chạy" vì chưa có nến kế) | Hiện tại: chỉ gửi khi thị trường mở lại (an toàn, trễ ~2 ngày; phát hiện 2026-11-06 trên máy người dùng). Cải tiến: coi là đã đóng khi `open + khung ≤ giờ server` **và** lịch broker báo đóng cửa; test DST, cuối tuần, ngày lễ, nghỉ giữa phiên | `[ ]` |

### 1B — Lịch thị trường và ngày lễ

| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| CAL-01 | Lịch tham chiếu New York (CN 18:00 → T6 17:00, nghỉ 17:00–18:00) | `[x]` | `market/hours.py` |
| CAL-02 | Lịch broker (giờ server) giao lịch tham chiếu | `[x]` | `BrokerSessions`, `MarketCalendar` |
| CAL-03 | Bảng **ngày lễ / đóng sớm** có phiên bản (Mỹ: năm mới, MLK, Presidents, Good Friday, Memorial, Juneteenth, Independence, Labor, Thanksgiving, Giáng sinh) | `[ ]` | Ghi rõ nguồn; đối chiếu dữ liệu thật để phát hiện sai (`CALENDAR_MISMATCH`) |
| CAL-04 | Dùng `MarketCalendar` cho cờ `GAP` lúc nạp và R1 | `[ ]` | |
| CAL-05 | Thông báo đổi giờ giao dịch đặc biệt của broker (cập nhật tay, có phiên bản) | `[ ]` | |

| Mã | Tình huống | Hành vi bắt buộc | TT |
| --- | --- | --- | --- |
| 1B-C01 | Ngày lễ đóng sớm (ví dụ Labor Day 07/09/2026 thiếu 10 nến) | Không coi là thiếu nến; phân tích không bị chặn oan | `[ ]` |
| 1B-C02 | Ngày lễ rơi vào cuối tuần, nghỉ bù | Theo bảng ngày lễ của năm đó | `[ ]` |
| 1B-C03 | Broker mở/đóng khác bảng ngày lễ | `CALENDAR_MISMATCH` hoặc R2 chặn, cảnh báo cập nhật bảng | `[ ]` |
| 1B-C04 | Giáng sinh – năm mới (nhiều ngày thanh khoản thấp) | Đúng lịch; gắn cờ thanh khoản thấp | `[ ]` |

### 1C — Lịch kinh tế (← DEC-01)

| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| DB-08 | Bảng lịch kinh tế / tin tức / series vĩ mô (append-only, point-in-time) | `[ ]` | Migration mới |
| ING-09 | Nạp **lịch công bố** (CPI, NFP, FOMC, PCE, GDP, PPI, bán lẻ, thất nghiệp hằng tuần…) cho vài tháng tới | `[ ]` | `releaseAt` theo UTC, giữ múi giờ gốc |
| ING-17 | Nạp **số actual** ngay khi công bố, đo độ trễ | `[ ]` | |
| ING-18 | Nạp **forecast/consensus** và **previous** | `[!]` | ← DEC-01 |
| ING-19 | Ghi nhận **sửa số kỳ trước** (revision) | `[ ]` | Không viết lại quá khứ |
| ING-20 | Mức quan trọng sự kiện có phiên bản (cao/trung/thấp) | `[ ]` | |

| Mã | Tình huống | Hành vi bắt buộc | TT |
| --- | --- | --- | --- |
| 1C-C01 | Chưa công bố vs actual = 0 | Hai trạng thái khác nhau, không nhầm | `[ ]` |
| 1C-C02 | Công bố bị **hoãn/hủy** (ví dụ chính phủ Mỹ đóng cửa) | Cập nhật lịch, ghi lịch sử thay đổi; cửa sổ rủi ro theo giờ mới | `[ ]` |
| 1C-C03 | Đổi giờ công bố / hai sự kiện cùng giờ | Đúng giờ mới; gộp cửa sổ rủi ro | `[ ]` |
| 1C-C04 | Giờ công bố qua DST Mỹ | Quy đổi đúng từ giờ ET | `[ ]` |
| 1C-C05 | Nguồn chết đúng lúc công bố | Coi là "chưa biết", **kéo dài** cửa sổ chặn, cảnh báo | `[ ]` |
| 1C-C06 | Hai nguồn lệch nhau / sự kiện bị trùng | Khử trùng theo khóa; lệch → cờ, dùng nguồn chính | `[ ]` |
| 1C-C07 | Không có forecast | Ghi "không đủ dữ liệu" cho phần bất ngờ, vẫn tạo cửa sổ rủi ro | `[ ]` |
| 1C-C08 | Số sửa đổi kỳ trước lớn | Lưu revision, có thể gắn cờ | `[ ]` |

### 1D — Tin tức (← DEC-02)

| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| ING-10 | Khung nạp tin: khử trùng theo fingerprint, `publishedAt` + `ingestedAt` + URL + nội dung gốc | `[ ]` | Nguồn tin là **danh sách cấu hình được** (DEC-02): thêm/bật/tắt nguồn RSS không sửa code, mỗi nguồn có ghi chú giấy phép |
| ING-21 | Nguồn chính thức: tuyên bố/biên bản/phát biểu Fed, Bộ Tài chính, BLS | `[ ]` | |
| ING-22 | Nguồn tin tổng hợp | `[!]` | ← DEC-02 |
| ING-23 | Nhận diện ngôn ngữ, thực thể cơ bản (Fed, lạm phát, vàng, USD, địa chính trị) | `[ ]` | |

| Mã | Tình huống | Hành vi bắt buộc | TT |
| --- | --- | --- | --- |
| 1D-C01 | Cùng tin từ nhiều nguồn | Một bản ghi gốc + liên kết | `[ ]` |
| 1D-C02 | Bài bị sửa sau khi đăng | Lưu phiên bản mới, giữ bản cũ | `[ ]` |
| 1D-C03 | Thiếu/sai `publishedAt`, sai múi giờ | Dùng `ingestedAt`, gắn cờ | `[ ]` |
| 1D-C04 | Nội dung độc hại (prompt injection), quá dài, rỗng, không phải tiếng Anh | Lưu nguyên văn như dữ liệu, **không bao giờ thực thi**; giới hạn độ dài; gắn cờ | `[ ]` |
| 1D-C05 | Nguồn chết / bị giới hạn tần suất | Trạng thái nguồn STALE/MISSING, backoff | `[ ]` |
| 1D-C06 | Tin cũ được đăng lại | Nhận diện bằng fingerprint, không coi là tin mới | `[ ]` |

### 1E — Vĩ mô (← DEC-03, DEC-04, DEC-07)

| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| ING-11 | Khung series vĩ mô theo `releaseAt` (point-in-time, revision) | `[ ]` | |
| ING-24 | DXY hoặc chỉ số USD thay thế (ghi rõ đó là gì) | `[!]` | ← DEC-03 |
| ING-25 | Lợi suất thực 10 năm (TIPS) | `[ ]` | Công bố trễ 1 ngày làm việc |
| ING-26 | Lợi suất danh nghĩa 2 năm, 10 năm | `[ ]` | |
| ING-27 | Kỳ vọng lãi suất Fed hoặc proxy | `[!]` | ← DEC-04 |

| Mã | Tình huống | Hành vi bắt buộc | TT |
| --- | --- | --- | --- |
| 1E-C01 | Số liệu ngày D công bố ngày D+1 | `available_at` = lúc công bố thật, không dùng sớm | `[ ]` |
| 1E-C02 | Ngày nghỉ không có giá trị / giá trị "." | Không nội suy; để trống + cờ | `[ ]` |
| 1E-C03 | Series bị sửa / đổi tên / ngừng | Lưu revision; ngừng → MISSING + cảnh báo | `[ ]` |
| 1E-C04 | Đổi đơn vị | Kiểm tra khoảng giá trị, sai → cách ly | `[ ]` |
| 1E-C05 | Khóa API hết hạn/sai | Nguồn MISSING, cảnh báo, không lộ khóa trong log | `[ ]` |

### 1F — Vị thế và dòng tiền (← DEC-05)

| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| ING-12 | COT vàng (dữ liệu chốt thứ Ba, công bố thứ Sáu) | `[ ]` | `available_at` = thời điểm công bố |
| ING-28 | Lượng vàng nắm giữ của ETF vàng lớn | `[ ]` | DEC-05: GLD, IAU (dữ liệu quỹ tự công bố hằng ngày) |
| ING-29 | NHTW mua vàng | `[ ]` (hoãn) | Người dùng hoãn 2026-11-07 (DEC-05): dữ liệu trễ hàng tháng/quý |

| Mã | Tình huống | Hành vi bắt buộc | TT |
| --- | --- | --- | --- |
| 1F-C01 | Ngày chốt ≠ ngày công bố | Dùng ngày công bố cho point-in-time | `[ ]` |
| 1F-C02 | Công bố trễ (nghỉ lễ, chính phủ đóng cửa) | Nguồn STALE đúng TTL, không dùng số cũ như số mới | `[ ]` |
| 1F-C03 | Sửa số liệu / đổi mã hợp đồng | Revision; đổi mã → cảnh báo | `[ ]` |

### 1G — Chung cho mọi nguồn

| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| ING-13 | Store point-in-time dùng chung cho nguồn không phải nến | `[~]` | `ingestion/point_in_time.py` (chưa dùng): tái dùng hoặc thay |
| ING-30 | Trạng thái từng nguồn HEALTHY/STALE/MISSING/INVALID với **TTL riêng** từng nguồn | `[ ]` | |
| DSH-09 | Trang **"Nguồn dữ liệu"**: trạng thái, lần nhận cuối, độ trễ, số cách ly của từng nguồn | `[ ]` | |
| ING-31 | Quản lý khóa API (chỉ trong `.env`, không commit, không log) | `[ ]` | |
| ING-32 | Ghi lại giấy phép/điều khoản sử dụng của từng nguồn | `[ ]` | `docs/thiet-ke/` |
| ING-33 | Chính sách giữ dữ liệu + ước tính dung lượng (tick, tin) | `[ ]` | |
| ING-34 | Test replay: nạp lại cùng dữ liệu → cùng kết quả cho mọi nguồn | `[ ]` | |
| DSH-03 | Trang Thị trường (nến, EMA/RSI, S/R, thẻ Technical, chất lượng dữ liệu, trạng thái MT5) | `[x]` | |
| DSH-07 | Hiển thị giá sống bid/ask/spread | `[ ]` | ← GW-08 |

**Gate GĐ1:** mọi việc 1A–1G xong (trừ việc người dùng hoãn); mọi case 1A–1G có test; chạy trên máy người dùng **≥ 5 ngày giao dịch liên tục**, trong đó bắt được **ít nhất một lần công bố lớn** (CPI hoặc NFP) với giờ, actual (và forecast nếu có) đúng; trang Nguồn dữ liệu hiển thị đủ; bản sao lưu có dữ liệu mới. Bao gồm MT-12..MT-15 (liên kết + xác minh danh tính MT5) và case MT-C08, MT-C11, MT-C14 (phần dữ liệu).

### Nhật ký GĐ1

- **2026-11-07** — Người dùng chốt đủ 8 quyết định (hỏi từng câu): DEC-06 ngân sách 0 đồng (chỉ nguồn miễn phí); DEC-01 lịch + actual từ nguồn chính thức Mỹ (BLS/BEA/Fed), không forecast; DEC-02 tin chỉ từ thông cáo chính thức qua RSS, danh sách nguồn **cấu hình được**; DEC-03 chỉ số USD tự tính từ 6 cặp trên MT5 (không gọi là DXY chính thức); DEC-04 proxy Fed = lợi suất 2 năm so với lãi suất Fed (FRED), không gọi là xác suất; DEC-05 chỉ ETF GLD/IAU, NHTW hoãn (ING-29); DEC-07 khóa miễn phí FRED + BLS + BEA (hướng dẫn đăng ký khi tới 1C/1E); DEC-14 mỗi tài khoản theo giá broker của mình. Chưa code. Bước tiếp: người dùng đồng ý thứ tự làm 1A → 1G.
- **2026-11-07** — Trước khi code GĐ1, người dùng yêu cầu đơn giản hóa trang Quản trị (dòng "Tài khoản chính · Nguồn giá chung" gây hiểu nhầm, tài khoản trống `u-user_cutlot` của Lord Trade): chốt **DEC-17** (ghi ở `MT-da-nguoi-dung.md`, thiết kế `docs/thiet-ke/00-xac-thuc-phan-quyen.md` mục 17). Làm: một USER một dòng; thêm/sửa/xóa/khóa; USER xin token → ADMIN cấp (token hiện cho ADMIN) hoặc từ chối; migration 0007 (`DELETED`, bảng `gateway_token_requests` chỉ thêm dòng, bỏ tài khoản thừa — thử trên PostgreSQL 16 với dữ liệu giống máy người dùng). Kiểm chứng: backend 349 passed, ruff sạch; frontend 68 passed, tsc/eslint sạch, build OK; đột biến 11 chốt chặn → 10 làm test đỏ (chốt còn lại có Keycloak kiểm lần hai). CI `ci_stack.sh` với Keycloak thật: e2e **52/52** (tạo không sinh token, ADMIN cấp, USER xin → ADMIN từ chối, sửa thông tin trên Keycloak thật, xóa USER cấp giá → 409, xóa USER thứ hai → token 401 + không đăng nhập được), khôi phục 14/14, không có bí mật trong log. Lần chạy đầu e2e đỏ 4 mục do kịch bản kỳ vọng sai (USER thử trong CI nhận tài khoản cấp giá nên backend từ chối xóa — đúng thiết kế); đã sửa kịch bản. Máy người dùng cần: build lại `backend frontend` (migration 0007 tự chạy).
- **2026-11-07** — Người dùng chốt: **không cần sao lưu thủ công** trước khi cập nhật trong giai đoạn phát triển (tài khoản demo); chỉ sao lưu khi chạy thật, sau khi xong các giai đoạn. Không đổi container `backup` tự động. Code DEC-17 đã đẩy lên `develop` để người dùng build lại.
- **2026-11-07** — Lập kế hoạch + checklist GĐ1 ở `docs/ke-hoach/GD1-ke-hoach.md` (10 bước). Người dùng chốt **giữ thứ tự đề xuất**, bắt đầu bước 1 (ING-14 khung H1/H4/D1) ở phiên chat mới.
- **2026-11-07** — **Bước 1 (ING-14 + 1A-C19), phần code.** Gateway đọc thẳng H1/H4/D1 từ MT5 (không ghép từ M15), gửi kèm `server_tz`; cấu hình `GT_TIMEFRAMES` (mặc định `M15,H1,H4,D1`, M15 luôn có). `check` thêm bước 10 "Khung H1/H4/D1": khung thiếu lịch sử / backend từ chối / có nến lệch ranh giới giờ server → **CẢNH BÁO** và không đồng bộ khung đó (M15 vẫn chạy). `run`: nạp bù từng khung; khung lớn chỉ gửi khi có nến mới đóng hoặc 60 giây/lần (bắt bản sửa); lỗi riêng một khung không làm ngừng M15. Backend: thêm `Timeframe.D1`; H4/D1 `server_aligned` — kiểm căn khung theo **đồng hồ server** (D1 = 00:00, H4 = 00/04/…/20 giờ server), `close_time` = ranh giới kế tiếp theo giờ server (ngày đổi giờ dài 23/25 h hoặc 3/5 h; giờ mơ hồ lấy lần muộn hơn, giờ không tồn tại lấy lúc đồng hồ vượt qua → không bao giờ coi nến đóng sớm). Nến D1 cắt theo nửa đêm UTC → cách ly `MISALIGNED_TIME`, không tự cắt lại. API: H4/D1 bắt buộc `server_tz` hợp lệ, và phải giống `GT_BROKER_SERVER_TZ` nếu backend có đặt (khác → 422). R1 áp cho M15 và H1; không áp cho H4/D1 (nến vắt qua giờ nghỉ; múi giờ đã được R1 kiểm trên M15 của cùng Gateway). GAP cho H4/D1: nến "lẽ ra phải có" khi thị trường mở ở bất kỳ lúc nào trong nến. Contract `Candle`: M1–H1 vẫn `close = open + khung`; H4/D1 cho lệch tối đa 1 giờ. Nhịp tim báo `timeframes`. Không đổi schema DB (cột `timeframe` sẵn có). Test: backend +35 (giá trị tham chiếu tính tay cho Athens mùa đông/hè, tiến giờ 29/03, lùi giờ 25/10, Santiago giờ không tồn tại, Havana giờ mơ hồ, nến chưa đóng tính theo độ dài thật 25 h/3 h, cuối tuần không GAP, thiếu ngày giữa tuần có GAP, trùng/revision/xung đột, các khung tách chuỗi, chạy trên bộ nhớ + SQLite); Gateway +11. Soát lại bằng kịch bản riêng (Gateway giả → backend thật, lịch sử 70 ngày qua lùi giờ 25/10 và qua tiến giờ 29/03): gom M15 đã lưu theo ranh giới giờ Athens khớp 100% OHLC của H1/H4/D1, 0 cách ly, 0 GAP nhầm cuối tuần. **Giới hạn:** với XAUUSD + Europe/Athens, DST đổi vào sáng Chủ nhật khi thị trường đóng nên nến 23/25 h không xuất hiện thực tế (chỉ test ở mức hàm); chưa có trang xem H1/H4/D1 (chỉ lưu, dùng ở GĐ2); nến D1/H4 cuối tuần vẫn tới thứ Hai mới gửi (1A-C21, bước 3); ngày lễ chưa có lịch (bước 2) nên thiếu nến ngày lễ sẽ bị gắn GAP. Còn: kiểm trên máy người dùng.
