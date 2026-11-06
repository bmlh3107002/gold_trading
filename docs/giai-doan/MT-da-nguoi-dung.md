# MT — Đa người dùng, mỗi người một tài khoản riêng (để sau)

> Một phần của bản đồ việc theo giai đoạn (tách từ `CHECKLIST.md` 2026-11-06). Chỉ mục, nguyên tắc và bất biến: [`README.md`](README.md). Trạng thái chung: `PROGRESS.md`. Ghi chú kỹ thuật: `docs/ghi-chu-ky-thuat.md`.


**Trạng thái: nền móng làm trong GĐ0 (người dùng chốt 2026-11-06).** **Luồng giao dịch riêng từng người (đăng nhập → liên kết MT5 → lệnh vào đúng MT5) là yêu cầu chính thức (người dùng chốt 2026-11-06), thiết kế ở `docs/thiet-ke/00-xac-thuc-phan-quyen.md` mục 14: MT-12..MT-18 (GĐ1/GĐ8/GĐ9) — CHƯA làm; token Gateway theo tài khoản (MT-04) KHÔNG phải xác minh danh tính MT5.** Mục tiêu: **mỗi người có vốn, MT5, hồ sơ rủi ro, lệnh riêng**. Việc ghi "GĐ0" làm ngay; việc khác làm ở giai đoạn ghi bên cạnh. Chưa nhận người dùng thứ hai trước khi DEC-11, DEC-12 được trả lời.

Ảnh hưởng tới các giai đoạn: dữ liệu thị trường (giá, tin, lịch, vĩ mô) **dùng chung theo nguồn/broker**; còn tài khoản MT5, Gateway + token, hồ sơ rủi ro, chiến lược được bật, Safety, Mode, Ledger, lệnh, vị thế, hiệu suất, audit thì **riêng từng tài khoản**.

| Mã | Câu hỏi cần chốt | TT |
| --- | --- | --- |
| DEC-11 | Người dùng là ai: người thân/bạn bè hay khách hàng bên ngoài? Hệ thống **tự giao dịch tiền của họ** hay chỉ đưa phân tích để họ tự quyết? | `[x]` 2026-11-06: người thân/bạn bè, hệ thống **tự giao dịch** |
| DEC-12 | Rủi ro pháp lý khi quản lý/giao dịch tiền của người khác hoặc cung cấp khuyến nghị đầu tư (cần hỏi luật sư theo nơi cư trú) | `[x]` 2026-11-06: người dùng **chấp nhận rủi ro**, chỉ dùng **nội bộ** (bản thân và người thân), **không giới hạn số người** → bật `GT_MULTI_USER_ENABLED=1` trên máy người dùng |
| DEC-13 | Nơi chạy hệ thống: máy của người dùng hiện tại (Tailscale) hay máy chủ riêng; mỗi người tự chạy Gateway trên máy Windows của họ hay gom về một máy | `[x]` 2026-11-06: máy Windows của người dùng, **gom mọi Gateway/MT5 về máy này** (nhiều terminal MT5 trên một máy: GĐ1/MT-05) |
| DEC-14 | Các broker khác nhau → lịch phiên, spread, giá khác nhau: chấp nhận nhiều nguồn giá song song? | `[!]` |
| DEC-15 | Vai trò của tài khoản `admin` | `[x]` 2026-11-06: **chỉ quản trị, không giao dịch**; ẩn token Gateway với admin (chi tiết: `docs/thiet-ke/00-xac-thuc-phan-quyen.md` mục 0). Yêu cầu kèm theo cho MT-15: một máy Windows chạy nhiều MT5, mỗi người chỉ thao tác MT5 của mình; mong muốn **một Gateway quản lý nhiều terminal** (mỗi terminal một nhánh, token riêng) |

