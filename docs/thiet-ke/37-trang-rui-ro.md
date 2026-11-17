# 37 — Báo cáo khả thi + trang Rủi ro (GĐ5 bước 8 — RPF-02..05, DSH-05)

> 2026-11-17, viết trước khi code. Kế hoạch: [`GD5-ke-hoach.md`](../ke-hoach/GD5-ke-hoach.md) bước 8. Dựa trên thiết kế 35 (mục 7, 9, 12) và 36 (chiến lược v1).
>
> **Không có lệnh thật.** Trang này chỉ đọc trạng thái + cho chủ tài khoản nhập những thứ Risk đang chờ (hồ sơ rủi ro, phí / lot, bắt đầu sổ paper). Tới khi nhập đủ, Risk từ chối hoặc chiến lược bỏ qua mọi lệnh (an toàn).

## 1. Chia nhỏ

| Phần | Nội dung |
| --- | --- |
| **8a** | Báo cáo khả thi (`risk/feasibility.py`, hàm thuần) + lệnh `cli kha-thi` (chỉ đọc) — RPF-02, RPF-03, RPF-04 |
| **8b** | API `/api/accounts/{id}/risk/...` (đọc + ghi, chỉ chủ tài khoản) — RPF-05 phía backend |
| **8c** | Trang **Rủi ro** ở giao diện — DSH-05 |

## 2. Báo cáo khả thi (8a)

Câu hỏi nó trả lời: "với vốn, sàn và biến động **thật** hiện nay, chiến lược v1 có vào được lệnh trong mức rủi ro đã chọn không?"

**Đầu vào, tất cả đọc thật lúc chạy** (thiếu cái nào → `KHONG_DU_DU_LIEU` kèm danh sách thiếu, không đoán): equity MT5 (nhịp tim ≤ 30 giây) và equity paper nếu đã bắt đầu (lấy số nhỏ hơn, như Risk); thông số broker `spec_at` (cỡ HĐ, lot min / bước, point, swap); **ATR14 M15 đo thật** = output Technical mới nhất còn hạn của nguồn giá tài khoản; spread hiện tại + p95 30 ngày (cùng cách Risk); phí / lot đã nhập; hồ sơ rủi ro (mức / lệnh) — chưa có thì tính cho **cả 0,25 % và 0,5 %** để tham khảo.

**Tính** (cùng công thức Risk RSK-11 + chiến lược v1, không có công thức thứ hai):

```
khoảng SL       D  = 1,5 × ATR (P7)
rủi ro / lot    R1 = (D + spread + đệm p95) × cỡ HĐ + phí / lot + swap một đêm   (như Risk)
lot ở mức r     V  = floor(r × equity / R1 theo bước lot)
vốn tối thiểu   E  = lot min × R1 / r
rủi ro lot min  = lot min × R1  (= bao nhiêu % vốn)
R:R sau chi phí = ((2 × D − spread) × cỡ HĐ − phí − swap) / R1   (TP = 2 × SL, P8)
giữ lệnh tối đa = tới 16:45 NY cùng ngày (P10): vào lúc 03:00 → ≤ 13 giờ 45 phút
```

**Kết luận** cho từng mức r: `KHA_THI` (V ≥ lot min) / `KHONG_KHA_THI` (kèm số tiền thiếu = E − equity). R:R < 1,5 → ghi cảnh báo. ATR thay đổi theo ngày → báo cáo ghi rõ "số tại thời điểm chạy".

**RPF-04 — dữ liệu mẫu:** nguồn `SAMPLE` (không có broker / equity thật) → báo cáo vẫn chạy được phần có thể tính, gắn nhãn **"CHỈ MINH HỌA — dữ liệu mẫu"** ở đầu, và kết luận luôn là `CHI_MINH_HOA` (không bao giờ `KHA_THI`). Báo cáo không dẫn tới quyết định nào (chỉ đọc).

**`cli kha-thi [--account <id>]`**: đọc DB, in báo cáo tiếng Việt, mã thoát 0 khi chạy được (kể cả không khả thi), 1 khi lỗi đọc.

## 3. API (8b) — `/api/accounts/{id}/risk`

Mọi đường đều qua `Guard.check` (chỉ **chủ tài khoản** USER đang hoạt động; ADMIN không vào — DEC-16, Q6); mọi lệnh ghi có `reason` (bắt buộc, ≤ 256 ký tự) và ghi audit.

