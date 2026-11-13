# Thiết kế — Khung nạp tin (GĐ1 bước 10a — ING-10, 1D)

> Tạo 2026-11-13. Code: `backend/src/gold_trading/ingestion/news.py`, cấu hình `ingestion/news_sources.json`, test `tests/test_news.py`. Liên quan: DEC-02 (tin chỉ từ thông cáo chính thức qua RSS, danh sách nguồn cấu hình được), ING-30 (trạng thái nguồn), ING-32 (điều khoản), khung point-in-time `10-nguon-ngoai.md`.
>
> 10a dựng **khung**; 10b thêm nguồn thật đầu tiên (RSS Fed, mục 9).

## 1. Danh sách nguồn cấu hình được (DEC-02)

File JSON, mặc định `ingestion/news_sources.json` (đóng gói cùng backend, hiện **rỗng**). Đổi sang file khác bằng biến `GT_NEWS_SOURCES_FILE`. Một mục:

```json
{"name": "fed_press", "provider": "fed", "url": "https://www.federalreserve.gov/feeds/press_all.xml",
 "enabled": true, "license_note": "Public domain; ghi nguồn Federal Reserve Board",
 "poll_minutes": 15, "fetch_ttl_hours": 6}
```

| Quy tắc | Lý do |
| --- | --- |
| Sai **bất kỳ** chỗ nào → từ chối **cả file** (không bật nửa vời) | Cấu hình sai mà vẫn chạy một phần thì khó nhận ra |
| Khóa lạ (gõ nhầm `enabeld`) → lỗi | Gõ nhầm không được âm thầm thành giá trị mặc định |
| Bật được chỉ khi điều khoản `provider` là `VERIFIED` (`SourceRegistry`, ING-32); nguồn tắt thì khai báo trước được | Thêm nguồn **không sửa code** nếu nhà cung cấp đã `VERIFIED`; nhà cung cấp mới vẫn phải đọc điều khoản + sửa `source_terms.py` (cố ý) |
| `license_note` bắt buộc (≤ 500 ký tự) | Mỗi nguồn có ghi chú giấy phép (ING-10) |
| URL chỉ `https`, có tên máy, không tài khoản/mật khẩu, không `key=` / `token=` / `secret=` / `password=` | Khóa chỉ để trong `.env` (ING-31) |
| `poll_minutes` 5–1440, `fetch_ttl_hours` 1–168 và phải dài hơn chu kỳ tải | Chặn gõ nhầm (gọi dồn / TTL ngắn hơn chu kỳ → luôn STALE) |
| Không `data_ttl` | Nguồn tin im lặng nhiều ngày (không có thông cáo) vẫn là khỏe |

## 2. Đọc RSS 2.0 / Atom an toàn

- Cỡ tối đa 5 MB; tối đa 300 mục mỗi lần tải (thừa → bỏ, `truncated`).
- **Từ chối mọi DOCTYPE / ENTITY** (`FEED_DTD_FORBIDDEN`) ở hai lớp: lọc byte + lượt quét expat dừng ngay tại khai báo DOCTYPE (lớp thứ hai bắt DOCTYPE mã hóa UTF-16 mà lọc byte không thấy — tìm ra khi soát lại). Chặn XXE và "billion laughs". RSS/Atom không cần DTD.
- Không phải XML / bảng mã expat không hỗ trợ (UTF-32…) → `FEED_NOT_XML`; trang HTML (vd. "Access Denied") / gốc lạ → `FEED_FORMAT_UNKNOWN`. Cả hai → lần kiểm `INVALID` (ING-30).
- RSS: `title`, `link`, `guid`, `description` (thiếu → `content:encoded`), `pubDate` (thiếu → `dc:date`). Atom: `title`, `link rel=alternate`, `id`, `summary` (thiếu → `content`), `published` (thiếu → `updated`). RSS 1.0 (RDF) chưa hỗ trợ — thêm khi một nguồn thật cần.

## 3. Thời gian (1D-C03)

`published_at` đọc theo RFC 822 (RSS, gồm tên múi giờ `EST`/`EDT`) hoặc RFC 3339 (Atom), đổi sang UTC.

| Tình huống | Xử lý | Cờ |
| --- | --- | --- |
| Thiếu | `event_time = ingested_at` | `PUBLISHED_AT_MISSING` |
| Không đọc được / năm < 1990 | như trên | `PUBLISHED_AT_INVALID` |
| Không có múi giờ (gồm `-0000`: RFC 2822 nghĩa là "không rõ") | như trên — **không đoán múi giờ** | `PUBLISHED_AT_NO_TZ` |
| Muộn hơn `now` quá 5 phút (nguồn sai múi giờ) | như trên | `PUBLISHED_AT_FUTURE` |
| Muộn hơn `now` ≤ 5 phút (lệch đồng hồ nhỏ) | kẹp về `now` | — |
| Cũ hơn 7 ngày ở lần đầu thấy | giữ giờ đăng | `OLD_ON_ARRIVAL` |

Luôn `event_time <= ingested_at` (không biết trước). `available_at` để trống → `known_at = ingested_at`.

