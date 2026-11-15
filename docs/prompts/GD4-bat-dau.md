# Prompt: Bắt đầu GĐ4 — Snapshot → Quality Gate → Fusion → MarketView

> Dán phần dưới đường kẻ vào một phiên Claude Code mới trên repo `bmlh3107002/gold_trading`, nhánh `develop`.

---

Đọc `CLAUDE.md` và `PROGRESS.md` (đã nạp sẵn), rồi mở **đúng một** file giai đoạn: `docs/giai-doan/GD4-snapshot-fusion-marketview.md` (đọc DEC-23 trước). Đặc tả: `docs/huong-dan-chuc-nang/05-snapshot-fusion-marketview.md`. Không đọc file các giai đoạn khác, trừ tra mã việc cụ thể bằng `grep -rn "<mã>" docs/giai-doan/`.

Bối cảnh: GĐ4 làm **song song** (DEC-23) — GĐ1, GĐ2, GĐ3 đã xong code, chỉ còn kiểm trên máy (lịch: `docs/ke-hoach/lich-kiem-tren-may.md`, ưu tiên hơn GĐ4). Không đóng GĐ4 trước GĐ1 → GĐ2 → GĐ3. GĐ3 đã có 6 analyst (Technical, Lịch sự kiện, Regime, Macro, Positioning/COT, News) — đầu vào của GĐ4; tra hợp đồng / phạm vi lưu ở `docs/thiet-ke/27-khung-analyst.md` và bảng thành phần trong `docs/ghi-chu-ky-thuat.md`. Đã có sẵn một phần: `intelligence/snapshot_builder.py`, `intelligence/quality_gate.py`; orchestrator đã định tuyến `INVALIDATE_MARKETVIEW` (chưa có bộ xử lý).

**Việc của phiên này: chỉ làm kế hoạch** — viết `docs/ke-hoach/GD4-ke-hoach.md` theo mẫu `docs/ke-hoach/GD3-ke-hoach.md` (ý tưởng chính, các bước theo thứ tự, mỗi bước: thiết kế → code + test (gồm trường hợp xấu) + soát lại kịch bản riêng → tick → commit → push develop → kiểm CI; mục kiểm trên máy; Gate; prompt cho phiên sau). Thêm dòng GĐ4 vào `docs/ke-hoach/README.md`. Liệt kê các **quyết định cần người dùng chốt** (ví dụ: analyst nào bắt buộc / tùy chọn cho Quality Gate, cách gộp khi chưa có trọng số hiệu chỉnh — REG-02 đang để trung tính, Fusion có được ra "xu hướng" hay chỉ mô tả khi chưa backtest) và hỏi **từng câu một**, kèm 2–3 lựa chọn + khuyến nghị. Chưa code trước khi người dùng duyệt kế hoạch.

Nguyên tắc số 1 trong `CLAUDE.md` (thận trọng tài chính): không bịa số, không gọi là "xác suất" khi chưa hiệu chỉnh, không nhìn trước tương lai, mặc định an toàn. Người dùng không rành kỹ thuật: tiếng Việt đơn giản, mỗi lần hỏi một câu. Không bao giờ yêu cầu dán mật khẩu / token / khóa API vào chat. Xong thì ghi nhật ký vào file GĐ4, cập nhật `PROGRESS.md` ngắn gọn, commit + push `develop`, kiểm CI.
