Dữ liệu test cho bộ nạp BEA (GĐ1 bước 8c). Nguồn: U.S. Bureau of Economic Analysis (BEA),
https://www.bea.gov — BEA không bảo trợ hay xác nhận hệ thống này.

- `schedule-2026-11-13.ics`: file lịch công bố chính thức, tải nguyên văn ngày 2026-11-13 từ
  https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics
- `release_dates-2026-11-13.json`: file lịch máy đọc được mà trang lịch BEA dẫn tới, tải nguyên văn
  ngày 2026-11-13 từ https://apps.bea.gov/API/signup/release_dates.json
- `nipa-*.json`: **dựng lại** (không phải phản hồi tải về — chưa có khóa API lúc làm). Cấu trúc theo
  ví dụ trong "BEA API For Data Retrieval User Guide" (bản 20/04/2026, phụ lục B — NIPA); **số liệu là
  số thật** lấy từ file công khai https://apps.bea.gov/national/Release/TXT/NipaDataQ.txt và
  NipaDataM.txt tải 2026-11-13 (sau lần công bố 29/10/2026). Mục USERID là chuỗi mẫu của hướng dẫn,
  không phải khóa. Khi có khóa thật: so lại với phản hồi thật (kịch bản soát lại bước 8c).

Không sửa các file tải nguyên văn: test cần đúng nội dung thật.