## 4. Nội dung (1D-C04)

- Nội dung tin **chỉ là dữ liệu**: không bao giờ thực thi, không làm theo; khi đưa cho AI (GĐ3) phải đóng khung là dữ liệu.
- Làm sạch để hiển thị/so khớp: bỏ thẻ HTML (cả thẻ mã hóa `&lt;b&gt;`), giải mã ký tự HTML, bỏ ký tự điều khiển / C1 / ký tự ẩn hướng chữ & độ rộng 0, gộp khoảng trắng. Kết quả là **văn bản thuần** — frontend phải hiển thị như văn bản, không như HTML.
- Giới hạn: tiêu đề 500, tóm tắt 20.000 ký tự (cắt → `CONTENT_TRUNCATED`); guid 1024; URL 2048.
- Rỗng → `CONTENT_EMPTY`. Liên kết không phải `http(s)` (vd. `javascript:`, `data:`) hoặc tương đối → bỏ, `URL_INVALID`.
- Câu dạng "ra lệnh cho AI" (`ignore previous instructions`, `system prompt`, `<system>`, "buy gold now"…) → cờ `SUSPECT_INSTRUCTIONS`; chỉ gắn cờ, không chặn (bộ lọc theo mẫu luôn có thể bị lách — lớp bảo vệ chính là không bao giờ coi nội dung là lệnh).
- Ngôn ngữ: giữ nguyên mọi ngôn ngữ; nhận diện ngôn ngữ + thực thể là ING-23 (bước 10 sau).
- Nguyên văn (`raw`, đã cắt độ dài, NUL → U+FFFD vì Postgres không lưu NUL) lưu kèm để đối chiếu.

## 5. Lưu (ING-10, 1D-C02)

- Mỗi mục = một dữ kiện `kind="news"` trong `external_records` (không cần bảng mới, không migration).
- Định danh `logical_key = "n:" + sha256(guid | URL | nội dung)[:40]` — ưu tiên guid, rồi URL, rồi dấu vân tay nội dung; không có gì → bỏ mục (`ITEM_NO_IDENTITY`, đếm `invalid`).
- **Bài bị sửa** (khác tiêu đề / tóm tắt / URL so với bản mới nhất) → **revision mới**, giữ bản cũ; `event_time` + `first_seen_at` giữ theo revision 0, cờ `EDITED`. Chỉ đổi `pubDate` → **không** coi là sửa (tránh nguồn đổi giờ liên tục tạo revision).
- Y hệt → không ghi (`duplicate`). Hai mục cùng định danh trong một lần tải: giống → `duplicate`, khác → giữ mục đầu, mục sau `conflict` (`ITEM_DUPLICATED_IN_FEED`).
- Một mục sửa quá 20 lần → không ghi thêm (`conflict`, `REVISION_LIMIT`) — chống nguồn "nhảy" làm phình DB.
- Payload: `title`, `summary`, `url`, `guid`, `published_raw`, `published_at`, `first_seen_at`, `content_fingerprint`, `policy_version` (`news-2026.11.13`), `flags`.

## 6. Gộp tin (1D-C01, 1D-C06)

- **Dấu vân tay nội dung** = sha256 của tiêu đề + tóm tắt sau NFKC, chữ thường, chỉ giữ chữ + số. Rỗng → không gộp.
- `news_stories(store, as_of)`: bản mới nhất của mỗi mục đã biết tại `as_of` (cửa sổ `event_time` 90 ngày), gộp theo dấu vân tay → **một tin gốc** (thấy sớm nhất; hòa thì theo nguồn, khóa) **+ các liên kết** (nguồn khác, đăng lại).
- `new_stories(store, since, as_of)`: chỉ tin có tin gốc thấy lần đầu trong `(since, as_of]`. Tin cũ đăng lại (guid/URL mới, cùng nội dung) thuộc tin gốc cũ → **không mới**.
- Point-in-time: gộp tính lại tại mỗi `as_of` → ghi sau không viết lại quá khứ (đã kiểm ngẫu nhiên, mục 8). Bài sửa khác nội dung → rời nhóm từ lúc bản sửa được biết.
- Giới hạn (cố ý, ghi lại): chỉ gộp **trùng y nội dung** (sau chuẩn hóa) — hai nguồn viết khác chữ về cùng sự kiện là hai tin (gộp theo nghĩa cần NLP, để GĐ3); bản gốc cũ hơn 90 ngày nằm ngoài cửa sổ → bản đăng lại thành tin gốc mới.

## 7. Tải + lịch tải (1D-C05, phần khung)

- `http_getter`: chuyển hướng sang tên máy khác → `UNEXPECTED_REDIRECT`; HTTP lỗi → mã ngắn (`RATE_LIMITED`, `FORBIDDEN`, `HTTP_5xx`); > 5 MB → `RESPONSE_TOO_LARGE`. Không bao giờ ghi thông điệp lỗi gốc.
- `run_once`: một dòng nhật ký lần kiểm mỗi lần (ING-30) → trạng thái HEALTHY/STALE/MISSING/INVALID như mọi nguồn.
- `due`: chỉ dựa trên nhật ký lần kiểm (khởi động lại không gọi dồn). OK → tải lại sau `poll_minutes`. Lỗi → chờ `poll × 2^(số lần lỗi liên tiếp)`, trần 6 giờ (15 phút → 30, 60, 120… phút); lỗi "chết" (`FORBIDDEN`, `AUTH_FAILED`…) → 6 giờ.
- Nối vào bộ chạy tự động ở 10b (mục 9).

