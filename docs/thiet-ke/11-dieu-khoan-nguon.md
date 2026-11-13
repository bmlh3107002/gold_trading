# Thiết kế — Giấy phép / điều khoản từng nguồn ngoài (GĐ1 bước 7d, ING-32)

> Tạo 2026-11-13. Liên quan: DEC-02 (mỗi nguồn ghi giấy phép), DEC-05 (kiểm điều khoản GLD/IAU trước khi bật), DEC-06 (chỉ nguồn miễn phí), ING-31 (khóa API).
> Code: `backend/src/gold_trading/ingestion/source_terms.py` (`SOURCE_TERMS`). Test `tests/test_source_terms.py` kiểm code và file này **không lệch** trạng thái.

## 1. Quy tắc

- Mỗi **nhà cung cấp** có một mục ở đây, ghi: tình hình hiện biết, bằng chứng (đường dẫn), ngày kiểm, trạng thái.
- **Chỉ bật được nguồn khi trạng thái là `VERIFIED`** (đã đọc **nguyên văn** điều khoản hiện hành và thấy cách dùng dự định được phép). `SourceRegistry` từ chối bật nguồn `NEEDS_REVIEW` / `BLOCKED` / chưa có mục. Nguồn tắt thì khai báo trước được.
- Cách dùng dự định (để đối chiếu với điều khoản): **một người, dùng nội bộ**, chương trình tự tải định kỳ qua API/RSS/file chính thức, lưu trên máy để phân tích giao dịch của chính mình; **không** phân phối lại, **không** bán, **không** hiển thị công khai.
- Đổi trạng thái: sửa mục ở đây (bằng chứng + ngày) **và** `SOURCE_TERMS` trong cùng một commit. Điều khoản các trang đều ghi có thể đổi không báo trước → đọc lại khi bật nguồn và khi nguồn báo `FORBIDDEN` / `AUTH_FAILED` lạ.

## 2. Tình trạng kiểm

**Lần 1 (2026-11-13, bước 7d):** chỉ có trích đoạn kết quả tìm kiếm → tất cả `NEEDS_REVIEW`, IAU `BLOCKED`.

**Lần 3 (2026-11-13, bước 9a):** đọc được nguyên văn FRED → `BLOCKED` (cấm lưu vào database + cấm dùng cho AI); lợi suất / lãi suất Fed chuyển sang H.15 của Fed.

**Lần 2 (2026-11-13, bước 8a):** người dùng cho phép tải trực tiếp trang chính thức (chỉ đọc). Đọc **nguyên văn**: BEA, Census, Fed → `VERIFIED` (kèm nghĩa vụ ghi nguồn); GLD → `BLOCKED`. Không đọc được: FRED (hết giờ chờ), BLS và CFTC (máy chủ trả 403 "Access Denied" cho máy chủ đám mây — **không** giả trình duyệt để lách), DOL (trang cần JavaScript), Bộ Tài chính (chưa tìm được trang chính sách), iShares (trang điều khoản đổi địa chỉ, nằm trên `blackrock.com`) → giữ nguyên trạng thái. Các mục chưa đọc được ghi rõ bên dưới; phần lấy từ kết quả tìm kiếm vẫn là **trích đoạn, chưa nguyên văn**.

**Việc phải làm trước khi bật mỗi nguồn (bước 8–10):** đọc nguyên văn trang điều khoản (đường dẫn ở từng mục), ghi lại các điểm: được tải tự động không / cần khóa không / giới hạn tần suất / lưu trữ / ghi nguồn / phân phối lại / ngày hiệu lực → nếu khớp cách dùng dự định thì đổi `VERIFIED`.

Lưu ý chung cho cơ quan liên bang Mỹ: tác phẩm do nhân viên liên bang làm trong công việc thường không có bản quyền ở Mỹ, **nhưng** điều khoản API (khóa, giới hạn, cấm giả danh, dữ liệu bên thứ ba có bản quyền) vẫn áp dụng — không suy ra "được phép" chỉ từ điểm này.

## 3. Từng nhà cung cấp

