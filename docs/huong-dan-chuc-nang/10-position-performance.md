# 10 — Position Manager và Performance

## Position Manager

Theo dõi vị thế đã mở và tạo **đề xuất** quản lý: dời SL về hòa vốn (BE), trailing stop, time-stop hoặc chốt/giảm vị thế. Đầu vào là trạng thái MT5 đã đối soát, TradeIntent gốc, risk policy, giá mới nhất và Safety state.

### Quy tắc

- Không nới rộng rủi ro vượt policy; mọi sửa SL/TP phải qua Risk/Execution và được Safety kiểm tra.
- Time-stop dùng thời điểm khớp thực tế, không dùng thời điểm tạo intent.
- Không gửi update khi giá không đổi đáng kể, khi command trước chưa xác nhận hoặc trong cửa sổ `PAUSED` trừ thao tác bảo vệ được phép.
- Đóng do time-stop hay Guardian phải tạo nguyên nhân chuẩn để đánh giá hậu kỳ.

## Performance

Tổng hợp từ ledger đã đối soát: PnL thực hiện/chưa thực hiện, drawdown, hit rate, expectancy, MAE/MFE, chi phí, slippage, fill quality và hiệu năng theo strategy/regime/thời điểm. Đánh giá phải tách paper, shadow và live.

Performance chỉ là phản hồi offline/giám sát; nó không được tự động thay đổi mô hình hay thông số LIVE. Thay đổi phải đi qua quy trình Training và phê duyệt.

## Kiểm thử

Đảm bảo PnL khớp deal MT5 sau phí/swap/commission, vị thế đóng không còn nhận trailing command, và restart không lặp command quản lý.