## 8. Kiểm chứng (2026-11-13)

- `tests/test_news.py` 139 test (bộ nhớ + SQLite): cấu hình (20 kiểu sai, điều khoản BLOCKED / NEEDS_REVIEW / chưa ghi, file thiếu, biến môi trường), RSS/Atom, CDATA, `content:encoded`, `dc:date`, XXE, billion laughs, DOCTYPE UTF-16, bảng mã lạ, HTML "Access Denied", 300+ mục; giờ GMT / EST / EDT / ngay sau đổi DST / `-0000` / không múi giờ / tương lai xa và gần / cũ; nội dung độc (script, thẻ mã hóa, ký tự ẩn hướng chữ, NUL, câu ra lệnh, `javascript:`), quá dài, rỗng, không phải tiếng Anh; ghi lại y hệt, chỉ đổi giờ, sửa bài (point-in-time), nguồn "nhảy", trùng trong một lần tải, mục không định danh, tất cả hỏng → INVALID; gộp hai nguồn, đăng lại, cửa sổ tin mới, tin rỗng, bản sửa rời nhóm; lỗi tải / HTML thay feed → INVALID; STALE đúng TTL; backoff 30/60/120 phút → trần 6 giờ; HTTP 429/403/503, chuyển hướng lạ, quá lớn, hết giờ.
- **Soát lại bằng kịch bản riêng** (Postgres 16 thật sau `alembic upgrade head`): fuzz 20.000 feed đột biến ngẫu nhiên → chỉ lỗi `FeedParseError`, không lỗi lạ; DOCTYPE ở 5 bảng mã đều bị chặn; chuỗi 120 lần tải ngẫu nhiên (3 nguồn, sửa, đăng lại, giờ hỏng) → bộ nhớ = SQLite = Postgres ở 360 thời điểm `as_of`, kết quả quá khứ không đổi sau khi ghi thêm, mọi bản ghi `known_at <= as_of` và `event_time <= ingested_at`.
- **Lỗi tìm được khi làm:** (1) ký tự NUL trong nguyên văn làm cả mục bị cách ly (`RAW_NUL_CHAR`) → thay bằng U+FFFD; (2) thẻ giả `<system>` bị bỏ khi làm sạch nên cờ `SUSPECT_INSTRUCTIONS` không bắt được → soi trên văn bản chưa bỏ thẻ; (3) DOCTYPE mã hóa UTF-16 lọt lọc byte → thêm lượt quét expat; (4) bảng mã expat không hỗ trợ ném `ValueError` lạ → `FEED_NOT_XML`.

## 9. Nguồn thật đầu tiên: RSS Fed (10b, 2026-11-13)

| Nguồn | URL | Nội dung |
| --- | --- | --- |
| `fed_rss_monetary` | `https://www.federalreserve.gov/feeds/press_monetary.xml` | Thông cáo chính sách tiền tệ: tuyên bố FOMC, biên bản, dự báo kinh tế |
| `fed_rss_speeches` | `https://www.federalreserve.gov/feeds/speeches_and_testimony.xml` | Phát biểu + điều trần của lãnh đạo Fed |

- Điều khoản Fed `VERIFIED` (public domain, ghi nguồn Board) → chân trang web: "Lịch FOMC, thông cáo và phát biểu: Federal Reserve Board".
- Kiểm từ máy người dùng 2026-11-13: cả hai 200, 15 bài, khớp máy chủ đám mây. Feed RSS 2.0, có BOM, CDATA, `pubDate` GMT, guid = URL.
- Tải 15 phút/lần, TTL 6 giờ (Fed không công bố giới hạn tần suất; 2 feed × 96 lần/ngày ≈ 10 KB/lần). Không chọn nhanh hơn: RSS không phải đường nhanh nhất lúc công bố FOMC — cửa sổ chặn quanh FOMC đã có từ lịch (8b).
- Bộ chạy tự động: `news` nằm trong `GT_EXTERNAL_SOURCES` mặc định; mỗi nguồn tin đang bật là một việc, chạy sau các việc lịch + số. Cấu hình tin sai → **không bật nguồn tin nào**, các nguồn khác vẫn chạy, log ERROR "Không bật nguồn tin".
- Lần tải đầu nhận cả tin cũ trong feed (vd. tuyên bố FOMC 28/10) với `event_time` = giờ đăng thật, cờ `OLD_ON_ARRIVAL`; chúng không là "tin mới" theo giờ đăng.
- Lệnh xem: `python -m gold_trading.ingestion.cli tin [--dry-run] [--hours N]` — lọc theo **giờ đăng** của tin gốc, in giờ Việt Nam, kèm ghi chú giấy phép từng nguồn.