<a id="fred"></a>
### FRED — Fed St. Louis (định dùng cho lợi suất, lãi suất Fed; bước 9)

- **Trạng thái:** `BLOCKED`
- **Đọc nguyên văn** 2026-11-13 (bước 9a): <https://fred.stlouisfed.org/docs/api/terms_of_use.html> và <https://fred.stlouisfed.org/legal/> (mục "Additional Terms of Use for the FRED® API"). Lý do chặn — phần cấm của API, nguyên văn:
  1. *"(l) Use the FRED® API in connection with storing, caching, or archiving any portion of the FRED® Services or FRED® Content; … or incorporating any FRED® Content in any database, compilation, archive, cache, or other medium."* — hệ thống **phải** lưu số liệu point-in-time vào database (ING-11, ING-13, replay, backtest) → trái trực tiếp.
  2. *"(k) Use the FRED® API to access the FRED® Services or FRED® Content in connection with the development or training of any software program or system or machine learning, … or any other program or process commonly known as artificial intelligence."* — dự án có GĐ7 huấn luyện AI.
  3. Phần chung còn cấm dùng thương mại khi chưa có phép bằng văn bản (mục j) và yêu cầu câu ghi nguồn "This product uses the FRED® API but is not endorsed or certified by the Federal Reserve Bank of St. Louis."
- **Hệ quả (người dùng chọn 2026-11-13):** lợi suất 2 năm / 10 năm / thực 10 năm + lãi suất Fed hiệu dụng lấy từ **trang phát hành H.15 của Fed (Hội đồng Thống đốc)** — nhà cung cấp `fed` đã `VERIFIED`. Không đăng ký khóa FRED (DEC-07 bỏ phần FRED). Lưu ý: chính trang Fed giới thiệu FRED thay cho "Data Download Program" sắp gỡ (31/3/2027, 1/7/2027) — **không** dùng DDP mà đọc trang phát hành H.15.

<a id="bls"></a>
### BLS — Cục Thống kê Lao động (CPI, NFP, PPI; lịch + actual; RSS; bước 8, 10)

- **Trạng thái:** `NEEDS_REVIEW`
- Biết được: API bản 2 **cần khóa**; giới hạn **500 truy vấn/ngày** (có khóa), **50 yêu cầu / 10 giây**; khóa phải **gia hạn ít nhất mỗi năm** (→ khóa hết hạn sẽ ra `AUTH_FAILED`/`KEY_*`, nguồn MISSING — ING-30). Chữ, bảng, biểu đồ của BLS là **public domain**, dùng lại được nếu **ghi nguồn**; ảnh và logo không được dùng; không được sửa nội dung mà vẫn ghi nguồn BLS.
- Cần đọc: <https://www.bls.gov/developers/termsOfService.htm>, <https://www.bls.gov/developers/api_faqs.htm>, <https://www.bls.gov/bls/linksite.htm>.
- Lần 2 (2026-11-13): trang web BLS trả **403 Access Denied** cho máy chủ đám mây → chưa đọc được nguyên văn; không giả trình duyệt để lách. Kênh chính thức cho chương trình là API `api.bls.gov` (có khóa).

<a id="bea"></a>
### BEA — Cục Phân tích Kinh tế (GDP, PCE; bước 8)

- **Trạng thái:** `VERIFIED`
- **Đọc nguyên văn** 2026-11-13: <https://apps.bea.gov/API/_pdf/bea_api_tos.pdf> (2 trang). Được dùng API để "search, display, analyze, retrieve, view and otherwise get information" — khớp cách dùng dự định. Nghĩa vụ:
  1. **Hiển thị rõ trong ứng dụng** câu: *"This product uses the Bureau of Economic Analysis (BEA) Data API but is not endorsed or certified by BEA."* → phải có trên web (trang Nguồn dữ liệu / chân trang) **trước khi bật** nguồn.
  2. Không dùng tên BEA để ngụ ý bảo trợ; không sửa nội dung mà vẫn ghi nguồn BEA (hệ thống lưu số gốc, phần tính toán ghi rõ là của hệ thống).
  3. Giới hạn truy cập "theo Thỏa thuận hoặc do BEA đặt ra" — cố tình vượt giới hạn có thể bị chặn → bộ nạp phải tôn trọng giới hạn trong hướng dẫn API (100 yêu cầu / 100 MB / 30 lỗi mỗi phút theo nguồn thứ cấp).
