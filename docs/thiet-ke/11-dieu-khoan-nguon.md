# Thiết kế — Giấy phép / điều khoản từng nguồn ngoài (GĐ1 bước 7d, ING-32)

> Tạo 2026-11-13. Liên quan: DEC-02 (mỗi nguồn ghi giấy phép), DEC-05 (kiểm điều khoản GLD/IAU trước khi bật), DEC-06 (chỉ nguồn miễn phí), ING-31 (khóa API).
> Code: `backend/src/gold_trading/ingestion/source_terms.py` (`SOURCE_TERMS`). Test `tests/test_source_terms.py` kiểm code và file này **không lệch** trạng thái.

## 1. Quy tắc

- Mỗi **nhà cung cấp** có một mục ở đây, ghi: tình hình hiện biết, bằng chứng (đường dẫn), ngày kiểm, trạng thái.
- **Chỉ bật được nguồn khi trạng thái là `VERIFIED`** (đã đọc **nguyên văn** điều khoản hiện hành và thấy cách dùng dự định được phép). `SourceRegistry` từ chối bật nguồn `NEEDS_REVIEW` / `BLOCKED` / chưa có mục. Nguồn tắt thì khai báo trước được.
- Cách dùng dự định (để đối chiếu với điều khoản): **một người, dùng nội bộ**, chương trình tự tải định kỳ qua API/RSS/file chính thức, lưu trên máy để phân tích giao dịch của chính mình; **không** phân phối lại, **không** bán, **không** hiển thị công khai.
- Đổi trạng thái: sửa mục ở đây (bằng chứng + ngày) **và** `SOURCE_TERMS` trong cùng một commit. Điều khoản các trang đều ghi có thể đổi không báo trước → đọc lại khi bật nguồn và khi nguồn báo `FORBIDDEN` / `AUTH_FAILED` lạ.

## 2. Tình trạng kiểm 2026-11-13 — vì sao chưa nguồn nào `VERIFIED`

Môi trường phát triển **không đọc được nguyên văn** các trang điều khoản (công cụ đọc web không phân giải được tên miền; tải trực tiếp bị chặn bởi quy tắc an toàn của phiên). Các ý dưới đây lấy từ **kết quả tìm kiếm** trỏ tới trang chính thức (trích đoạn), **chưa phải nguyên văn đầy đủ**. Vì vậy tất cả để `NEEDS_REVIEW` (riêng IAU `BLOCKED`). Đây là hướng an toàn: thiếu bằng chứng → không bật.

**Việc phải làm trước khi bật mỗi nguồn (bước 8–10):** đọc nguyên văn trang điều khoản (đường dẫn ở từng mục), ghi lại các điểm: được tải tự động không / cần khóa không / giới hạn tần suất / lưu trữ / ghi nguồn / phân phối lại / ngày hiệu lực → nếu khớp cách dùng dự định thì đổi `VERIFIED`.

Lưu ý chung cho cơ quan liên bang Mỹ: tác phẩm do nhân viên liên bang làm trong công việc thường không có bản quyền ở Mỹ, **nhưng** điều khoản API (khóa, giới hạn, cấm giả danh, dữ liệu bên thứ ba có bản quyền) vẫn áp dụng — không suy ra "được phép" chỉ từ điểm này.

## 3. Từng nhà cung cấp

<a id="fred"></a>
### FRED — Fed St. Louis (lợi suất, lãi suất Fed; bước 9)

- **Trạng thái:** `NEEDS_REVIEW`
- Biết được (trích đoạn trang chính thức): dùng API là chấp nhận điều khoản; **bắt buộc khóa đã đăng ký**; điều khoản có thể đổi không báo trước; vi phạm thì bị tắt quyền; không được ngụ ý Fed St. Louis bảo trợ; **phải ghi nguồn** khi dùng nội dung FRED; cấm thu thập (scraping) ngoài cách API cho phép; một số series thuộc **bên thứ ba** có điều khoản riêng. Có tin điều khoản mới thêm cấm tải hàng loạt (chưa kiểm được nguyên văn).
- Cần đọc: <https://fred.stlouisfed.org/docs/api/terms_of_use.html>, <https://fred.stlouisfed.org/legal/>. Khi bật từng series: kiểm series đó có phải dữ liệu bên thứ ba không.

