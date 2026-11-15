# Prompt: Soát lại độc lập GĐ0 → GĐ4

> Dán phần dưới đường kẻ vào một phiên Claude Code mới trên repo `bmlh3107002/gold_trading`, nhánh `develop`. Tạo 2026-11-15.

---

Đọc `CLAUDE.md` và `PROGRESS.md` (đã nạp sẵn). Đây là phiên **soát lại độc lập** toàn bộ phần đã làm của **GĐ0, GĐ1, GĐ2, GĐ3, GĐ4**, bằng con mắt mới, như một người kiểm toán chưa từng viết dòng code nào ở đây. Hệ thống sẽ giao dịch **tiền thật** về sau: mục tiêu là tìm lỗi có thể gây **mất tiền, cho phép lệnh khi lẽ ra phải chặn, nhìn trước tương lai, bịa số, hoặc báo cáo sai sự thật** — trước khi sang GĐ5.

**Ngoại lệ có chủ ý cho quy ước "chỉ đọc một file giai đoạn":** phiên này được đọc cả 5 file `docs/giai-doan/GD0..GD4-*.md`, `docs/ke-hoach/GD1..GD4-ke-hoach.md`, `docs/ke-hoach/lich-kiem-tren-may.md`, `docs/thiet-ke/`, `docs/ghi-chu-ky-thuat.md`, đặc tả `docs/huong-dan-chuc-nang/` 01–05 + 07–08 + 12. Đọc **lần lượt từng giai đoạn** (GĐ0 → GĐ4), không nạp tất cả cùng lúc. Không đọc GĐ5+ trừ khi tra mã việc (`grep -rn "<mã>" docs/giai-doan/`). Được phép dùng agent con (Explore) để rà song song khi một giai đoạn quá lớn.

## Pha 1 — Chỉ soát, KHÔNG sửa code

Với từng giai đoạn:
1. Đối chiếu **tài liệu ↔ code ↔ test**: mục nào ghi `[x]` / "đã soát" / "có test" mà thực tế không đúng; test nào chỉ đạt vì dữ liệu test tự dựng không giống dữ liệu thật (bài học GĐ4 5b: test tự dựng `output_id` kiểu mới nên không bắt được Technical dùng id kiểu cũ → hệ thống không bao giờ ra MarketView).
2. Chạy `uv run pytest -q` + `uv run ruff check .` (backend, mt5_gateway), `npm run check && npm run build` (frontend).
3. **Viết kịch bản soát riêng** (trong scratchpad, không đưa vào repo) nhắm vào chỗ dễ sai: chạy thành phần thật trên dữ liệu thật / mẫu, so với cách tính độc lập (pandas, thư viện tham chiếu, bảng tra viết lại), kiểm tính đối xứng, ma trận trường hợp xấu. Có Postgres 16 trên máy thử (`pg_ctlcluster 16 main start`; container có thể khởi động lại làm Postgres tắt — bật lại; đặt mật khẩu bằng `su postgres -c "psql -c \"ALTER USER postgres PASSWORD '...'\""`). TimescaleDB thật chỉ có ở CI (job `docker`).

