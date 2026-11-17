# Lưu trữ nhánh cũ (dọn 2026-11-17)

Người dùng dọn nhánh 17/11 (xóa trên trang GitHub — sandbox không có quyền xóa nhánh / tạo thẻ). Ghi lại commit cuối của từng nhánh trước khi xóa — cần lại thì tạo nhánh từ mã commit (GitHub MCP `create_branch` với `from_branch` = SHA, hoặc `git push origin <sha>:refs/heads/<tên>`).

**Nhóm 1 — nhánh cũ 6–13/11.** Đã xóa 17/11. **Mọi commit cuối dưới đây đều nằm trong lịch sử `develop`** (kiểm 17/11 bằng `git merge-base --is-ancestor` trên bản sao đủ lịch sử; GitHub cũng báo "Ahead 0" cho mọi nhánh) → xóa không mất code. (Lần kiểm đầu báo "không chung gốc" là sai — bản sao trong sandbox chỉ có 50 commit gần nhất.)

| Nhánh | Commit cuối | Ngày | Nội dung commit cuối |
| --- | --- | --- | --- |
| `claude/admiring-lamport-tqd6m1` | `78fb32c70d9cad5ef99839d11e306d46254c3ff5` | 2026-11-07 | DEC-17: kiểm xong trên máy người dùng; đóng việc treo trước bước 1 GĐ1 |
| `claude/beautiful-dirac-lig27j` | `8874d6c1effed955b34ffa0d939cde3e1bcf5c60` | 2026-11-06 | GW-05: người dùng đã đổi token ingest |
| `claude/beautiful-edison-9szk0t` | `ce9a5baf956c026ae94e107a06be8ac6b5930432` | 2026-11-07 | MT-12 + GW-09: kiểm xong trên máy người dùng (login/server/số liệu tài khoả |
| `claude/determined-cerf-vhzqk0` | `321a5d6f86977a595f367f8470994680953a9c36` | 2026-11-13 | GĐ1: 6a lần 1 không hợp lệ (Gateway bị tắt 23:57), hẹn làm lại; ghi 2 đi |
| `claude/gd0-foundation-setup-uzynq1` | `13cb0a59a63b2d56fba6c8a610198e345f984a03` | 2026-11-06 | MT-12..MT-19: ghi yêu cầu chính thức luồng đăng nhập -> liên kết MT5 -> gia |
| `claude/happy-wozniak-yx9hr2` | `a217f66e03ba43f98ec04c3702980d4d14a05817` | 2026-11-07 | CAL-03: bước 2 GĐ1 đã chạy trên máy người dùng (log có bảng ngày lễ) |
| `claude/laughing-euler-hnuy42` | `73922345ebaf0a6c3b9a2ad218363c6b30763141` | 2026-11-07 | 1A-C21: kiểm xong trên máy người dùng (nến cuối thứ Sáu M15/H1/H4/D1 vào n |
| `claude/loving-fermat-8ko7it` | `3fad1959ea5e279454cec4a0881d80ad82f7e8cb` | 2026-11-13 | PROGRESS: rút gọn, ghi việc phiên sau (GĐ2 4b) |
| `claude/magical-tesla-dye04e` | `459d0656924aaafd9a483f154d8d7266da634fd4` | 2026-11-06 | Tách PROGRESS/CHECKLIST theo giai đoạn để tiết kiệm token |
| `claude/nice-cannon-soxjfm` | `3f6f9958265de185b3ad8f8f38984038848dccbf` | 2026-11-12 | Ghi nhận CI xanh lại sau khi sửa migration 0009 |
| `claude/nice-pasteur-d6qkfb` | `c15f8e9a919f202ad631af36e04e12f4cd47b0a8` | 2026-11-06 | Đóng GĐ0 (người dùng xác nhận); chuyển GĐ1 + prompt bắt đầu phiên mới |
| `claude/nifty-maxwell-xse68m` | `b42bd6f18684243ceb53d485b0c3d48261ace306` | 2026-11-07 | GĐ1: người dùng chốt giữ thứ tự đề xuất, bắt đầu bước 1 |
| `claude/optimistic-bell-eazwsc` | `393c019edeab4d79262445f4dfe4c63c9b727966` | 2026-11-13 | PROGRESS: rút gọn trạng thái bước 7–8 |
| `claude/sleepy-fermi-1jsgdi` | `6aeee287152c55c9fae660e96200678f06733469` | 2026-11-13 | GĐ1 bước 7b — ING-30: trạng thái nguồn ngoài HEALTHY/STALE/MISSING/INVALID, TT |
| `claude/youthful-tesla-21q2ri` | `32e3d7f13139f5f5afca08b5fd349bff81841cfc` | 2026-11-13 | PROGRESS: rút gọn, ghi phiên mới bắt đầu từ 9f |
| `claude/zealous-hamilton-5crveb` | `94622e84478cf3addc0eb025cf15209091654c88` | 2026-11-11 | MT-05 (đọc): mỗi tài khoản xem giá + analyst theo nguồn giá của mình (GĐ1  |

**Nhóm 2 — đã gộp hết vào `develop`**, đã xóa 17/11:

- `claude/affectionate-einstein-8ypy59` — `01056f3`
- `claude/awesome-maxwell-g5y0zs` — `1a5e974`
- `claude/fervent-hypatia-n3uyfn` — `028c74a`
- `claude/inspiring-euler-xn2a7r` — `613b847`
- `claude/inspiring-volta-978t2l` — `544d044`
- `claude/sleepy-clarke-pca9oo` — `7185482`
- `claude/vigilant-hopper-f4wuqk` — `97de1da`

**Nhóm 3 — `main`** (người dùng chọn 17/11: chỉ giữ `develop`): `main` — `8e4aae838adc79e343d0fad4aafdfb52ef11f12c` (05/11, "gold_trading init project": tài liệu đặc tả ban đầu — đã có trong `develop` — + 2 file `.DS_Store`). Nhánh mặc định của kho là `develop`.

Còn lại trên GitHub (kiểm 17/11): **chỉ `develop`** (cả `claude/wizardly-franklin-8zeol8` cũng đã xóa). Cần lại nhánh nào: tạo từ mã commit ở trên.
