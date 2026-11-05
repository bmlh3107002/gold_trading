# 06 — Strategy Engine

## Mục đích

Chuyển `MarketView` hợp lệ thành một `TradeIntent` có thể đánh giá rủi ro. Strategy quyết định ý tưởng giao dịch, không có quyền đặt lệnh trực tiếp.

## Điều kiện vào

- MarketView còn hạn, `confidence` đạt ngưỡng theo regime và không có `riskFlags` cấm.
- Chế độ cho phép tạo lệnh mới; không có duplicate intent cho cùng strategy/symbol/horizon.
- Giá tham chiếu, spread và dữ liệu bắt buộc còn mới.

## Nội dung TradeIntent

`intentId`, `strategyId`, `symbol`, `side`, `entryType`, `entryReference`, `stopLoss`, `takeProfit`, `timeInForce`, `expiry`, `riskBudgetRequested`, `marketViewId`, `policyVersion`, `createdAt`, `reason` và `idempotencyKey`.

Stop-loss và khối lượng mục tiêu không được thiếu. Chiến lược nên chuyển **mức rủi ro mong muốn**, không tự suy ra volume cuối cùng sau khi thay đổi equity.

## Luồng

1. Đọc MarketView, quy tắc chiến lược và giá mới nhất.
2. Tính điều kiện vào/ra theo bias, volatility và cấu trúc giá.
3. Tạo intent có hạn dùng ngắn; ghi audit và gửi Risk Engine.
4. Nhận phê duyệt để chuyển sang execution, hoặc ghi lý do từ chối.

## Kiểm thử

Backtest phải mô phỏng spread, slippage, độ trễ, fill một phần và giới hạn broker. Kiểm thử invariant: intent hết hạn/MarketView hết hạn không tới Execution; một idempotency key chỉ có một luồng giao dịch.
