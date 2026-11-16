# 34 — Lịch sử thông số broker + số liệu tài khoản (KN-05, GW-09)

> 2026-11-16 · Khuyến nghị KN-05 của đánh giá độc lập GĐ0–GĐ4. Migration 0023. Mã: `storage/broker_history.py`, ghi ở `api/ingest.py` (nhịp tim Gateway).

## 1. Vì sao

Gateway (≥ 0.3) gửi trong mỗi nhịp tim: thông số mã giao dịch (cỡ hợp đồng, point, bước / min / max khối lượng, stops / freeze level, swap long / short / kiểu swap / ngày tính swap ba lần) và số liệu tài khoản (tiền tệ, balance, equity, margin, đòn bẩy). Trước đây chỉ giữ **trong bộ nhớ** → không biết giá trị **tại một thời điểm trong quá khứ**. Swap đổi theo lãi suất; đòn bẩy / stops level có thể đổi theo broker. GĐ5 (RSK-03/08/09, RSK-11), GĐ6 (chi phí qua đêm), GĐ9 (đối soát) cần giá trị **đã biết lúc đó**.

## 2. Bảng (chỉ thêm, trigger chặn UPDATE / DELETE)

| Bảng | Ghi khi | Khóa |
| --- | --- | --- |
| `broker_spec_history` | thông số **khác** dòng gần nhất cùng (tài khoản, login MT5, server, mã broker) — A → B → A ghi 3 dòng | `seq`; tra `(account_id, broker_symbol, observed_at)` |
| `account_equity_hourly` | nhịp tim **đầu tiên** của mỗi giờ UTC | `(account_id, login, server, giờ)` |

`observed_at` = lúc backend nhận nhịp tim = lúc hệ thống **đã biết** (point-in-time). Đòn bẩy + tiền tài khoản đi cùng thông số (đổi đòn bẩy = một dòng mới).

## 3. Quy tắc an toàn

- `None` = Gateway không đọc được → lưu `NULL`, **không** đổi thành 0. `NULL` → số là một thay đổi, được ghi.
- **Không có phí commission:** MT5 không cung cấp qua `symbol_info` → không có trường, không đoán (RSK-11 phải lấy từ nguồn khác / nhập tay).
- Chỉ ghi khi nhịp tim có **danh tính MT5** do terminal báo (`identity`) và không ở pha `STARTING`.
- Lỗi ghi (DB / giá trị sai) **không** làm hỏng nhịp tim: ghi log, mất một điểm lịch sử.
- CHECK: `point`, `contract_size`, bước / min khối lượng > 0, max ≥ min; đòn bẩy > 0; margin ≥ 0. Kho SQL không nuốt lỗi CHECK (chỉ coi "đã có" khi dòng của giờ đó thật sự tồn tại).
- Thời điểm không múi giờ / lùi về trước dòng đã ghi → từ chối.

## 4. Đọc

`spec_at(tài khoản, mã broker, at)` → dòng mới nhất có `observed_at ≤ at` (hoặc `None` — không đoán trước lúc bắt đầu lưu). `equity_rows(tài khoản)`.

## 5. Giới hạn

- Chỉ có lịch sử **từ lúc dựng bản này** — quá khứ trước đó không lấy lại được.
- Khóa tuần tự trong một tiến trình: nhiều tiến trình backend cùng lúc có thể ghi hai dòng giống nhau liền nhau (vô hại khi đọc).
- Equity theo giờ là **mẫu** đầu giờ, không phải thấp nhất trong giờ (sụt giảm trong giờ cần GĐ9 đối soát).
