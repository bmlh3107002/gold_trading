# Hướng dẫn cho Claude

@PROGRESS.md

## ⚠️ NGUYÊN TẮC SỐ 1: THẬN TRỌNG TÀI CHÍNH

Hệ thống này giao dịch bằng **tiền thật của người dùng**. Mọi lỗi logic, dữ liệu sai hay giả định sai đều có thể gây **mất tiền**. Ưu tiên **đúng và an toàn** hơn nhanh hay nhiều tính năng.

- **Không bịa số liệu.** Thiếu dữ liệu thì trả về "không đủ dữ liệu", không đoán, không nội suy âm thầm. Không gọi một con số là "xác suất" hay "độ tin cậy dự báo" khi nó chưa được hiệu chỉnh (calibration) trên dữ liệu thật.
- **Không nhìn trước tương lai.** Chỉ dùng nến đã đóng và dữ liệu có `available_at <= as_of`. Swing hay mẫu hình chỉ được tính sau khi đã xác nhận đủ nến.
- **Mặc định an toàn.** Khi không chắc, chọn hướng chặn giao dịch hoặc hạ độ tin cậy, không chọn hướng cho phép.
- **Dữ liệu mẫu không bao giờ dẫn tới quyết định thật.** Mọi kết quả từ dữ liệu `SAMPLE` phải mang nhãn và bị chặn ở SHADOW/LIVE.
- **Mỗi thay đổi đều phải có test**, gồm cả test cho trường hợp xấu (thiếu nến, spike, feed đóng băng, đổi giờ DST, trùng dữ liệu). Với công thức tài chính, phải có test so với giá trị tham chiếu tính tay hoặc từ nguồn chuẩn.
- **Soát lại sau khi làm:** viết kịch bản kiểm tra riêng nhắm vào chỗ dễ sai, không chỉ dựa vào việc test đang qua. Báo cáo trung thực cả lỗi tìm được và giới hạn còn lại.
- **Không mở rộng phạm vi trong một lần làm.** Chia nhỏ, làm xong và kiểm chứng xong từng phần rồi mới sang phần tiếp theo.
- Mọi thay đổi ảnh hưởng tới quyết định giao dịch (công thức, ngưỡng, chính sách rủi ro) phải được ghi vào `PROGRESS.md` hoặc `docs/thiet-ke/`, kèm lý do.

## Quy ước làm việc

- **Đọc `PROGRESS.md` trước tiên.** Đó là trạng thái hiện tại của dự án. Chỉ đọc thêm code hoặc docs khi cần.
- **`CHECKLIST.md`** là bản đồ việc theo **giai đoạn tuần tự** (GĐ0 → GĐ10) bám mô hình; mỗi việc có mã (`ING-07`, `EVT-02`…), mỗi giai đoạn có bảng case và Gate. **Đi sạch từng giai đoạn:** chỉ làm việc thuộc giai đoạn hiện tại; xong hết việc + case + Gate (và người dùng xác nhận) mới sang giai đoạn sau. Khi làm xong một việc: đổi trạng thái trong `CHECKLIST.md`, ghi nhật ký ở `PROGRESS.md`, nhắc mã việc trong commit.
- Đặc tả chức năng ở `docs/huong-dan-chuc-nang/`. Code phải tuân thủ các bất biến trong đó: point-in-time, idempotent, UTC, LIVE khóa mặc định, Safety có quyền chặn cao nhất.
- Push code lên nhánh **`develop`**. Không tạo PR nếu người dùng chưa yêu cầu.
- **Sau mỗi đợt làm việc:** cập nhật `PROGRESS.md` (bảng trạng thái, kết quả test, nhật ký, việc tiếp theo), rồi commit và push lên `develop`.
- Trước khi push: chạy `uv run pytest` và `uv run ruff check .` trong `backend/` (và `mt5_gateway/` nếu có sửa), cùng `npm run build` trong `frontend/` nếu có sửa.
- Khi đổi schema DB: sửa `backend/src/gold_trading/storage/schema.py` và thêm migration Alembic mới. Không sửa migration đã có.
- Khi đổi contract hoặc API: chạy `uv run python scripts/export_openapi.py` trong `backend/`, rồi `npm run gen:api` trong `frontend/`.
- Trả lời người dùng bằng tiếng Việt.
