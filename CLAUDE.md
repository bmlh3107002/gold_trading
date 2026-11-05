# Hướng dẫn cho Claude

@PROGRESS.md

- **Đọc `PROGRESS.md` trước tiên.** Đó là trạng thái hiện tại của dự án. Chỉ đọc thêm code hoặc docs khi cần.
- Đặc tả chức năng ở `docs/huong-dan-chuc-nang/`. Code phải tuân thủ các bất biến trong đó: point-in-time, idempotent, UTC, LIVE khóa mặc định, Safety có quyền chặn cao nhất.
- Push code lên nhánh **`develop`**. Không tạo PR nếu người dùng chưa yêu cầu.
- **Sau mỗi đợt làm việc:** cập nhật `PROGRESS.md` (bảng trạng thái, kết quả test, nhật ký, việc tiếp theo), rồi commit và push lên `develop`.
- Trước khi push: chạy `uv run pytest` và `uv run ruff check .` trong `backend/` (và `mt5_gateway/` nếu có sửa), cùng `npm run build` trong `frontend/` nếu có sửa.
- Khi đổi schema DB: sửa `backend/src/gold_trading/storage/schema.py` và thêm migration Alembic mới. Không sửa migration đã có.
- Khi đổi contract hoặc API: chạy `uv run python scripts/export_openapi.py` trong `backend/`, rồi `npm run gen:api` trong `frontend/`.
- Trả lời người dùng bằng tiếng Việt.