| Đường | Làm gì |
| --- | --- |
| `GET /overview` | hồ sơ hiện hành + lịch sử phiên bản; phí / lot hiện hành + lịch sử; sổ paper (đã bắt đầu chưa, vốn đầu, equity đã chốt, đỉnh, mức sụt, lệnh đang mở, giữ chỗ đang mở); **mức đã dùng** (số lệnh hôm nay / tối đa, lỗ đã chốt ngày / tuần / tháng so với ngưỡng, chuỗi thua — theo mốc 17:00 NY của hồ sơ); 20 quyết định Risk gần nhất (kết quả + mã lý do); 20 lần xét chiến lược gần nhất; `is_sample`; chiến lược bật / tắt |
| `GET /feasibility` | báo cáo khả thi (mục 2) |
| `POST /profile` | tạo phiên bản hồ sơ mới (kiểm hợp lệ cứng của thiết kế 35 mục 9; sai → 422 kèm thông báo tiếng Việt) |
| `POST /commission` | nhập phí / lot (≥ 0, ≤ 1.000 USD, USD) |
| `POST /paper/start` | bắt đầu sổ paper; vốn đầu = **equity MT5 đọc từ nhịp tim lúc bấm** (không cho gõ tay — tránh số bịa); không có nhịp tim mới → 409 |
| `POST /paper/cash` | nạp / rút (H10); có lệnh paper đang mở mà không có giá mới → 409 (không tính được equity trước rút) |
| `POST /paper/drawdown-reset` | xác nhận rõ sau khi dừng vì sụt (H6): phải gửi `confirm: true` + lý do; đỉnh = equity hiện tại |

Lỗ "đã dùng" trên trang chỉ tính **lệnh đã đóng** (PnL đang chạy hiện riêng khi có giá) — trang để xem, Risk vẫn tự tính đủ lúc quyết.

## 4. Trang Rủi ro (8c)

Mục "Rủi ro" ở thanh bên (chỉ USER). Các thẻ, từ trên xuống:

1. **Tình trạng sẵn sàng**: danh sách 3 việc cần làm trước khi chiến lược paper chạy được — hồ sơ rủi ro / phí / bắt đầu sổ paper (✓ / chưa), kèm câu giải thích đơn giản.
2. **Hồ sơ rủi ro**: giá trị hiện hành bằng lời (vd. "Rủi ro mỗi lệnh: 0,25 % vốn"), lịch sử phiên bản; nút "Tạo phiên bản mới" mở biểu mẫu điền sẵn (bản hiện hành, hoặc H1–H11 bạn đã chốt nếu chưa có), mỗi ô ghi giới hạn cho phép.
3. **Phí giao dịch**: phí / lot hiện hành + biểu mẫu nhập.
4. **Sổ paper**: bắt đầu (hiện equity MT5 sẽ dùng làm vốn), vốn / equity / đỉnh / mức sụt; nạp / rút; xác nhận sau khi dừng (chỉ hiện khi đang sụt ≥ ngưỡng).
5. **Mức đã dùng hôm nay / tuần / tháng**, lệnh đang mở, giữ chỗ đang mở.
6. **Khả thi**: kết luận + bảng số (mục 2), nhãn "CHỈ MINH HỌA" khi dữ liệu mẫu.
7. **Hoạt động gần đây**: quyết định Risk + lần xét chiến lược, mã lý do dịch sang tiếng Việt (mã lạ hiện nguyên mã).

Số tiền / tỷ lệ hiển thị từ chuỗi `Decimal` của API (không đổi sang số thực để tính lại ở trình duyệt).

## 5. Giới hạn

- Biểu mẫu nhận số người dùng gõ; kiểm cứng ở backend (DEC-09 không vượt được).
- Báo cáo khả thi dùng ATR **một thời điểm**; ATR trung bình nhiều tuần cần dữ liệu MT5 dài hơn (sau khi chạy liên tục).

## 6. Nhật ký

- **2026-11-17** — Hiện thực xong 8a / 8b / 8c như mục 2–4. Khác bản thiết kế: (1) `cli kha-thi` chạy tiến trình riêng nên không thấy nhịp tim → equity lấy bản ghi theo giờ của Gateway (≤ 2 giờ, cũ hơn → thiếu); (2) không có giây giá mới → spread dùng p95 30 ngày (ghi rõ trong báo cáo) thay vì báo thiếu, để chạy được lúc thị trường đóng; (3) swap trong báo cáo = chiều tệ hơn (BUY / SELL) × số đêm của lần chốt kế tiếp (như Risk).
