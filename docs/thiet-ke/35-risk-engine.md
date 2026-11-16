# 35 — Risk Engine: tự đọc cổng thật + khối lượng theo thông số thật (RSK-10, RSK-11)

> 2026-11-16 · GĐ5 bước 0–2 (kế hoạch [`GD5-ke-hoach.md`](../ke-hoach/GD5-ke-hoach.md), người dùng duyệt 16/11, Q1–Q5 đã chốt). Đặc tả: `docs/huong-dan-chuc-nang/07-risk-engine-va-ledger.md`. Mã: `risk/engine.py`, `risk/gates.py`, `risk/sizing.py`, `storage/commissions.py`.
>
> **Không có lệnh thật nào.** Risk chỉ ra quyết định (`RiskDecision`) + giữ chỗ ngân sách trong sổ paper. **Không có số rủi ro nào do người phát triển đặt:** `RiskPolicy` không còn số mặc định (0,5 % / 2 % cũ đã bỏ); số đến từ hồ sơ rủi ro người dùng chọn ở bước 3 (H1–H11). Ở bước 0–2, test dùng số giả ghi rõ "chỉ để test".

## 1. Ý tưởng

1. **Risk tự đi hỏi, không tin bên gọi.** Bên gọi chỉ đưa `TradeIntent` + `account_id`. Mọi thứ khác (Safety, khóa người dùng, lệnh cấm làn nhanh, chế độ, MarketView hiện hành, sức khỏe nguồn lịch, thông số broker, equity, spread, phí) Risk tự đọc **tại lúc quyết** qua các cổng (`RiskGates`).
2. **Thiếu / cũ / lỗi đọc → `REJECTED` có lý do.** Một cổng ném lỗi → `GATE_READ_ERROR:<cổng>`; không ném lên người gọi, không cho qua.
3. **Rủi ro thật (gồm chi phí) ≤ mức được duyệt.** Khối lượng làm tròn **xuống**, không bao giờ lên.
4. **Tiền / rủi ro tính bằng `Decimal`** (CORE-05). Số thực từ broker / Gateway đổi qua `Decimal(str(x))` (giữ đúng số thập phân đã báo).

## 2. Luồng quyết định

`RiskEngine.evaluate(intent, account_id) → RiskDecision`, `now` lấy từ đồng hồ của Risk (không do bên gọi đưa).

**Pha A — cổng (gom mọi lý do, mỗi cổng đọc trong `try`):**

| # | Kiểm | Đọc từ | Mã từ chối |
| --- | --- | --- | --- |
| A1 | Cổng tài khoản: tài khoản tồn tại, Safety ACTIVE, chủ tài khoản không bị khóa (DEC-16), **không còn lệnh cấm làn nhanh** (DEC-20) | `AccountRegistry.entry_denials(tài khoản, now)` | `ACCOUNT_UNKNOWN`, `SAFETY_<trạng thái>`, `ACCOUNT_LOCKED`, `ENTRY_BLOCKED:<mã lệnh cấm>` |
| A2 | Chế độ của tài khoản (không do bên gọi khai) + cờ chất lượng MarketView theo chế độ (DEC-25) | `AccountRegistry` (ModeManager) | `MODE_UNKNOWN`, `QUALITY_FLAGS_<chế độ>:…` |
| A3 | Intent còn hạn | intent | `INTENT_EXPIRED` |
| A4 | MarketView **hiện hành** của đúng nguồn giá của tài khoản; id khớp intent; mã khớp | `MarketViewStore.current(phạm vi của tài khoản, now)` | `NO_PRICE_FEED`, `NO_MARKET_VIEW` (không có / hết hạn / bị vô hiệu), `MARKET_VIEW_MISMATCH`, `SYMBOL_MISMATCH` |
| A5 | Cờ rủi ro của MarketView | MarketView hiện hành | `RISK_FLAGS:…` |
| A6 | Sức khỏe nguồn lịch (Q1) | nhật ký kiểm nguồn (ING-30) | `CALENDAR_SOURCE_UNHEALTHY:<nguồn>`, `CALENDAR_HEALTH_UNKNOWN` |
| A7 | Nhịp tim Gateway + equity (2b) | `GatewayMonitors` | `EQUITY_STALE`, `NO_EQUITY` |
| A8 | Thông số broker tại lúc quyết (2a) | `spec_at` (KN-05) + nhịp tim hiện tại | `BROKER_SPEC_MISSING:<trường>`, `BROKER_SPEC_STALE`, `CURRENCY_UNSUPPORTED` |
| A9 | Giá hiện tại + spread (2d) | giá theo giây (ING-08) | `QUOTE_STALE`, `MARKET_CLOSED` |
| A10 | Nền spread 30 ngày (2c, 2d) | spread theo phút (KN-03) | `SPREAD_BASELINE_MISSING`, `SPREAD_TOO_WIDE` |
| A11 | Phí hoa hồng / lot (2c, Q3) | `CommissionStore` | `COMMISSION_UNKNOWN` |
| A12 | SL quá gần (2e, RSK-08) | thông số + spread | `SL_TOO_CLOSE` |

