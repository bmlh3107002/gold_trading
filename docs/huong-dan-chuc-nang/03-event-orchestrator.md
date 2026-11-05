# 03 — Event Orchestrator

## Mục đích

Biến dữ liệu mới thành các job phân tích đúng loại, đúng độ ưu tiên và không chạy trùng. Orchestrator điều phối; nó không đưa ra nhận định thị trường.

## Sự kiện và hành động

| Sự kiện | Job chính |
| --- | --- |
| Nến M15 đóng | Technical → Regime → Fusion |
| CPI/NFP/FOMC được công bố | Fast lane, Event/Calendar, News, cập nhật `riskFlags` |
| DXY/yield cập nhật | Macro analyst |
| COT/ETF flow công bố | Positioning analyst |
| Output hết hạn | Invalidate MarketView, yêu cầu tái tính |

## Quy tắc vận hành

- Debounce dữ liệu dồn dập theo loại/symbol/time bucket; không bỏ qua sự kiện công bố quan trọng.
- Dùng `jobKey = eventType + subject + eventVersion + analyzerVersion`; cùng khóa chỉ xử lý một lần có hiệu lực.
- Fast lane ưu tiên cờ an toàn và cảnh báo; không gọi LLM nặng trong đường giây.
- Job có deadline, retry giới hạn, exponential backoff và dead-letter queue. Không retry vô hạn.
- Ghi `correlationId`, nguyên nhân kích hoạt, phiên bản input/output và trạng thái job.

## Đầu ra

Job thành công xuất analyst output hoặc yêu cầu invalidate. Job thất bại phải tạo tín hiệu quan sát được để Quality Gate đánh giá độ thiếu dữ liệu, không được âm thầm dùng output cũ quá hạn.

## Kiểm thử

Replay cùng event log phải có thứ tự nhân quả ổn định; gửi lại cùng event không nhân đôi analyst output; một tin nóng phải cập nhật `riskFlags` trong ngân sách độ trễ đã đặt.