<a id="bls"></a>
### BLS — Cục Thống kê Lao động (CPI, NFP, PPI; lịch + actual; RSS; bước 8, 10)

- **Trạng thái:** `NEEDS_REVIEW`
- Biết được: API bản 2 **cần khóa**; giới hạn **500 truy vấn/ngày** (có khóa), **50 yêu cầu / 10 giây**; khóa phải **gia hạn ít nhất mỗi năm** (→ khóa hết hạn sẽ ra `AUTH_FAILED`/`KEY_*`, nguồn MISSING — ING-30). Chữ, bảng, biểu đồ của BLS là **public domain**, dùng lại được nếu **ghi nguồn**; ảnh và logo không được dùng; không được sửa nội dung mà vẫn ghi nguồn BLS.
- Cần đọc: <https://www.bls.gov/developers/termsOfService.htm>, <https://www.bls.gov/developers/api_faqs.htm>, <https://www.bls.gov/bls/linksite.htm>.

<a id="bea"></a>
### BEA — Cục Phân tích Kinh tế (GDP, PCE; bước 8)

- **Trạng thái:** `NEEDS_REVIEW`
- Biết được: đăng ký khóa (`UserID`) cần tên + email và **đồng ý điều khoản**. Giới hạn 100 yêu cầu, 100 MB, 30 lỗi mỗi phút — **chỉ từ nguồn thứ cấp**, phải kiểm lại.
- Cần đọc: <https://apps.bea.gov/API/_pdf/bea_api_tos.pdf>, <https://apps.bea.gov/api/bea_web_service_api_user_guide.htm>.

<a id="census"></a>
### Census — Cục Điều tra Dân số (doanh số bán lẻ; bước 8, bổ sung DEC-01)

- **Trạng thái:** `NEEDS_REVIEW`
- Biết được: hướng dẫn chính thức ghi **mọi truy vấn phải có khóa** (tham số `key`; theo một bài thứ cấp, bắt buộc từ 12/05/2026) → **cần thêm biến khóa** khi làm bước 8 (ING-31). API cung cấp "nguyên trạng"; Cục có thể giám sát việc dùng; không được ngụ ý Cục bảo trợ, không trình bày số đã sửa như số của Cục. Không thấy con số giới hạn chính thức.
- Cần đọc: <https://www.census.gov/data/developers/terms-of-service.html>, <https://www.census.gov/data/developers/guidance/api-user-guide.API_Key.html>.

<a id="dol"></a>
### DOL — Bộ Lao động (trợ cấp thất nghiệp hằng tuần; bước 8, bổ sung DEC-01)

- **Trạng thái:** `NEEDS_REVIEW`
- Biết được (thông cáo DOL + bài báo): cổng dữ liệu `data.dol.gov`, API miễn phí, **đăng ký qua Login.gov để nhận khóa**, cần khóa cho mọi yêu cầu. Chưa thấy điều khoản sử dụng, giới hạn. Phải kiểm thêm: số liệu tuần có sẵn qua API ngay giờ công bố không (một bộ dữ liệu ghi trễ ít nhất 30 phút) — nếu trễ thì nguồn actual lúc công bố phải là thông cáo trên `dol.gov`.
- Cần đọc: <https://data.dol.gov>, <https://www.dol.gov/newsroom/releases/oasam/oasam20260218>.

<a id="fed"></a>
### Fed — Hội đồng Thống đốc (FOMC: lịch, tuyên bố; RSS; bước 8, 10)

