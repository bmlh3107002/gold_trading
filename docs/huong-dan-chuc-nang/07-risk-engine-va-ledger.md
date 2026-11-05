# 07 — Risk Engine và Risk Ledger

## Risk Engine

Đây là cổng phê duyệt vốn. Nó tái định giá `TradeIntent` bằng danh mục và trạng thái an toàn hiện thời trước mỗi lệnh mới hoặc thay đổi bảo vệ.

### Kiểm tra tối thiểu

- Hạn mức rủi ro mỗi lệnh, mỗi symbol, danh mục, ngày và drawdown.
- Khoảng cách SL, leverage/margin, volume step/min/max, spread/slippage và exposure ròng/gộp.
- Correlation/concentration, cửa sổ tin nóng, MarketView/intent stale, trạng thái Safety và equity hiện tại.
- Vị thế/lệnh tồn tại và reservation đang mở để tránh over-allocation do đồng thời.

### Kết quả

`APPROVED` (volume, giới hạn giá, reservation), `REJECTED` (reason codes), hoặc `REDUCED` (khối lượng/điều kiện đã thu nhỏ). Quyết định có TTL và phải gắn policy/config version.

## Risk Ledger

Ledger là sổ cái append-only cho `PortfolioState`, `RiskReservation` và kết quả đối soát với MT5. Khi duyệt, reserve ngân sách; khi lệnh bị từ chối/hết hạn, nhả reservation; khi fill/đóng lệnh, cập nhật exposure và PnL.

Không xóa hay sửa trực tiếp bản ghi đã ghi. Các điều chỉnh dùng event bù trừ có lý do, actor và liên kết bản ghi gốc.

## Đối soát

Định kỳ và theo event, so sánh order/deal/position/equity/margin MT5 với ledger. Sai lệch nghiêm trọng phải chuyển Safety sang hạn chế/halt theo chính sách, khóa order mới và tạo incident.

## Kiểm thử cạnh tranh

Gửi đồng thời hai intent cùng tiêu ngân sách phải chỉ cho phép mức tổng trong hạn mức. Crash giữa reserve và gửi lệnh phải recover được qua idempotency key + đối soát broker.
