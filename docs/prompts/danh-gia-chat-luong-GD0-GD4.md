# Prompt: Đánh giá chất lượng GĐ0 → GĐ4 + khuyến nghị để đạt kết quả cao nhất

> Dán phần dưới đường kẻ vào một phiên Claude Code mới trên repo `bmlh3107002/gold_trading`, nhánh `develop`. Tạo 2026-11-15.

---

Đọc `CLAUDE.md` và `PROGRESS.md` (đã nạp sẵn). Phiên này là **đánh giá chất lượng độc lập** toàn bộ phần đã làm của **GĐ0, GĐ1, GĐ2, GĐ3, GĐ4**, như một chuyên gia kiểm định chưa từng viết dòng code nào ở đây, rồi **khuyến nghị** những việc cần làm để hệ thống đạt kết quả cao nhất về sau (GĐ5 → GĐ10: kế hoạch giao dịch, backtest, AI, paper, demo, live). Hệ thống sẽ giao dịch **tiền thật**: "kết quả cao nhất" nghĩa là **bảo toàn vốn trước**, rồi mới tới khả năng kiếm lợi thế thật — được chứng minh bằng dữ liệu, không phải bằng lời hứa.

**Trung thực tuyệt đối:** không hứa lợi nhuận, không nói một thay đổi "chắc chắn tăng hiệu quả" khi chưa có backtest. Mỗi khuyến nghị nói rõ: lợi ích **kỳ vọng** + lý do / bằng chứng (nguồn chuẩn, số liệu, thử nghiệm), cách đo ở giai đoạn sau, rủi ro, công sức.

**Ngoại lệ có chủ ý cho quy ước "chỉ đọc một file giai đoạn":** phiên này được đọc `docs/giai-doan/GD0..GD4-*.md`, `docs/ke-hoach/GD1..GD4-ke-hoach.md`, `docs/ke-hoach/lich-kiem-tren-may.md`, `docs/thiet-ke/`, `docs/ghi-chu-ky-thuat.md`, đặc tả `docs/huong-dan-chuc-nang/` (toàn bộ 01–12, để biết các giai đoạn sau cần gì từ GĐ0–4), và **chỉ mục** các việc của GĐ5–GĐ10 (bảng mã việc, không cần nhật ký). Đọc **lần lượt từng giai đoạn**, không nạp tất cả cùng lúc. Được phép dùng agent con (Explore) để rà song song, và tra cứu web cho phương pháp / nguồn chuẩn (ghi nguồn).

## Pha 1 — Đánh giá + khuyến nghị, KHÔNG sửa code

### A. Chấm điểm từng giai đoạn (1–5, mỗi điểm phải có bằng chứng `file:dòng` / lệnh / kết quả chạy)

| Tiêu chí | Câu hỏi |
| --- | --- |
| 1. Đúng đắn | Code làm đúng như tài liệu / đặc tả? Test có thật sự kiểm điều nó tuyên bố, hay chỉ đạt vì dữ liệu test tự dựng không giống dữ liệu thật? (Bài học GĐ4 5b: test tự dựng `output_id` kiểu mới nên không bắt được Technical dùng id kiểu cũ → hệ thống không bao giờ ra MarketView.) |
| 2. An toàn tài chính | Mặc định an toàn, Safety có quyền cao nhất, LIVE khóa, không nhìn trước tương lai (`known_at` / `computed_at` / `as_of`, nến chưa đóng, revision), không bịa số, không gọi là "xác suất" khi chưa hiệu chỉnh, SAMPLE không dẫn tới SHADOW / LIVE |
| 3. Chất lượng phương pháp | Với **trading vàng**, cách làm có hợp lý, theo chuẩn ngành không? Thiếu yếu tố quan trọng nào (vd. phiên giao dịch Á / Âu / Mỹ, mức độ bất ngờ của tin — cần số dự báo (DEC-01), lợi suất thực, USD, ETF, ngân hàng trung ương, biến động theo giờ, thanh khoản / spread lễ tết)? Ngưỡng / hệ số chưa hiệu chỉnh có ghi rõ và có kế hoạch hiệu chỉnh không? |
| 4. Chất lượng dữ liệu | Nguồn đáng tin, đủ lịch sử cho backtest / hiệu chỉnh sau này, point-in-time thật, xử lý trùng / spike / feed đóng băng / nhiều broker (MT-05) |
| 5. Độ tin cậy vận hành | Trên máy Windows + Docker của người dùng: khởi động lại, mất điện / mạng, Gateway MT5, sao lưu, dung lượng, theo dõi / cảnh báo khi hỏng |
| 6. Khả năng kiểm chứng | Mọi quyết định truy được về dữ liệu đầu vào, tái dựng được, đủ để GĐ6 backtest và GĐ7 hiệu chỉnh dùng lại (có đang **lưu đủ** những gì sau này cần không — cái gì không lưu từ bây giờ thì sau này không có lại được) |
| 7. Bảo mật | Phân quyền theo tài khoản, khóa API / token không lọt log / DB / phản hồi, Keycloak / BFF, Host / CORS |
| 8. Dễ dùng | Người dùng **không rành kỹ thuật và chưa từng trade**: giao diện tiếng Việt có dễ hiểu không, cảnh báo có rõ không, hướng dẫn kiểm trên máy (PowerShell) có đúng, đủ, làm theo được không |
| 9. Bảo trì + tài liệu | Code / tài liệu / trạng thái `[x]` có khớp nhau, có nợ kỹ thuật gì sẽ cản GĐ5+ |

