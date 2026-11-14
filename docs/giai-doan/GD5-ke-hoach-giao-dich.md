# GĐ5 — Kế hoạch giao dịch: hồ sơ rủi ro + chiến lược + Risk Engine + Ledger (đặc tả 06, 07)

> Một phần của bản đồ việc theo giai đoạn (tách từ `CHECKLIST.md` 2026-11-06). Chỉ mục, nguyên tắc và bất biến: [`README.md`](README.md). Trạng thái chung: `PROGRESS.md`. Ghi chú kỹ thuật: `docs/ghi-chu-ky-thuat.md`.


### 5A — Hồ sơ rủi ro (việc ③b)

| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| DEC-09 | Người dùng trả lời: vốn; mục tiêu 4–5% theo ngày/tuần/tháng; lỗ tối đa mỗi lệnh; ngưỡng dừng ngày/tuần; giữ lệnh trong ngày hay qua đêm; broker, đòn bẩy, phí | `[~]` | **Nguyên tắc đã chốt 2026-11-14 (người dùng):** khi mục tiêu lợi nhuận mâu thuẫn rủi ro → **ưu tiên rủi ro mỗi lệnh**: luật cứng của Risk Engine là rủi ro **0,25–0,5 % vốn / lệnh** + ngưỡng lỗ ngày / tuần; mục tiêu 4–5 %/ngày **chỉ là con số tham khảo**, không bao giờ dùng để nới rủi ro, tăng lot hay ép hệ thống vào lệnh. Con số cụ thể (mức trong khoảng 0,25–0,5 %, ngưỡng dừng, giữ qua đêm…) và các chương áp dụng từ tài liệu "Quản lý vốn khi trade vàng" chốt khi người dùng gửi lại tài liệu (chưa có trong repo) — tại GĐ5 |
| DB-07 | Bảng hồ sơ rủi ro có phiên bản | `[ ]` | |
| RPF-01 | Hồ sơ rủi ro có phiên bản (append-only, audit) | `[!]` | ← DEC-09 |
| RPF-02 | Đề xuất SL theo ATR, TP theo R:R, lot theo rủi ro, thời gian giữ lệnh ước tính | `[ ]` | Lot làm tròn **xuống**; < tối thiểu → **không khả thi** |
| RPF-03 | Kết luận khả thi bằng số cụ thể | `[ ]` | Ví dụ: vốn 100$, ATR ~13$, lot 0,01 → SL 1,5 ATR mất ~20% vốn |
| RPF-04 | Nhãn "chỉ minh họa" khi SAMPLE | `[ ]` | |
| RPF-05 | Trang nhập hồ sơ và xem kế hoạch | `[ ]` | Thuộc trang Rủi ro (DSH-05) |

### 5B — Chiến lược (Strategy Engine)

| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| STR-06 | **Văn bản chiến lược v1** được người dùng duyệt: điều kiện vào/ra, phiên giao dịch, cửa sổ cấm, SL/TP, BE, trailing, time-stop, số lệnh tối đa | `[ ]` | `docs/thiet-ke/` |
| STR-01 | Contract `TradeIntent` (SL/TP đúng chiều lệnh) | `[x]` | `contracts/trade_intent.py` |
| STR-02 | Điều kiện vào: MarketView còn hạn, confidence đạt ngưỡng theo regime, không có riskFlags cấm | `[ ]` | `strategy/` |
| STR-03 | Sinh intent: entry, SL, TP, `riskBudgetRequested`, `expiry`, `idempotencyKey` | `[ ]` | Không tự suy volume cuối |
| STR-04 | Chống intent trùng cho cùng strategy/symbol/horizon | `[ ]` | |
| STR-05 | Audit, gửi Risk, ghi lý do khi bị từ chối | `[ ]` | |

### 5C — Risk Engine

| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| CORE-05 | Tiền/PnL dùng `Decimal` | `[ ]` | Bắt buộc trước LED-04 |
| RSK-01 | Kiểm Safety, hết hạn intent/MarketView, riskFlags, spread | `[x]` | `risk/engine.py` |
| RSK-02 | Sizing theo rủi ro, volume step/min/max, hạn mức tổng (giữ `ledger.lock`) | `[x]` | |
| RSK-03 | Margin/đòn bẩy | `[ ]` | ← GW-09 |
| RSK-04 | Exposure ròng/gộp, tập trung | `[ ]` | |
| RSK-05 | Hạn mức ngày/tuần, drawdown, chuỗi thua | `[ ]` | ← RPF-01 |
| RSK-06 | Kết quả `REDUCED`, TTL quyết định, gắn policy version | `[ ]` | |
| RSK-07 | Đọc `EVENT_WINDOW`, `WIDE_SPREAD`, `HIGH_VOLATILITY` từ MarketView thật | `[ ]` | |
| RSK-08 | Stops level / freeze level của broker: SL quá gần → từ chối | `[ ]` | ← GW-09 |
| RSK-09 | Ước tính swap qua đêm (thứ Tư ×3) và commission vào rủi ro | `[ ]` | |

### 5D — Risk Ledger (bản paper)

| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| LED-01 | Reserve/release append-only trong bộ nhớ, test đồng thời | `[x]` | `risk/ledger.py` |
| DB-06 | Bảng lệnh, deal, vị thế, reservation | `[ ]` | |
| LED-02 | Lưu ledger vào DB (`PortfolioState`, `RiskReservation`) | `[ ]` | |
| LED-04 | Fill/đóng lệnh → exposure và PnL (Decimal) | `[ ]` | |
| LED-05 | Khôi phục sau crash giữa reserve và gửi lệnh | `[ ]` | |
| DSH-05 | Trang Rủi ro (hồ sơ, hạn mức, mức đã dùng) | `[ ]` | |

| Mã | Tình huống | Hành vi bắt buộc | TT |
| --- | --- | --- | --- |
| 5-C01 | Vốn quá nhỏ: lot tối thiểu vẫn vượt rủi ro cho phép | **Từ chối**, nói rõ số tiền thiếu; không làm tròn lên | `[ ]` |
| 5-C02 | SL quá gần (< spread hoặc < stops level) / quá xa | Từ chối | `[ ]` |
| 5-C03 | Tín hiệu ngược chiều khi đang có lệnh | Theo văn bản chiến lược (không tự đảo lệnh nếu chưa định nghĩa) | `[ ]` |
| 5-C04 | Nhiều tín hiệu liên tiếp / trùng | Chống trùng, giới hạn số lệnh | `[ ]` |
| 5-C05 | Chạm ngưỡng lỗ ngày/tuần | Chặn lệnh mới tới kỳ sau; Safety PAUSED | `[ ]` |
| 5-C06 | Chuỗi thua liên tiếp | Giảm rủi ro hoặc dừng theo chính sách | `[ ]` |
| 5-C07 | Giữ lệnh qua cuối tuần (gap qua SL) | Theo chính sách: cấm hoặc tính rủi ro gap | `[ ]` |
| 5-C08 | Swap qua đêm, thứ Tư ×3 | Tính vào chi phí | `[ ]` |
| 5-C09 | Margin không đủ / đòn bẩy bị broker đổi | Từ chối / giảm khối lượng | `[ ]` |
| 5-C10 | Spread giãn lúc vào / đang trong cửa sổ tin | Từ chối | `[~]` (spread) |
| 5-C11 | Intent hoặc MarketView hết hạn | Từ chối | `[x]` |
| 5-C12 | Hai intent đồng thời tiêu cùng ngân sách | Tổng không vượt hạn mức | `[x]` |
| 5-C13 | Equity đổi giữa lúc tính và lúc duyệt | Tính lại dưới khóa | `[~]` |

**Gate GĐ5:** người dùng duyệt hồ sơ rủi ro (DEC-09) và văn bản chiến lược (STR-06); mọi case có test; báo cáo khả thi trên dữ liệu thật.