- **Trạng thái:** `NEEDS_REVIEW`
- Biết được: trang miễn trừ trách nhiệm ghi một số nội dung trên trang **có thể có bản quyền** với hạn chế dùng lại, xin phép từ nguồn gốc chứ không phải từ Hội đồng. **Chưa tìm thấy** điều khoản riêng cho RSS.
- Cần đọc: <https://www.federalreserve.gov/disclaimer.htm>, <https://www.federalreserve.gov/feeds/>, trang chính sách website.

<a id="treasury"></a>
### Bộ Tài chính Mỹ (RSS thông cáo; bước 10)

- **Trạng thái:** `NEEDS_REVIEW`
- Biết được: có RSS thông cáo báo chí trên `home.treasury.gov`. **Chưa tìm thấy** trang chính sách/bản quyền hiện hành (chỉ có bản lưu cũ).
- Cần đọc: trang "Site Policies and Notices" trên <https://home.treasury.gov>.

<a id="cftc"></a>
### CFTC — báo cáo COT (vị thế vàng; bước 9)

- **Trạng thái:** `NEEDS_REVIEW`
- Biết được: COT hiện tại + lịch sử có trên `cftc.gov` và API công khai `publicreporting.cftc.gov`; kế hoạch dữ liệu mở của CFTC hướng tới giấy phép mở; danh mục data.gov ghi dữ liệu công khai. **Chưa thấy** câu chữ giấy phép rõ ràng của chính CFTC.
- Cần đọc: <https://www.cftc.gov/MarketReports/CommitmentsOfTraders/index.htm> (cả giờ công bố — `available_at` của ING-12), điều khoản trang web CFTC.

<a id="gld"></a>
### GLD — SPDR Gold Shares (lượng vàng nắm giữ; bước 9, DEC-05)

- **Trạng thái:** `NEEDS_REVIEW`
- Biết được: điều khoản trang cho **lưu, hiển thị, in thông tin chỉ để dùng cá nhân, phi thương mại**; cấm sao chép, phân phối, tạo sản phẩm phái sinh ngoài phạm vi được phép; dùng thương mại cần đồng ý bằng văn bản của WGTS; dữ liệu thị trường của ICE và giá LBMA có **điều khoản riêng**; file dữ liệu lịch sử "chỉ để tham khảo". **Chưa rõ** có cho chương trình tự tải file không.
- Cần đọc: <https://www.spdrgoldshares.com/usa/terms>, <https://www.spdrgoldshares.com/usa/historical-data>. Chỉ dùng cột lượng vàng nắm giữ của quỹ (không dùng giá ICE/LBMA).

<a id="iau"></a>
### IAU — iShares Gold Trust (lượng vàng nắm giữ; bước 9, DEC-05)

- **Trạng thái:** `BLOCKED`
- Lý do chặn: một trang điều khoản iShares (Mỹ) tìm được **cấm hoạt động nhằm sao chép website hoặc lấy báo cáo, dữ liệu, thông tin** và cấm tạo sản phẩm phái sinh; bản Thụy Sĩ ghi thông tin chỉ dùng cá nhân, phi thương mại. Chưa xác định được trang điều khoản Mỹ hiện hành áp dụng cho trang sản phẩm IAU. Có dấu hiệu cấm tải tự động → **chặn** cho tới khi đọc nguyên văn và thấy được phép.
- Cần đọc: điều khoản ở chân trang <https://www.ishares.com> (bản Mỹ).

## 4. Nguồn không thuộc khung này

- **Giá MT5 (nến, bid/ask):** lấy từ terminal MT5 của chính người dùng với tài khoản broker của họ (DEC-14), chỉ đọc, dùng nội bộ, không phân phối lại. Quan hệ với broker theo thỏa thuận khách hàng của người dùng — không có mục trong `SOURCE_TERMS` (không qua `SourceRegistry`).
- **Trang lịch tổng hợp (ForexFactory, Investing, FXStreet, Kitco):** không dùng (DEC-01, ING-18) — không có API miễn phí chính thức, điều khoản thường cấm tải tự động.
