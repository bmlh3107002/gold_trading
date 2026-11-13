# Bản đồ việc theo giai đoạn — Gold Trading AI

> **Cách dùng (tiết kiệm token):** mỗi phiên chỉ đọc `PROGRESS.md` (ngắn, tự nạp qua `CLAUDE.md`) rồi mở **đúng một** file của giai đoạn đang làm. Không đọc các giai đoạn khác trừ khi cần tra một mã việc.
> Bám mô hình (`docs/mo-hinh/gold-bot-1-tong-the.png`, `docs/mo-hinh/gold-bot-2-market-intelligence.png`) và đặc tả `docs/huong-dan-chuc-nang/01–12`.

> Mỗi file giai đoạn chứa: việc (mã), bảng case, Gate, việc tiếp theo và **nhật ký của chính giai đoạn đó**. Hai nơi mâu thuẫn thì kiểm tra code rồi sửa cả hai.

## Nguyên tắc "đi sạch từng giai đoạn" (người dùng chốt 2026-11-06)

1. Làm **hết** một giai đoạn rồi mới sang giai đoạn sau. Giai đoạn có nhiều phần (1A, 1B, …) thì xong **tất cả** các phần.
2. Mỗi giai đoạn làm **đủ mọi nguồn/thành phần mà mô hình yêu cầu**, không chỉ lấy một cái để thử.
3. Mỗi giai đoạn có **bảng case** (tình huống có thể xảy ra, kể cả xấu). Mỗi case phải có **test** và **hành vi mặc định an toàn**.
4. Chỉ qua giai đoạn khi đạt hết **Điều kiện qua giai đoạn (Gate)**, có kiểm chứng trên máy người dùng nếu Gate yêu cầu, và người dùng xác nhận.
5. Việc mà người dùng **chủ động hoãn** được ghi `(hoãn)` và không chặn Gate. Chỉ người dùng mới được hoãn.
6. Trong lúc làm phát hiện case mới → thêm vào bảng case của giai đoạn đó trước khi đóng giai đoạn.
7. **Bảo mật và phân quyền làm ngay trong GĐ0** (người dùng chốt 2026-11-06, đổi quyết định trước đó): đăng nhập bằng **Keycloak**, phân quyền theo vai trò, nền móng đa người dùng (phần **MT**: các việc ghi "GĐ0" làm ngay, phần còn lại làm trong giai đoạn tương ứng). Prompt thực hiện: `docs/prompts/GD0-hoan-thien-nen-mong.md`.

## Cách đọc và cập nhật

**Trạng thái:** `[x]` xong (có test, đã kiểm chứng) · `[~]` có một phần · `[ ]` chưa làm · `[!]` chờ người dùng (quyết định/thao tác)

**Mã việc:** `<KHỐI>-<số>` (ví dụ `ING-09`). **Mã case:** `<giai đoạn><phần>-C<số>` (ví dụ `1A-C07`). **Mã quyết định:** `DEC-<số>`.
Mã **không bao giờ đổi hoặc dùng lại**; việc mới lấy số kế tiếp của khối. Việc bị bỏ giữ dòng, ghi `(bỏ: lý do)`.

**Khi làm một việc:** đọc `CLAUDE.md` + đặc tả tương ứng → làm **một** mã việc, có test cho các case liên quan → kiểm chứng bằng kịch bản riêng → đổi trạng thái và ghi nhật ký **trong file của giai đoạn đó**, cập nhật mục "Trạng thái hiện tại" ở `PROGRESS.md` (ngắn), commit có mã việc (`ING-09: ...`), push `develop`. Thay đổi ảnh hưởng quyết định giao dịch phải ghi lý do ở `docs/thiet-ke/`.

**Bất biến toàn hệ thống:** point-in-time (`available_at <= decisionAt`), UTC, idempotent, append-only, LIVE khóa mặc định, Safety + Guardian chặn cao nhất, không `MarketView` hợp lệ → không tín hiệu, không phê duyệt Risk → không gửi lệnh, dữ liệu `SAMPLE` không bao giờ dẫn tới SHADOW/LIVE, thiếu dữ liệu → "không đủ dữ liệu" (không đoán, không nội suy), không gọi là "xác suất" khi chưa hiệu chỉnh.

## Lộ trình giai đoạn (theo luồng của mô hình)