| Mã | Việc | TT | Ghi chú |
| --- | --- | --- | --- |
| MT-01 | Mô hình dữ liệu: `User` (khóa theo `sub` của Keycloak), `TradingAccount` (một tài khoản MT5), vai trò theo tài khoản (`OWNER`/`OPERATOR`/`VIEWER`) + quản trị hệ thống | `[x]` | **GĐ0.** Bảng `users`, `trading_accounts`, `account_members` (migration 0004). ADMIN đầu tiên đăng nhập → OWNER tài khoản `default`. Test: `tests/test_repository_accounts.py` (bộ nhớ + SQLite) |
| MT-02 | Thêm `account_id` vào mọi bảng riêng (Safety, Mode, audit, hồ sơ rủi ro, ledger, lệnh, vị thế, analyst output dùng dữ liệu riêng) bằng migration mới; dữ liệu hiện có gán cho tài khoản đầu tiên | `[x]` | **GĐ0.** `account_id` cho Safety/Mode/audit (+ `actor_sub`), dữ liệu cũ → `default` bằng `ADD COLUMN DEFAULT` (không UPDATE). Đã kiểm trên TimescaleDB thật: trigger append-only còn nguyên, schema khớp migration |
| MT-03 | Mọi API/truy vấn lọc theo tài khoản của người đang đăng nhập (chặn ở tầng truy cập dữ liệu, không chỉ ở giao diện) | `[x]` | **GĐ0.** Mọi API của tài khoản đi qua `Guard.check` (không thành viên → 404, thiếu quyền → 403, có audit). Dữ liệu thị trường dùng chung |
| MT-04 | Token Gateway riêng từng tài khoản; Gateway chỉ ghi được vào tài khoản của mình | `[x]` | **GĐ0.** Token `gtk_…` lưu SHA-256, xoay thu hồi token cũ ngay, `GT_INGEST_TOKEN` cũ chỉ còn cho `default` tới lần xoay đầu; Gateway khai sai `account_id` → 403; chỉ tài khoản `price_feed` ghi nến. Giao diện: trang Tài khoản (hiện token đúng một lần) |
| MT-05 | Nguồn giá theo broker/server (một tài khoản ↔ một nguồn); analyst chạy theo từng nguồn | `[ ]` | **GĐ1.** ← ING-15, DEC-14 |
| MT-06 | Safety và Mode theo từng tài khoản + kill switch toàn hệ thống cho quản trị | `[x]` | **GĐ0.** `accounts/runtime.py`: Safety/Mode riêng từng tài khoản, khôi phục cho mọi tài khoản, DB là nguồn sự thật (ghi có `expected_last`, đồng bộ 2 s), kill switch toàn hệ thống `POST /api/admin/kill-switch` |
| MT-07 | Hồ sơ rủi ro, hạn mức, ledger, đối soát theo từng tài khoản | `[ ]` | **GĐ5.** |
| MT-08 | Duyệt LIVE theo từng tài khoản (approver khác actor, cùng quyền với tài khoản đó) | `[ ]` | **GĐ10.** |
| MT-09 | Dashboard: chọn tài khoản, chỉ thấy tài khoản được cấp quyền | `[x]` | **GĐ0.** Header: người đăng nhập, chọn tài khoản (chỉ tài khoản có quyền), đăng xuất; nút khóa theo `permissions` từ backend; duyệt LIVE; kill switch ADMIN; trang `#account` |
| MT-10 | Quản lý người dùng: mời, khóa, đổi vai trò, có audit | `[x]` | **GĐ0.** `/api/accounts/{id}/members` thêm (username/email của người đã đăng nhập), đổi vai trò, gỡ; không gỡ/hạ OWNER cuối; audit; `GT_MULTI_USER_ENABLED=0` chặn người thứ hai (DEC-12). Test: `tests/test_members.py`. Khóa người dùng toàn hệ thống: vô hiệu hóa trên Keycloak (≤ 60 s) |
| MT-11 | Mã hóa/bảo vệ thông tin tài khoản MT5 và token | `[x]` | **GĐ0.** Bí mật chỉ ở `.env`/`gateway.env` (gitignore, compose bắt buộc biến), realm JSON chỉ có placeholder (CI kiểm), token Gateway lưu băm + chỉ trả một lần (`Cache-Control: no-store`), phiên/refresh token chỉ trong bộ nhớ, log che bí mật. Backend không lưu thông tin đăng nhập MT5 |
| MT-12 | Gateway (vẫn **chỉ đọc**) đọc danh tính terminal: MT5 **login**, server, company, loại tài khoản (DEMO/REAL), đường dẫn terminal; gửi trong nhịp tim | `[ ]` | **GĐ1** (cùng GW-09). Hiện nhịp tim chưa có login |
| MT-13 | **Liên kết MT5** (`mt5_links`: account_id, login, server, company, gateway_id, token_id, trạng thái, người/giờ xác minh); luồng: Gateway báo danh tính → OWNER xác nhận "login X / server Y" → ACTIVE; một `(login, server)` không ACTIVE ở 2 tài khoản; có audit | `[ ]` | **GĐ1.** Thiết kế: `docs/thiet-ke/00-xac-thuc-phan-quyen.md` mục 14 |
| MT-14 | Phát hiện terminal đổi tài khoản / sai liên kết / mất kết nối → liên kết MISMATCH/DISCONNECTED, chặn ghi dữ liệu của tài khoản, cảnh báo, yêu cầu xác minh lại; **không tự chuyển** sang MT5 mới | `[ ]` | **GĐ1** (chặn + cảnh báo); nối Safety tự động ở GĐ8 (SAF-04) |
| MT-15 | Gateway kết nối **đúng terminal đã cấu hình** (đường dẫn terminal), nhiều terminal MT5 trên một máy Windows (DEC-13) | `[ ]` | **GĐ1** (cùng MT-05) |
| MT-16 | Paper trading theo tài khoản: lệnh/vị thế/vốn/ledger có `account_id` + `link_id`; không có liên kết ACTIVE → không tạo lệnh | `[ ]` | **GĐ8** |
| MT-17 | Định tuyến lệnh: backend chỉ giao lệnh của tài khoản X cho thành phần thực thi của **liên kết ACTIVE của X**; không có đường dự phòng sang MT5/Gateway khác | `[ ]` | **GĐ9** (← GW-10) |
| MT-18 | **Kiểm tra danh tính trước MỌI thao tác lệnh** (đặt/sửa/hủy/đóng): lệnh mang `expected_login/server/link_id`; thành phần thực thi đọc `account_info()` ngay trước khi gửi; lệch/không đọc được → từ chối `MT5_IDENTITY_MISMATCH`/`MT5_DISCONNECTED`, PAUSE/HALT tài khoản đó, audit, cảnh báo | `[ ]` | **GĐ9** |
| MT-19 | Giao diện: người chỉ có **một** tài khoản giao dịch không phải chọn tài khoản (bộ chọn chỉ hiện khi ≥ 2), đăng nhập xong tự dùng tài khoản của mình | `[x]` | **GĐ0.** `Header.tsx`; test `App.test.tsx` (1 tài khoản: không có bộ chọn; 2 tài khoản: có, đổi được) |
| MT-20 | ADMIN tạo người dùng trên Dashboard (menu **Quản trị** chỉ ADMIN thấy): tự tạo trên Keycloak (mật khẩu tạm ADMIN nhập, bắt đổi lần đầu) + tài khoản giao dịch riêng, người đó là Chủ; không giới hạn số người | `[x]` | **GĐ0.** Thiết kế `docs/thiet-ke/00-xac-thuc-phan-quyen.md` mục 15. `api/users.py`, `auth/kc_admin.py`, migration 0005, `sync-client.sh`; test `test_admin_users.py`, `AdminPage.test.tsx`, `ci_stack.sh`. Chưa có: danh sách/khóa/xóa người dùng trên Dashboard |