Có lý do nào → `REJECTED` (kèm `details` để audit), không giữ chỗ ngân sách.

**Pha B — khối lượng (dưới `ledger.lock`, mục 4).** Dưới lot tối thiểu → `BELOW_MIN_VOLUME` (5-C01).

Ghi chú RSK-01 (cũ): "Kiểm Safety" trước đây chỉ hỏi `SafetySupervisor.allows_new_orders()` (chỉ xét ACTIVE) → **không thấy** lệnh cấm làn nhanh. Từ RSK-10, Risk không nhận `SafetySupervisor` nữa.

## 3. Nguồn của từng số

| Số | Nguồn | Loại |
| --- | --- | --- |
| Cỡ hợp đồng, point, lot min / max / bước, stops level, freeze level, tiền lợi nhuận, tiền tài khoản | `broker_spec_history` (`spec_at`, KN-05) — phải **trùng** thông số trong nhịp tim hiện tại | broker thật |
| Equity, tiền tài khoản | nhịp tim Gateway mới nhất (`AccountSnapshot`) | broker thật |
| Spread hiện tại | giây giá mới nhất của nguồn giá: `max(spread_points, spread_max_points)` | broker thật |
| Đệm trượt giá **và** ngưỡng spread quá rộng | p95 (hạng gần nhất) của `spread_p95` theo phút, 30 ngày trước `now`, chỉ phút thị trường mở (Q4, Q5) | **giá trị khởi đầu chưa hiệu chỉnh — proxy, không phải trượt giá đo được**; đo lại bằng deal thật ở GĐ9 (sổ tham số KN-08) |
| Phí hoa hồng khứ hồi / lot | người dùng nhập theo trang của sàn (Q3), có phiên bản | người dùng |
| Mức rủi ro / lệnh, trần tổng giữ chỗ | `RiskPolicy` — **không có mặc định**; bước 3 thay bằng hồ sơ rủi ro | người dùng (H1, H3) |

Hằng số kỹ thuật (giá trị khởi đầu chưa hiệu chỉnh, vào sổ tham số KN-08 ở bước 9):

| Hằng | Giá trị | Lý do |
| --- | --- | --- |
| `EQUITY_MAX_AGE` | 30 giây | bằng `HEARTBEAT_TIMEOUT` (quá 30 giây Gateway đã bị coi là mất kết nối) |
| `QUOTE_MAX_AGE` | 10 giây | bằng ngân sách độ trễ làn nhanh (GĐ2 4d) — giá cũ hơn không phản ánh spread lúc vào |
| `BASELINE_WINDOW` | 30 ngày | Q4 / Q5 |
| `BASELINE_MIN_MINUTES` | 6.900 phút | ≈ 5 ngày giao dịch × 23 giờ × 60 phút: đủ một vòng các phiên trong tuần. Ít hơn → `SPREAD_BASELINE_MISSING` (không đoán) |
| Ngưỡng "quá hạn" nguồn lịch | `fetch_ttl` sẵn có của từng nguồn (ING-30) | Q1: dùng chu kỳ nạp sẵn có |