**Danh sách điểm cần soát (không giới hạn ở đây):**
- **Point-in-time / nhìn trước tương lai:** `known_at`, `computed_at` vs `as_of`, nến chưa đóng, bản sửa số liệu (revision) không viết lại quá khứ, bộ quét orchestrator (mốc chồng lấn 15 phút), các analyst đọc dữ liệu "đã biết tại `as_of`".
- **Safety + làn nhanh (GĐ0, GĐ2):** đọc lỗi → phải chặn; cửa sổ lịch quanh công bố; DST Mỹ / Việt Nam; ngày lễ, đóng sớm; spread chỉ với MT5; nhịp tim / độ trễ; Safety luôn có quyền chặn cao nhất; LIVE khóa mặc định, người duyệt ≠ người yêu cầu.
- **Dữ liệu (GĐ1):** cách ly nến lỗi, trùng dữ liệu, feed đóng băng, spike, nhiều broker không trộn giá (MT-05 / DEC-14), quy đổi giờ server MT5 → UTC, nguồn ngoài (Fed, BLS, BEA, DOL, Census, H.15, COT, RSS) — số dạng chuỗi thập phân, "(NA)" không thành 0, điều khoản nguồn, khóa API không bao giờ lọt vào log / DB / phản hồi.
- **Orchestrator (GĐ2):** thứ tự nhân quả, debounce, retry / dead-letter, khôi phục sau khởi động lại. **Đầu mối đã biết:** job của cùng một sự kiện chạy theo **thứ tự chữ cái** loại job (`REGIME` trước `TECHNICAL`) — kiểm có analyst nào phụ thuộc kết quả của analyst khác trong cùng nhịp mà bị dùng bản cũ không.
- **Analyst (GĐ3):** công thức so giá trị tham chiếu; ngưỡng ghi rõ "chưa hiệu chỉnh"; `confidence` chỉ là chất lượng dữ liệu, **không** được gọi / hiển thị là xác suất; thiếu dữ liệu → "không đủ dữ liệu" chứ không đoán; News: chống prompt injection, ngân sách, mặc định tắt.
- **GĐ4:** Snapshot / Quality Gate / Fusion / MarketView / `FusionRunner` (bộ đệm `_last` có thể bỏ sót vô hiệu không?), vô hiệu khi Gate từ chối, `output_id` kiểu cũ của Technical ở **mọi** chỗ khác còn kiểm phạm vi qua id (vd. `_check_scope` trong `storage/analyst_outputs.py`), API theo tài khoản, thẻ giao diện khi mất kết nối / quá hạn, Risk chặn SHADOW / LIVE. Hệ số 0,9 / 0,5 / trần 30 phút là giá trị chưa hiệu chỉnh — chỉ báo nếu có lý do số học / an toàn.
- **Hợp đồng dữ liệu:** `model_copy(update=...)` của Pydantic không kiểm tra lại (đã vá riêng `MarketView`; các hợp đồng khác như `TradeIntent` chưa — có thẻ việc đề xuất).
- **Bảo mật:** phân quyền theo tài khoản (USER khác → 404), ADMIN không giao dịch, token Gateway, che bí mật trong log, Host / CORS, BFF Keycloak.
- **DB:** migration lên / xuống, `alembic check`, trigger chỉ-thêm trên mọi bảng nhật ký, không sửa migration cũ, không gì phá TimescaleDB (bài học migration 0009).
- **Tài liệu lệch code:** trạng thái trong `docs/giai-doan/`, `PROGRESS.md`, `docs/ghi-chu-ky-thuat.md`, hướng dẫn kiểm trên máy (lệnh PowerShell đúng cú pháp, không `\"` / `$`).

**Kết quả Pha 1:** viết `docs/soat-lai/bao-cao-GD0-GD4.md` — bảng phát hiện: mã (SL-01…), **mức độ** (NGHIÊM TRỌNG = có thể mất tiền / cho lệnh khi phải chặn / nhìn trước / bịa số; CAO; TRUNG BÌNH; THẤP = tài liệu, vặt), giai đoạn + mã việc, mô tả **dễ hiểu cho người chưa từng trade**, bằng chứng (`file:dòng`, lệnh / kịch bản tái hiện, kết quả), đề xuất sửa, trạng thái. Ghi cả **những gì đã soát mà không thấy lỗi** (để biết phạm vi đã phủ) và giới hạn của lần soát. Commit + push `develop` (chỉ tài liệu) → kiểm CI. Rồi tóm tắt cho người dùng bằng tiếng Việt đơn giản, xếp theo mức độ.

## Pha 2 — Sửa (chỉ khi người dùng đồng ý)

- Hỏi người dùng **từng câu một**: sửa phát hiện nào trước (kèm 2–3 lựa chọn + khuyến nghị). Phát hiện mâu thuẫn với quyết định đã chốt (DEC-…) → báo và hỏi, **không tự đổi**.
- Mỗi lần sửa: một phát hiện / một commit nhỏ; test gồm trường hợp xấu + test hồi quy tái hiện đúng lỗi; soát lại bằng kịch bản riêng; ghi nhật ký vào **file giai đoạn của mã việc đó** + cập nhật trạng thái trong báo cáo soát; nhắc mã việc + mã SL-xx trong commit; `uv run pytest` / `ruff` / `npm run check && build` → push `develop` → **kiểm CI GitHub Actions** (`actions_list` / `get_job_logs`); CI đỏ → sửa trước khi làm tiếp.
- **Không mở rộng phạm vi**: không thêm tính năng mới, không làm việc của GĐ5+.

## Lưu ý vận hành

- Máy người dùng `deploy/docker-compose.yml` **build thẳng từ `develop`**. Lịch kiểm trên máy: `docs/ke-hoach/lich-kiem-tren-may.md` (dựng lại thứ Hai 16/11 trước 22:00; đêm 16→17/11 là mục 6a — backend tắt; từ 17/11 đếm 5 ngày chạy liên tục). **Trước khi push code (không phải tài liệu) lên `develop`, hỏi người dùng đã dựng lại chưa / sắp dựng lại lúc nào**, để không đưa thay đổi chưa chắc chắn lên máy giữa đợt kiểm. Không thay đổi gì buộc người dùng dựng lại thêm lần, trừ lỗi NGHIÊM TRỌNG (khi đó nói rõ cần làm gì trên máy Windows, từng lệnh một).
- Không đổi trạng thái Gate, không tick việc nếu chưa có bằng chứng.
- Người dùng không rành kỹ thuật: tiếng Việt đơn giản, mỗi lần hỏi một câu. Không bao giờ yêu cầu dán mật khẩu / token / khóa API vào chat. Không tạo PR.
