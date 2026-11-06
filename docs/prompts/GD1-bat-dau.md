# Prompt: Bắt đầu GĐ1 — Dữ liệu vào

> Dán phần dưới đường kẻ vào một phiên Claude Code mới trên repo `bmlh3107002/gold_trading`, nhánh `develop`.

---

Đọc `CLAUDE.md` và `PROGRESS.md` (đã nạp sẵn), rồi mở **đúng một** file giai đoạn: `docs/giai-doan/GD1-du-lieu-vao.md` (đọc mục "Chuyển từ GĐ0" trước). GĐ0 đã đóng (2026-11-06). Không đọc file các giai đoạn khác, trừ tra một mã việc cụ thể bằng `grep -rn "<mã>" docs/giai-doan/` (ví dụ MT-05, MT-12..15 ở `docs/giai-doan/MT-da-nguoi-dung.md`).

Người dùng không rành kỹ thuật: giải thích đơn giản bằng tiếng Việt, **mỗi lần chỉ hỏi một câu / đưa một bước**, đợi trả lời rồi mới sang câu tiếp. Lệnh PowerShell để trong một khối riêng, chỉ dùng ký tự ASCII trong lệnh. Không bao giờ yêu cầu dán mật khẩu, token, khóa API hay nội dung `.env` vào chat.

## Việc 1: chốt quyết định (chưa code nguồn mới trước khi chốt)

Hỏi lần lượt, mỗi câu kèm 2–3 lựa chọn đơn giản + khuyến nghị, nói rõ cái nào miễn phí / trả phí và giới hạn (độ trễ, giấy phép):

1. **DEC-06** ngân sách (hỏi trước vì ảnh hưởng mọi câu sau).
2. **DEC-01** lịch kinh tế + số dự báo.
3. **DEC-02** tin tức.
4. **DEC-03** DXY.
5. **DEC-04** kỳ vọng lãi suất Fed.
6. **DEC-05** NHTW mua vàng / dòng tiền ETF.
7. **DEC-07** khóa API miễn phí (người dùng tự đăng ký, khóa để trong `.env`).
8. **DEC-14** (đa tài khoản): các tài khoản dùng broker khác nhau thì mỗi tài khoản phân tích theo giá broker của mình hay dùng chung một nguồn giá.

Ghi từng câu trả lời vào bảng quyết định trong file GĐ1 (cột TT `[x]` + ngày + lựa chọn), commit, push `develop`.

## Việc 2: lập thứ tự làm

Sau khi chốt, đề xuất thứ tự làm từng phần nhỏ (1A → 1G), mỗi phần xong + test + kiểm chứng rồi mới sang phần sau. Gợi ý bắt đầu từ 1A (giá MT5: H1/H4/D1, tick/spread, 1A-C21 nến cuối tuần) vì không phụ thuộc quyết định. Hỏi người dùng đồng ý thứ tự trước khi code.

## Nhắc lại bất biến

Point-in-time (`available_at <= as_of`), UTC, chỉ nến đã đóng, dữ liệu `SAMPLE` không dẫn tới SHADOW/LIVE, thiếu dữ liệu → "không đủ dữ liệu", MT5 Gateway **chỉ đọc**, mỗi thay đổi có test (gồm trường hợp xấu), không bịa số liệu, không mở rộng phạm vi.