| Mã | Tình huống | Hành vi bắt buộc | TT |
| --- | --- | --- | --- |
| MT-C01 | Người A gọi API với id tài khoản của người B | 404/403, ghi audit | `[x]` `tests/test_rbac.py`: `test_user_cannot_see_or_touch_other_account` |
| MT-C02 | Gateway của A gửi dữ liệu kèm tài khoản B | Từ chối | `[x]` `tests/test_gateway_tokens.py::test_gateway_of_a_cannot_write_into_b` |
| MT-C03 | A bấm dừng khẩn cấp | Chỉ tài khoản A dừng; B không bị ảnh hưởng | `[x]` `tests/test_rbac.py`: `test_halt_of_one_account_does_not_affect_other` |
| MT-C04 | Quản trị bấm kill switch toàn hệ thống | Mọi tài khoản HALTED | `[x]` `tests/test_rbac.py`: `test_global_kill_switch_halts_every_account_admin_only` |
| MT-C05 | Hai tài khoản khác broker, giờ phiên khác nhau | Mỗi tài khoản dùng lịch và giá của broker mình | `[ ]` |
| MT-C06 | Người dùng bị khóa khi đang có lệnh mở | Không thao tác được nữa; vị thế vẫn được Safety/Guardian bảo vệ | `[x]` `tests/test_rbac.py`: `test_removed_user_cannot_act_but_safety_state_is_kept` |
| MT-C07 | Lỗi/sự cố ở tài khoản A (ví dụ lệch đối soát) | Chỉ HALT tài khoản A | `[ ]` |
| MT-C08 | Người dùng đổi sang MT5 khác trên terminal đã liên kết | Liên kết MISMATCH; chặn ghi + chặn lệnh; cảnh báo; phải xác minh lại; không tự đổi liên kết | `[ ]` (GĐ1; lệnh: GĐ9) |
| MT-C09 | Tài khoản giao dịch **chưa có liên kết** MT5 | Không dữ liệu riêng, không lệnh; **không** dùng MT5 chính hay Gateway người khác | `[~]` GĐ0: tài khoản không phải nguồn giá không ghi được nến (`test_gateway_of_a_cannot_write_into_b`); phần lệnh: GĐ8/GĐ9 |
| MT-C10 | Hai người cùng broker, khác login (111111 / 222222) | Mỗi lệnh chỉ vào đúng login đã liên kết | `[ ]` (GĐ9) |
| MT-C11 | Cùng một `(login, server)` bị liên kết ở tài khoản giao dịch thứ hai | Từ chối liên kết thứ hai | `[ ]` (GĐ1) |
| MT-C12 | Terminal mất kết nối / đăng xuất ngay trước khi gửi lệnh | Từ chối `MT5_DISCONNECTED`, không thử MT5 khác | `[ ]` (GĐ9) |
| MT-C13 | Gateway của B cố nhận lệnh của A | Từ chối (xác thực theo liên kết ACTIVE của A) | `[ ]` (GĐ9) |
| MT-C14 | Liên kết lại sang MT5 mới | Tạo liên kết mới cần xác nhận; lịch sử lệnh/vị thế cũ không trộn | `[ ]` (GĐ1/GĐ9) |
| MT-C15 | Người chỉ có một tài khoản giao dịch đăng nhập | Tự dùng tài khoản đó, không hiện bộ chọn | `[x]` `App.test.tsx` |