- **Bước 8c (2026-11-13):** (1) câu ghi nguồn đã có **nguyên văn** ở chân mọi trang web (`SourceAttribution.tsx`, test khóa nguyên văn). (3) giới hạn đọc nguyên văn trong "BEA API For Data Retrieval User Guide" (bản 20/04/2026): **100 yêu cầu / 100 MB / 30 lỗi mỗi phút**, vượt → HTTP 429 + `RETRY-AFTER`; BEA khuyên chỉ gọi theo lịch công bố, không gọi tự động khi chưa có số mới → bộ nạp gọi 3 yêu cầu mỗi lần, chỉ trong 90 phút sau giờ công bố + đối chiếu mỗi tuần (`13-bea.md`). Trang "Guidelines for Citing BEA" (đọc nguyên văn): khuyến khích ghi nguồn, không được ngụ ý BEA xác nhận. Lịch công bố (ICS, JSON) và file số liệu NipaData tải từ `www.bea.gov` / `apps.bea.gov` không cần khóa; file lịch lưu làm dữ liệu test, có ghi nguồn (`backend/tests/fixtures/bea/README.md`).
- Thỏa thuận dẫn chiếu thêm "Website Policies" và chính sách riêng tư của bea.gov (chưa đọc; không có điều khoản dữ liệu riêng được nêu). API cung cấp "nguyên trạng", có thể dừng bất kỳ lúc nào → đúng thiết kế ING-30 (nguồn MISSING/STALE).

<a id="census"></a>
### Census — Cục Điều tra Dân số (doanh số bán lẻ; bước 8, bổ sung DEC-01)

- **Trạng thái:** `VERIFIED`
- **Đọc nguyên văn** 2026-11-13: <https://www.census.gov/data/developers/terms-of-service.html> — văn bản cùng mẫu với BEA. Nghĩa vụ:
  1. **Hiển thị rõ trong ứng dụng**: *"This product uses the Census Bureau Data API but is not endorsed or certified by the Census Bureau."* → có trên web **trước khi bật**.
  2. Không ngụ ý bảo trợ; không sửa nội dung mà vẫn ghi nguồn Census.
  3. Không dùng dữ liệu để nhận diện cá nhân/doanh nghiệp (không liên quan: chỉ dùng số tổng doanh số bán lẻ toàn quốc).