| GĐ | Tên | Khối mô hình | Đặc tả | Trạng thái |
| --- | --- | --- | --- | --- |
| 0 | Nền móng: contract, DB, Docker, CI, bảo mật, sao lưu | Database, Vận hành | 01, 12 | `[x]` (đóng 2026-11-06; OPS-06 hoãn) |
| 1 | **Dữ liệu vào: đủ 4 nhóm nguồn** + lịch thị trường | Nguồn dữ liệu, Ingestion | 02 | `[~]` (code xong 2026-11-13; chờ kiểm / Gate — DEC-19) |
| 2 | Event Orchestrator + Làn nhanh | Event Orchestrator, Làn nhanh | 03 | `[~]` (bắt đầu 2026-11-13, song song GĐ1 — DEC-19) |
| 3 | **6 analyst** (bản luật, chưa ML) | Market Intelligence | 04 | `[~]` (Technical) |
| 4 | Snapshot → Quality Gate → Fusion → MarketView | Market Intelligence | 05 | `[~]` |
| 5 | **Kế hoạch giao dịch:** hồ sơ rủi ro + chiến lược + Risk Engine + Ledger | Strategy, Risk Engine, Risk ledger | 06, 07 | `[~]` |
| 6 | Backtest có chi phí thật | Backtest | 12 | `[ ]` |
| 7 | Training + AI Service + kiểm soát mô hình (ML) | Training, AI Service | 05, 11 | `[ ]` |
| 8 | Paper trading: giả lập khớp lệnh bằng giá sống, Safety tự động, quản lý vị thế, hiệu suất | Safety, Execution, Position Manager, Performance | 08, 09, 10 | `[ ]` |
| 9 | Kết nối lệnh MT5 **demo**: đặt lệnh, đối soát, Guardian EA | Execution, MT5 Gateway, MT5 + Guardian EA | 09 | `[ ]` |
| 10 | SHADOW → LIVE (canary nhỏ) | Mode manager | 12 | `[ ]` |

Dashboard và vận hành của từng thành phần được làm **trong giai đoạn của thành phần đó**, không dồn về cuối.

## File theo giai đoạn

- [GD0-nen-mong.md](GD0-nen-mong.md)
- [GD1-du-lieu-vao.md](GD1-du-lieu-vao.md)
- [GD2-event-orchestrator.md](GD2-event-orchestrator.md)
- [GD3-analyst.md](GD3-analyst.md)
- [GD4-snapshot-fusion-marketview.md](GD4-snapshot-fusion-marketview.md)
- [GD5-ke-hoach-giao-dich.md](GD5-ke-hoach-giao-dich.md)
- [GD6-backtest.md](GD6-backtest.md)
- [GD7-training-ai.md](GD7-training-ai.md)
- [GD8-paper-trading.md](GD8-paper-trading.md)
- [GD9-lenh-mt5-demo.md](GD9-lenh-mt5-demo.md)
- [GD10-shadow-live.md](GD10-shadow-live.md)
- [MT-da-nguoi-dung.md](MT-da-nguoi-dung.md)

## Backlog cũ (tham khảo, chuyển từ `PROGRESS.md`)



00. Theo dõi vài ngày ngưỡng R3 (spike 8× trung vị) và R5 trên dữ liệu MetaQuotes-Demo. Người dùng đổi token ingest (token đã lộ trong chat).
0. **Hồ sơ rủi ro + Kế hoạch giao dịch** (làm cùng ③): người dùng nhập vốn, mục tiêu lãi, lỗ tối đa, thông số broker → hệ thống đề xuất SL theo ATR, TP theo R:R, lot, thời gian giữ lệnh ước tính, kết luận khả thi. Hồ sơ lưu có phiên bản. Khi dùng dữ liệu mẫu thì ghi "chỉ minh họa". Mục tiêu người dùng: lãi nhỏ nhưng ổn định (ví dụ 4–5%, chưa chốt theo ngày/tuần/tháng), vốn ví dụ 100$; với lot tối thiểu 0,01 thì 100$ không đủ để rủi ro 1% theo ATR M15, phải báo rõ.
1. **Event & calendar analyst** (ưu tiên cao: chặn giao dịch quanh CPI/NFP/FOMC, tạo cờ `EVENT_WINDOW` mà Risk Engine đã chờ sẵn).
2. **Event Orchestrator đầy đủ:** hiện `TechnicalRunner` polling 15s là bản tối thiểu; cần jobKey, deadline, retry giới hạn, dead-letter.
3. **Fusion đơn giản → `MarketView`** đầu tiên, hiển thị trên Tổng quan. MarketView sinh từ dữ liệu mẫu phải mang cờ để Risk chặn ở SHADOW/LIVE.
4. Strategy Engine và Backtest (replay theo `available_at`, có spread/slippage/phí). Backtest trên dữ liệu mẫu phải đánh dấu "không có giá trị đánh giá".
5. ~~Xác thực API~~ — xong ở GĐ0 (Keycloak).
6. **Giá sống (bid/ask/spread)** từ Gateway sang backend: để hiển thị và để Risk kiểm tra ngay trước khi vào lệnh (bỏ lệnh nếu spread giãn hoặc giá đã chạy xa so với lúc nến đóng). Phân tích vẫn chỉ dùng nến đã đóng. Phải có trước Strategy/đặt lệnh.
7. **CD tự deploy lên máy Windows** (đã chốt thiết kế ở nhật ký 2026-11-06, chưa làm).
8. Gateway: chạy như dịch vụ Windows, đóng gói `.exe` (build trên runner Windows), hàng đợi bền vững; lịch giao dịch từ MT5 (R12). Đặt lệnh: thành phần riêng, làm sau cùng.

## Phụ lục — Mã cũ đã chuyển chỗ

Không có mã nào bị xóa. `ING-11` (vĩ mô) và `ING-12` (vị thế) nay là khung chung của 1E/1F, chi tiết tách thành `ING-24..29`. `TEC-08`, `FUS-02`, `MQC-01`, `AIS-01..02`, `TRN-01..04` chuyển sang GĐ7. `REG-01` là bản luật; bản ML là `REG-03`.