## 4. Đơn vị + công thức (tài liệu Quản lý vốn mục 5.2 + 3.5)

Đơn vị giá: USD / oz (đơn vị của giá XAUUSD). `point` = bước giá nhỏ nhất của broker (vd. 0,01). Spread lưu theo **point** → đổi ra giá: `× point`.

Q2: chỉ tính khi **tài khoản USD** (cả trong thông số và trong nhịp tim) **và** tiền lợi nhuận của mã = USD → giá trị 1 đơn vị giá / lot = **cỡ hợp đồng thật** (USD). Khác (USC, EUR…) hoặc `NULL` → `CURRENCY_UNSUPPORTED`.

```
khoảng SL       D  = |vào − SL|                       (giá)
spread hiện tại S  = spread_points_now × point         (giá)
đệm trượt giá   B  = p95_30 ngày × point               (giá)
khoảng SL thực  Dt = D + S + B
rủi ro / lot    R1 = Dt × cỡ hợp đồng + phí khứ hồi / lot          (USD)
tiền rủi ro     M  = min(mức xin, mức tối đa) × equity, cắt theo chỗ trống của trần tổng
lot             V  = floor(M / R1 theo bước lot) × bước lot; V > max → max (làm tròn xuống theo bước)
V < min         → REJECTED BELOW_MIN_VOLUME, kèm: thiếu = min × R1 − M (USD);
                  vốn tối thiểu = min × R1 / mức rủi ro
rủi ro thật     = V × R1 ≤ M           (bất biến, kiểm bằng test ngẫu nhiên)
```

SL quá gần (2e): `D < max(max(stops_level, freeze_level) × point, S)` → `SL_TOO_CLOSE`. `stops_level` / `freeze_level` `NULL` → **chưa biết** → `BROKER_SPEC_MISSING` (không coi là 0). SL quá xa → R1 lớn → rơi vào `BELOW_MIN_VOLUME`.

Spread quá rộng (2d): `spread_points_now > p95_30 ngày` → `SPREAD_TOO_WIDE` (details ghi cả hai số). Độc lập với băng chặn làn nhanh (> 3 × trung vị 60 phút, DEC-20) — hai lớp.

`REDUCED` khi mức xin bị cắt (vượt mức tối đa / chỗ trống) hoặc lot bị cắt về max (mã `REDUCED_TO_LIMIT`). Lot làm tròn xuống theo bước **không** tính là REDUCED (rủi ro thật < mức xin là bình thường).

## 5. Bảng tính tay (test `test_risk_sizing.py`)

Mức rủi ro trong bảng là **số chỉ để test**, không phải số khuyến nghị.

| Ca | Tiền rủi ro M | D | S | B | cỡ HĐ | phí / lot | bước | R1 | lot | rủi ro thật |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| QLV 5.2 (chưa chi phí) | 100 | 5,0 | 0 | 0 | 100 | 0 | 0,01 | 500 | **0,20** | 100,0 |
| QLV 5.2 (có spread + đệm) | 100 | 5,0 | 0,3 | 0,5 | 100 | 0 | 0,01 | 580 | **0,17** | **98,6** |
| QLV 11.2 | 40 | 18,0 | 0,3 | 0,5 | 100 | 0 | 0,01 | 1.880 | **0,02** | **37,6** |
| 1 lot = 10 oz | 50 | 10,0 | 0,2 | 0,3 | 10 | 0 | 0,01 | 105 | 0,47 | 49,35 |
| 1 lot = 1 oz, bước 0,1 | 50 | 10,0 | 0,2 | 0,3 | 1 | 0 | 0,1 | 10,5 | 4,7 | 49,35 |
| Có phí (5-C16) | 100 | 5,0 | 0,3 | 0,5 | 100 | 7 | 0,01 | 587 | 0,17 | 99,79 |
| Vốn nhỏ (5-C01): equity 1.000 × 0,5 % | 5 | 10,0 | 0,2 | 0,3 | 100 | 0 | 0,01 | 1.050 | < 0,01 → **từ chối**, thiếu 5,50 USD, vốn tối thiểu 2.100 USD | — |