- **Khóa bắt buộc** (nguyên văn, <https://www.census.gov/data/developers/guidance/api-user-guide.Query_Limits.html>, sửa lần cuối 14/05/2026): *"An API key must be used with all data queries made to the Census Data API."* Tối đa 50 biến mỗi truy vấn. Đăng ký miễn phí, email phải có đuôi .com/.net/.org/.gov/.edu → biến `GT_CENSUS_API_KEY` (ING-31).
- **Bước 8d (2026-11-13):** câu ghi nguồn (1) đã có **nguyên văn** ở chân mọi trang web (`SourceAttribution.tsx`, test khóa nguyên văn). Khóa sai / thiếu: API trả 302 sang `invalid_key.html` / `missing_key.html` (kiểm thật). Trang lịch + lịch bán lẻ trên `www.census.gov` không cần khóa; lưu làm dữ liệu test có ghi nguồn (`backend/tests/fixtures/census/README.md`). Chỉ dùng số tổng toàn quốc (không liên quan điều cấm nhận diện cá nhân/doanh nghiệp).

<a id="dol"></a>
### DOL — Bộ Lao động (trợ cấp thất nghiệp hằng tuần; bước 8, bổ sung DEC-01)

- **Trạng thái:** `VERIFIED` (2026-11-13, bước 8f — **chỉ cho bản tin PDF `www.dol.gov/ui/data.pdf`**, không cho API `data.dol.gov`)
- **Đọc nguyên văn** 2026-11-13: <https://www.dol.gov/general/aboutdol/copyright> — *"Materials created by the federal government are generally part of the public domain and may be used, reproduced and distributed without permission. … such materials may not be used in a manner that implies any affiliation or endorsement by the DOL … You may properly credit public domain materials obtained from a DOL website to the U.S. Department of Labor and/or https://www.dol.gov."* Con dấu/logo DOL không được dùng; nội dung bên thứ ba có bản quyền riêng (bản tin trợ cấp thất nghiệp là số liệu của DOL/ETA). Trang "Website Policies" (`/general/aboutdol/website-policies`) đọc 2026-11-13: không thấy điều cấm tải tự động. Cách dùng: tải **một** file PDF công khai, vài lần quanh 8:30 ET thứ Năm + đối chiếu mỗi tuần. Máy người dùng tải được (200, 2026-11-13). Nghĩa vụ: ghi nguồn "U.S. Department of Labor" trên web (chân trang), không ngụ ý bảo trợ.
- Biết được (thông cáo DOL + bài báo): cổng dữ liệu `data.dol.gov`, API miễn phí, **đăng ký qua Login.gov để nhận khóa**, cần khóa cho mọi yêu cầu. Chưa thấy điều khoản sử dụng, giới hạn. Phải kiểm thêm: số liệu tuần có sẵn qua API ngay giờ công bố không (một bộ dữ liệu ghi trễ ít nhất 30 phút) — nếu trễ thì nguồn actual lúc công bố phải là thông cáo trên `dol.gov`.
- Cần đọc: <https://data.dol.gov>, <https://www.dol.gov/newsroom/releases/oasam/oasam20260218>.
- Lần 2 (2026-11-13): `data.dol.gov` là ứng dụng cần JavaScript, không đọc được bằng tải trang → chưa thấy điều khoản.

<a id="fed"></a>
### Fed — Hội đồng Thống đốc (FOMC: lịch, tuyên bố; RSS; bước 8, 10)

- **Trạng thái:** `VERIFIED`
- **Đọc nguyên văn** 2026-11-13: <https://www.federalreserve.gov/disclaimer.htm>, mục "Copyright/trademark": *"Unless otherwise indicated, information on Board's website is in the public domain and may be copied and distributed without permission. Please cite to the Board as the source of the information."* Nghĩa vụ: **ghi nguồn Federal Reserve Board**; không dùng con dấu/logo; nội dung đánh dấu của bên ngoài Board thì phải xin phép bên đó; không "framing" trang Fed.
- **Sửa lại lần 1:** trích đoạn tìm kiếm cũ ("có thể có bản quyền") thực ra nói về **trang bên ngoài** mà Fed dẫn link tới, không phải nội dung của Board.
- Trang RSS (<https://www.federalreserve.gov/feeds/>) không có điều khoản riêng → áp dụng mục trên.

<a id="treasury"></a>
### Bộ Tài chính Mỹ (RSS thông cáo; bước 10)

- **Trạng thái:** `NEEDS_REVIEW`
- Biết được: có RSS thông cáo báo chí trên `home.treasury.gov`. **Chưa tìm thấy** trang chính sách/bản quyền hiện hành (chỉ có bản lưu cũ).
- Cần đọc: trang "Site Policies and Notices" trên <https://home.treasury.gov>.
- Lần 2 (2026-11-13): tải được trang chủ nhưng chưa tìm thấy đường dẫn trang chính sách.

<a id="cftc"></a>
### CFTC — báo cáo COT (vị thế vàng; bước 9e)

- **Trạng thái:** `VERIFIED`
- **Đọc nguyên văn** 2026-11-13 (bước 9e) **từ máy người dùng** (máy chủ đám mây bị `www.cftc.gov` trả 403): <https://www.cftc.gov/webpolicy/index.htm>, mục "Copyright": *"Government information at the CFTC website is in the public domain. Public domain information may be freely distributed and copied, but it is requested that in any subsequent use the CFTC be given appropriate acknowledgement."* Nội dung do bên ngoài đóng góp có thể có bản quyền riêng — báo cáo COT là số liệu do CFTC lập, không thuộc loại đó. Không thấy điều cấm tải tự động trên trang này (lọc từ khóa automat/scrap/robot/crawl/bulk/restrict).
- **Nghĩa vụ:** ghi nguồn CFTC (chân trang web).
- **Truy cập (từ máy người dùng, 2026-11-13):** `www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm` 200; báo cáo `www.cftc.gov/dea/futures/deacmxsf.htm` 200; **`publicreporting.cftc.gov` (API) 403** → dùng trang báo cáo văn bản, không dùng API.
- **Lịch công bố** (trang `…/CommitmentsofTraders/ReleaseSchedule/index.htm`, nguyên văn): *"released at 3:30 p.m. Eastern time … usually released on Friday … includes data from the previous Tuesday … tentative schedule of releases through 2026. Federal holidays may delay release by one or two days."* Bảng ngày 2026 chép vào code (`cftc_cot.RELEASES_2026`).

<a id="gld"></a>
### GLD — SPDR Gold Shares (lượng vàng nắm giữ; bước 9, DEC-05)

- **Trạng thái:** `BLOCKED`
- **Đọc nguyên văn** 2026-11-13: <https://www.spdrgoldshares.com/terms-and-conditions/>. Lý do chặn:
  1. *"You are permitted to save, display or print out information contained on this Website only for your personal, non-commercial use."* — ngoài ra cấm sao chép, tạo sản phẩm phái sinh... nếu không có phép bằng văn bản của WGTS.
  2. Cấm *"use the whole or part of this Website or its content for any commercial or money-making purpose without having our written consent"* — dùng cho giao dịch kiếm lời có thể bị coi là "money-making".
  3. Cấm *"access or monitor this Website or any of its content other than using the Website's navigational structure"* → **chương trình tự tải file là trái điều khoản**.
- Muốn dùng: xin phép bằng văn bản (`sprdgoldshares@gold.org`) hoặc tìm nguồn chính thức khác cho lượng vàng nắm giữ của quỹ (ví dụ hồ sơ nộp SEC) — **người dùng quyết ở bước 9** (ảnh hưởng DEC-05).

<a id="iau"></a>
### IAU — iShares Gold Trust (lượng vàng nắm giữ; bước 9, DEC-05)

- **Trạng thái:** `BLOCKED`
- Lý do chặn: một trang điều khoản iShares (Mỹ) tìm được **cấm hoạt động nhằm sao chép website hoặc lấy báo cáo, dữ liệu, thông tin** và cấm tạo sản phẩm phái sinh; bản Thụy Sĩ ghi thông tin chỉ dùng cá nhân, phi thương mại. Chưa xác định được trang điều khoản Mỹ hiện hành áp dụng cho trang sản phẩm IAU. Có dấu hiệu cấm tải tự động → **chặn** cho tới khi đọc nguyên văn và thấy được phép.
- Cần đọc: điều khoản ở chân trang <https://www.ishares.com> (bản Mỹ).
- Lần 2 (2026-11-13): trang điều khoản iShares Mỹ chuyển sang `blackrock.com/corporate/compliance/terms-and-conditions` (chưa mở mạng tới đó) → giữ `BLOCKED`. Cùng loại với GLD (quỹ ETF, điều khoản website).

## 4. Nguồn không thuộc khung này

- **Giá MT5 (nến, bid/ask):** lấy từ terminal MT5 của chính người dùng với tài khoản broker của họ (DEC-14), chỉ đọc, dùng nội bộ, không phân phối lại. Quan hệ với broker theo thỏa thuận khách hàng của người dùng — không có mục trong `SOURCE_TERMS` (không qua `SourceRegistry`).
- **Trang lịch tổng hợp (ForexFactory, Investing, FXStreet, Kitco):** không dùng (DEC-01, ING-18) — không có API miễn phí chính thức, điều khoản thường cấm tải tự động.
