Dữ liệu test cho bộ nạp Census (GĐ1 bước 8d). Nguồn: U.S. Census Bureau, https://www.census.gov —
"This product uses the Census Bureau Data API but is not endorsed or certified by the Census Bureau."

- `calendar-listview-2026.html`, `calendar-listview-2027.html`: lịch công bố chỉ số kinh tế (dạng danh
  sách), tải nguyên văn 2026-11-13 từ https://www.census.gov/economic-indicators/calendar-listview-2026.html
  và https://www.census.gov/economic-indicators/calendar-listview.html (trang mặc định = năm 2027).
- `retail-release-schedule.html`: lịch riêng của khảo sát bán lẻ, tải nguyên văn 2026-11-13 từ
  https://www.census.gov/retail/release_schedule.html
- `marts-2025.json`, `marts-2026.json`: **dựng lại** (chưa có khóa API lúc làm) theo dạng chuẩn của
  Census Data API (mảng 2 chiều, dòng đầu là tên cột; biến theo
  https://api.census.gov/data/timeseries/eits/marts/variables.json). **Số liệu là số thật** (đã điều chỉnh
  mùa vụ, triệu USD và %) đọc 2026-11-13 từ công cụ Time Series của Census
  (https://www.census.gov/econ/currentdata/dbsearch?programCode=MARTS..., mã 44X72 / 44Y72 / 44W72,
  SM / MPCSM), khớp file https://www.census.gov/retail/marts/www/marts_current.xlsx. Thêm vài dòng giả
  có chủ ý để test bộ lọc: dòng sai số (`error_data=yes`), dòng không điều chỉnh mùa vụ, ngành 441.

Không sửa các file HTML tải nguyên văn: test cần đúng nội dung thật.