Ghi chú: đầu vào của hai ca QLV được **dựng lại từ kết quả** trong tài liệu (0,20 / 0,17 lot / 98,6 USD; 0,02 lot / 37,6 USD) vì bản tài liệu không nằm trong kho mã — kết quả khớp, đầu vào cần đối chiếu với tài liệu gốc khi người dùng gửi lại bản chữ.

## 6. Cổng đọc (`risk/gates.py`)

`RiskGates` gom các cổng; bản thật `live_gates(...)` dựng từ các thành phần của `create_app` (`AccountRegistry`, `MarketViewStore`, `FusionRunner.scope`, `account_feed`, `GatewayMonitors`, `BrokerHistoryStore`, `QuoteStore`, `QuoteMinuteStore`, nhật ký kiểm nguồn, `CommissionStore`). Risk **chưa nằm trong luồng thật nào** (nối Strategy → Risk ở bước 7).

- Phạm vi MarketView của tài khoản = nguồn giá tài khoản (`account_feed`, MT-05) + (mã, khung, nguồn dữ liệu) của Fusion. Không có nguồn giá → `NO_PRICE_FEED` (không lấy nguồn của tài khoản khác).
- Thông số broker: mã broker lấy từ **nguồn giá đã khóa** của tài khoản; nhịp tim phải cùng mã broker, cùng danh tính MT5 (login, server) với dòng `spec_at`, và **cùng mã băm thông số** → nếu khác (DB chưa kịp ghi thông số mới / Gateway đổi MT5) → `BROKER_SPEC_STALE`.
- Sức khỏe nguồn lịch (Q1): mọi nguồn lịch (`fed_fomc`, `bea_schedule`, `dol_claims_schedule`, `bls_schedule`) phải `HEALTHY` **và** lần nạp gần nhất không lỗi (`failures_since_ok = 0`). Một nguồn chưa từng chạy cũng là không khỏe (không biết lịch của nó → không biết có tin sắp ra). Chấp nhận có thể từ chối nhầm khi trang lịch chập chờn (người dùng chốt Q1).

## 7. Phí hoa hồng (Q3) — `account_commissions` (migration 0024)

Bảng chỉ-thêm (trigger chặn UPDATE / DELETE), mỗi tài khoản một chuỗi phiên bản: `commission_per_lot` (USD, khứ hồi, ≥ 0, `NUMERIC`), ai nhập, lúc nào, lý do. Risk đọc bản mới nhất có `created_at ≤ now`; chưa có → `COMMISSION_UNKNOWN`. 0 chỉ khi người dùng nhập 0. Cách nhập (trang Rủi ro) làm ở bước 8; tới lúc đó mọi intent bị từ chối `COMMISSION_UNKNOWN` (mặc định an toàn).

## 8. Giới hạn còn lại (sau bước 2)

- Chưa có hồ sơ rủi ro (bước 3), hạn mức ngày / tuần (bước 4), margin + swap (bước 5), sổ cái bền (bước 6). Sổ giữ chỗ vẫn trong bộ nhớ.
- Đệm trượt giá là proxy từ spread, không phải trượt giá đo được; không che được trượt giá lúc ra tin (đã chặn vào lệnh quanh tin — DEC-20).
- Chỉ tài khoản USD (Q2); tài khoản cent / tiền khác chờ giá trị tick từ Gateway khi chọn sàn thật.