Cách làm: chạy `uv run pytest -q` + `uv run ruff check .` (backend, mt5_gateway), `npm run check && npm run build` (frontend); **viết kịch bản kiểm riêng** (trong scratchpad, không đưa vào repo) chạy thành phần thật trên dữ liệu mẫu / thật, so với cách tính độc lập. Có Postgres 16 trên máy thử (`pg_ctlcluster 16 main start`; container khởi động lại có thể làm Postgres tắt — bật lại). TimescaleDB thật chỉ có ở CI (job `docker`).

**Đầu mối đã biết** (kiểm, đừng bỏ qua): job của cùng một sự kiện chạy theo **thứ tự chữ cái** loại job (`REGIME` trước `TECHNICAL`) — có phụ thuộc nào bị dùng bản cũ; `output_id` kiểu cũ của Technical ở mọi chỗ còn kiểm phạm vi qua id (vd. `_check_scope` trong `storage/analyst_outputs.py`); bộ đệm `_last` của `FusionRunner`; `model_copy(update=...)` của Pydantic không kiểm tra lại (đã vá `MarketView`, các hợp đồng khác chưa); Risk Engine chưa dùng trong luồng thật; hệ số GĐ4 (0,9 / 0,5 / trần 30 phút) chưa hiệu chỉnh.

### B. Khuyến nghị — xếp theo mức ưu tiên

Mỗi khuyến nghị: mã (KN-01…), **mức** (BẮT BUỘC trước GĐ5 = lỗi / rủi ro mất tiền / nhìn trước / bịa số; NÊN = nâng rõ chất lượng; CÓ THỂ), giai đoạn nên làm (đúng giai đoạn sở hữu — không dồn hết vào GĐ hiện tại), lợi ích kỳ vọng + bằng chứng, cách đo về sau, công sức (S / M / L), rủi ro, **có cần người dùng quyết không** (chi phí, nguồn trả phí, thay đổi DEC đã chốt). Chú ý riêng:
- **Việc phải bắt đầu ngay vì cần thời gian tích lũy** (lịch sử dữ liệu, ghi lại spread / tick, lưu MarketView liên tục, số dự báo cho tin…): càng trễ càng thiếu dữ liệu cho backtest / hiệu chỉnh.
- **Chuẩn bị cho GĐ6 (backtest)**: những gì cần để kết quả backtest đáng tin (chi phí, trượt giá, spread thật, walk-forward, ngoài mẫu, tránh overfitting, nhiều chế độ thị trường).
- **Quản lý vốn (DEC-09)**: nguyên tắc đã chốt (0,25–0,5 %/lệnh + ngưỡng lỗ ngày / tuần là luật cứng; 4–5 %/ngày chỉ tham khảo); tài liệu "Quản lý vốn khi trade vàng" người dùng **chưa gửi lại** — chỉ ra cần những gì từ tài liệu đó, không tự đặt số.

### C. Kết quả Pha 1

Viết `docs/danh-gia/danh-gia-GD0-GD4.md`: tóm tắt một trang (điểm từng giai đoạn × tiêu chí, 5 khuyến nghị quan trọng nhất), bảng chấm điểm có bằng chứng, danh sách phát hiện lỗi (nếu có), danh sách khuyến nghị, **những gì đã kiểm mà không thấy vấn đề** (phạm vi đã phủ) và giới hạn của lần đánh giá. Commit + push `develop` (chỉ tài liệu) → kiểm CI (`actions_list` / `get_job_logs`). Rồi tóm tắt cho người dùng bằng **tiếng Việt đơn giản, giải thích như cho người chưa từng trade**, xếp theo mức ưu tiên.

## Pha 2 — Thực hiện (chỉ khi người dùng đồng ý)

- Hỏi người dùng **từng câu một**: làm khuyến nghị nào trước (kèm 2–3 lựa chọn + khuyến nghị của bạn). Khuyến nghị mâu thuẫn quyết định đã chốt (DEC-…) → trình bày và hỏi, **không tự đổi**.
- Khuyến nghị thuộc GĐ0–GĐ4: làm từng cái một — test gồm trường hợp xấu + test hồi quy, soát lại bằng kịch bản riêng, ghi nhật ký vào **file giai đoạn của mã việc đó**, cập nhật trạng thái trong file đánh giá, nhắc mã việc + KN-xx trong commit, chạy test → push `develop` → **kiểm CI**; CI đỏ → sửa trước khi làm tiếp.
- Khuyến nghị thuộc GĐ5+: **không code** — chỉ ghi thành mục việc trong file giai đoạn tương ứng (khi người dùng đồng ý), để làm đúng lúc.
- Không mở rộng phạm vi ngoài các khuyến nghị đã duyệt.

## Lưu ý vận hành

- Máy người dùng `deploy/docker-compose.yml` **build thẳng từ `develop`**. Lịch kiểm trên máy: `docs/ke-hoach/lich-kiem-tren-may.md` (dựng lại thứ Hai 16/11 trước 22:00; đêm 16→17/11 là mục 6a — backend tắt; từ 17/11 đếm 5 ngày chạy liên tục; `kiem-mv` 18/11 + 24/11). **Trước khi push code (không phải tài liệu) lên `develop`, hỏi người dùng đã dựng lại chưa / sắp dựng lại lúc nào**, để không đưa thay đổi chưa chắc chắn lên máy giữa đợt kiểm. Không buộc người dùng dựng lại thêm lần, trừ lỗi BẮT BUỘC (khi đó nói rõ cần làm gì trên máy Windows, từng lệnh một).
- Không đổi trạng thái Gate, không tick việc nếu chưa có bằng chứng.
- Người dùng không rành kỹ thuật: tiếng Việt đơn giản, mỗi lần hỏi một câu. Không bao giờ yêu cầu dán mật khẩu / token / khóa API vào chat. Không tạo PR.
