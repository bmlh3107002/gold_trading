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

## 9. Hồ sơ rủi ro có phiên bản (bước 3 — DB-07, RPF-01; DEC-09, KN-12, Q6)

Mã: `storage/risk_profiles.py`, migration **0025** (`risk_profiles`, chỉ thêm, trigger chặn UPDATE / DELETE).

**Trường** (một dòng = một phiên bản; số tỷ lệ là `NUMERIC`, đọc ra `Decimal`):

| Trường | Ý nghĩa | Bản v1 người dùng chốt 16/11 | Kiểm hợp lệ cứng |
| --- | --- | --- | --- |
| `risk_per_trade` | rủi ro thật / lệnh (gồm chi phí) | 0,0025 (H1) | **[0,0025; 0,005]** — DEC-09; CHECK cả trong DB |
| `min_reward_risk` | R:R tối thiểu sau chi phí | 1,5 (H2) | [1; 10] |
| `max_open_risk` | heat — tổng rủi ro mở + giữ chỗ | 0,005 (H3) | ≥ `risk_per_trade`, ≤ 0,05 |
| `max_daily_loss` / `max_weekly_loss` / `max_monthly_loss` | lỗ tối đa | 0,0075 / 0,015 / 0,03 (H4) | `risk_per_trade` ≤ ngày ≤ tuần ≤ tháng ≤ 0,2 |
| `max_consecutive_losses` | chuỗi thua → PAUSED | 5 (H4) | 1–50 |
| `day_reset_tz`, `day_reset_time` | mốc ngày giao dịch | `America/New_York`, 17:00 (H4) | múi giờ IANA có thật; `HH:MM` |
| `max_trades_per_day` | lệnh mới / ngày | 4 (H5) | 1–100 |
| `max_drawdown_halt` | dừng hẳn khi sụt từ đỉnh | 0,05 (H6) | (0; 0,5]¹ |
| `news_hold_policy` | lệnh mở qua tin HIGH | `KEEP_SAFE_ONLY` (H7) | `CLOSE_ALL` / `KEEP_SAFE_ONLY` |
| `weekend_policy`, `weekend_close_before_min` | cuối tuần / lễ dài | `CLOSE_ALL`, 30 (H8) | chỉ `CLOSE_ALL` (cho giữ cần cách tính gap — chưa có); 5–240 phút |
| `max_effective_leverage` | đòn bẩy thực tế | 3 (H9) | (0; 30] |
| `cash_flow_policy` | nạp / rút | `SEPARATE` (H10) | chỉ `SEPARATE` |
| `pyramiding_policy` | thêm lệnh cùng chiều | `ONLY_IF_ALL_IN_PROFIT` (H11) | `NONE` / `ONLY_IF_ALL_SAFE` / `ONLY_IF_ALL_IN_PROFIT` |
| `notes` | ghi chú (vốn rủi ro, mục tiêu — **không** vào phép tính nào) | — | ≤ 1000 ký tự |
| `version`, `created_at`, `created_by`, `reason` | phiên bản tăng dần / tài khoản, ai, lúc nào, vì sao | — | duy nhất `(account_id, version)` |

¹ Không ép `max_drawdown_halt` lớn hơn lỗ tháng (hai giới hạn độc lập).

Chính sách chỉ cho các giá trị **đã có cách thực thi an toàn**; giá trị "cho giữ / không chặn" (vd. `KEEP` qua tin, giữ qua cuối tuần, `ALLOW` nhồi lệnh) **không** có trong danh sách — muốn thêm phải có quyết định mới + cách tính rủi ro.

**Ai được tạo (Q6 = B):** chỉ **chủ tài khoản** (`account_members.role = OWNER`), người dùng đang `ACTIVE`, không phải ADMIN (`accounts.access.decide`). Hiệu lực ngay (kể cả nới), mỗi lần là một phiên bản mới; không sửa / xóa bản cũ. Giới hạn DEC-09 do hệ thống chặn, không ai vượt được.

**Risk đọc:** hồ sơ mới nhất có `created_at ≤ now`. Không có → `NO_RISK_PROFILE` (mọi intent bị từ chối). Đọc một lần ở pha A (để ghi lý do) và **đọc lại dưới `ledger.lock`** ngay trước khi tính khối lượng (5-C13): khác phiên bản → dùng bản mới, ghi `details.profile_reread`. Quyết định ghi `risk_profile_version`. `RiskPolicy` không còn số rủi ro: `min(mức xin, risk_per_trade)` và trần giữ chỗ `max_open_risk × equity` lấy từ hồ sơ. Các trường còn lại (R:R, lỗ ngày…, chính sách tin / cuối tuần / nhồi lệnh, đòn bẩy) **lưu ở bước 3, thực thi ở bước 4–5**.

**Cách nhập:** trang Rủi ro (bước 8, API chỉ chủ tài khoản). Trước đó hồ sơ chưa có trên máy người dùng → Risk từ chối hết (an toàn; Risk cũng chưa nối luồng nào).

## 10. Bước 4 — hạn mức theo thời gian + danh mục (RSK-04, RSK-05, RSK-06)

Chia nhỏ, làm + kiểm từng phần:

| Phần | Nội dung | Phụ thuộc |
| --- | --- | --- |
| **4a** | Mốc kỳ giao dịch (`risk/periods.py`): ngày = [mốc hôm trước; mốc hôm nay) theo `day_reset_tz` + `day_reset_time` (H4: 17:00 New York); tuần bắt đầu ở mốc **Chủ nhật** (17:00 NY CN, trước giờ mở cửa 18:00); tháng bắt đầu ở mốc của **ngày trước ngày 1** (ngày giao dịch đầu tháng). Tự theo DST (đổi giờ Mỹ khác châu Âu). | hồ sơ |
| **4b** | R:R tối thiểu sau chi phí (H2): `lời / lot = (|TP − vào| − spread) × cỡ HĐ − phí`; `R:R = lời / R1` (R1 = rủi ro / lot RSK-11). `< min_reward_risk` → `REWARD_RISK_TOO_LOW`. Intent **không có TP** → `NO_TAKE_PROFIT` (không tính được R:R → chặn; chiến lược v1 luôn đặt TP). | RSK-11 |
| **4c** | Cổng **sổ lệnh** (`TradeBook`: lệnh đã đóng có PnL ròng, lệnh đang mở có giá vào / SL / lot / chiều) + luật: lỗ ngày / tuần / tháng (H4), chuỗi thua (H4), số lệnh / ngày (H5), heat gồm lệnh đang mở (H3), nhồi lệnh (H11). Chạm lỗ ngày / tuần / tháng / chuỗi → từ chối + **đề nghị Safety PAUSED** (chỉ người mở lại); đủ số lệnh / ngày → chỉ từ chối. | sổ lệnh |

**Sổ lệnh thật chưa có** (sổ cái paper là bước 6). Tới lúc đó cổng sổ lệnh thật = "không có" → Risk từ chối `TRADE_BOOK_UNAVAILABLE` (mặc định an toàn; Risk cũng chưa nối luồng nào). Bước 6 hiện thực đúng giao diện này.

**Quy ước tính (4c):**

- Lỗ kỳ = PnL ròng (đã gồm phí) của lệnh **đóng trong kỳ** + PnL **đang chạy** của lệnh mở (đánh giá theo giá đóng lệnh hiện tại: bid cho BUY, ask cho SELL, trừ phí). Tỷ lệ = lỗ / equity lúc quyết (nhịp tim). Lỗ ≥ ngưỡng → chặn (`DAILY_LOSS_LIMIT`, `WEEKLY_LOSS_LIMIT`, `MONTHLY_LOSS_LIMIT`).
- Chuỗi thua = số lệnh đóng gần nhất liên tiếp có PnL ròng < 0 (hòa = ngắt chuỗi? **không** — hòa không phải thắng, không ngắt; chỉ lệnh lời ngắt). ≥ `max_consecutive_losses` → `LOSS_STREAK_LIMIT` + đề nghị PAUSED.
- Số lệnh / ngày = lệnh mở trong ngày (đang mở hoặc đã đóng) + giữ chỗ đang mở; ≥ `max_trades_per_day` → `DAILY_TRADE_LIMIT` (không PAUSED).
- Heat = Σ rủi ro thật còn lại của lệnh mở (tới SL hiện tại, gồm chi phí; lệnh SL đã qua hòa vốn = 0) + giữ chỗ đang mở ≤ `max_open_risk` × equity.
- Nhồi lệnh (H11, `ONLY_IF_ALL_IN_PROFIT`): có lệnh **cùng chiều** đang mở mà PnL đang chạy (sau phí) ≤ 0 → `NO_AVERAGING_DOWN`. Không đọc được giá → chặn.
- Đề nghị PAUSED qua `AccountRegistry` (Safety có quyền cao nhất; Risk không bao giờ tự mở lại). Đã PAUSED thì không ghi thêm.

**Hoãn sang bước 6 (cần đường equity của sổ cái):** H6 dừng hẳn khi sụt 5 % từ đỉnh và H10 điều chỉnh đỉnh khi nạp / rút — đỉnh equity phải là của sổ cái (paper khác equity MT5). Ghi ở kế hoạch; không làm dở.

## 11. Bước 5 — đòn bẩy, ký quỹ, swap, cuối tuần (RSK-03, RSK-09; H8, H9; 5-C07, 5-C08, 5-C09)

Chia **5a** (đòn bẩy thực tế + ký quỹ), **5b** (swap), **5c** (chặn vào lệnh trước cuối tuần / lễ dài).

**5a — giới hạn khối lượng thêm** (sau khi tính lot theo rủi ro, làm tròn xuống theo bước; nhỏ hơn lot tối thiểu → từ chối):

- Đòn bẩy thực tế (H9): `Σ lot mở × cỡ HĐ × giá + lot mới × cỡ HĐ × giá ≤ max_effective_leverage × equity`. Giá = giá đóng hiện tại của lệnh mở (bid cho BUY, ask cho SELL) và giá vào của lệnh mới (ask cho BUY, bid cho SELL). Cắt → `REDUCED_BY_LEVERAGE`; không đủ lot tối thiểu → `LEVERAGE_LIMIT`.
- Ký quỹ (RSK-03, 5-C09): ký quỹ / lot ≈ cỡ HĐ × giá / đòn bẩy tài khoản (đòn bẩy trong thông số `spec_at`, phải trùng nhịp tim). Ký quỹ của lệnh mới + ký quỹ ước tính của lệnh paper đang mở ≤ `margin_free` trong nhịp tim (paper không làm đổi số MT5 → phải tự trừ). Cắt → `REDUCED_BY_MARGIN`; không đủ → `INSUFFICIENT_MARGIN`. `margin_free` / đòn bẩy `NULL` → từ chối (`MARGIN_UNKNOWN`, `BROKER_SPEC_MISSING:leverage`). **Ước tính** theo kiểu tính ký quỹ CFD-đòn bẩy; sàn có thể tính khác (hệ số ký quỹ) — GĐ9 dùng `order_calc_margin` của MT5 qua Gateway. Với trần đòn bẩy thực tế 3 lần và đòn bẩy sàn 1:100, ký quỹ cần ≤ 3 % equity nên hiếm khi là giới hạn chặn. Đòn bẩy sàn đổi → dùng giá trị tại lúc quyết (KN-05).

**5b — swap qua đêm** (RSK-09, 5-C08): lệnh có thể còn mở qua **lần chốt ngày kế tiếp** (17:00 NY, mốc ngày của hồ sơ) → cộng chi phí swap **một đêm** (nhân 3 nếu đêm đó là `swap_rollover3days`, đánh số MT5: 0 = Chủ nhật … 3 = thứ Tư) vào **rủi ro / lot** và trừ khỏi **lời / lot** (R:R). Swap dương (được nhận) → 0, không tính là lời. Kiểu swap hỗ trợ: `0` (không swap), `1` (theo point: `−swap × point × cỡ HĐ` / lot), `4` (tiền gửi = USD / lot); kiểu khác → `SWAP_MODE_UNSUPPORTED` (không biết chi phí → không vào lệnh). "Một đêm" là giá trị khởi đầu chưa hiệu chỉnh; chiến lược v1 (STR-06) có time-stop → xét lại. Cuối tuần không có swap vì H8 đóng hết trước thứ Sáu.

**5c — cuối tuần / lễ dài (H8, 5-C07):** nếu trong `weekend_close_before_min` phút tới (30) thị trường chuyển sang `WEEKEND` hoặc `HOLIDAY` (lịch thị trường + bảng ngày lễ + giờ đặc biệt broker) → `WEEKEND_CLOSE_WINDOW`. Bảng ngày lễ không phủ năm đó → `MARKET_CALENDAR_UNKNOWN` (mặc định an toàn). Nghỉ hằng ngày 17–18 NY không chặn. **Đóng lệnh đang mở trước cuối tuần (H8) và quy tắc giữ lệnh qua tin (H7) là quản lý lệnh đang mở → bước 6** (sổ cái paper); bước 5 chỉ chặn vào lệnh mới.

## 12. Bước 6 — sổ cái paper bền vững (DB-06, LED-02, LED-04, LED-05, CORE-05; H6, H7, H8, H10)

> Viết 16/11 trước khi code. **Không có lệnh thật**: "khớp" chỉ là giả lập trong sổ cái paper; không có đường nào tới Gateway gửi lệnh. Sổ cái chưa nối luồng thật nào (Strategy → Risk → sổ cái ở bước 7).

Chia nhỏ, làm + kiểm từng phần:

| Phần | Nội dung | Mã việc |
| --- | --- | --- |
| **6a** | Sổ cái chỉ-thêm trong DB (migration **0026**) + bản bộ nhớ cùng giao diện; giữ chỗ **theo tài khoản**; khóa theo tài khoản ở DB; quyết định Risk lưu bền + `idempotency_key` (trùng → một luồng); khôi phục sau crash | DB-06, LED-02, LED-05 (phần giữ chỗ), CORE-05 |
| **6b** | "Khớp" paper (giá ask / bid thật + đệm trượt giá) → vị thế; đóng khi chạm SL / TP theo giây giá **đã biết**; PnL ròng `Decimal` (phí, swap); sổ cái hiện thực `TradeBook` → Risk hết `TRADE_BOOK_UNAVAILABLE` | LED-04 |
| **6c** | Equity paper + đỉnh: H6 dừng hẳn khi sụt từ đỉnh; H10 nạp / rút tách khỏi lãi lỗ, điều chỉnh đỉnh | RSK-05 (phần hoãn) |
| **6d** | Quản lý lệnh đang mở (`PaperMonitor.tick`): H8 đóng hết trước cuối tuần / lễ; H7 qua tin HIGH; nhả giữ chỗ hết hạn | 5-C07, LED-05 |

### 12.1 Lỗi tìm được khi đọc mã (sửa ở 6a)

`RiskLedger.reserved_total()` và `open_since()` cộng giữ chỗ của **mọi tài khoản** (sổ không có `account_id`) → nhiều người dùng (DEC-12) tiêu chung một trần heat / số lệnh ngày của nhau. Hướng sai là hướng chặn (an toàn) nhưng sai số. Từ 6a mọi giữ chỗ gắn tài khoản; khóa cũng theo tài khoản.

### 12.2 Bảng (migration 0026, chỉ thêm — trigger `forbid_mutation` chặn UPDATE / DELETE)

**`risk_decisions`** — mỗi quyết định Risk (cả từ chối) + intent gốc:

| Cột | Ý nghĩa |
| --- | --- |
| `risk_decision_id` (khóa) | |
| `account_id`, `idempotency_key` | **duy nhất cặp** → cùng khóa chỉ có một quyết định |
| `intent_id`, `intent_hash` | sha256 nội dung intent (JSON chuẩn hóa) — cùng khóa mà khác nội dung → từ chối `IDEMPOTENCY_KEY_REUSED` (không lưu) |
| `outcome`, `decided_at`, `expires_at` | |
| `decision`, `intent` | JSON đầy đủ (để audit + trả lại y hệt khi gọi lại) |

**`paper_ledger_events`** — mọi thay đổi trạng thái paper của tài khoản là một sự kiện:

| Cột | Ý nghĩa |
| --- | --- |
| `seq` (khóa, tự tăng), `event_id` (duy nhất) | |
| `account_id`, `account_seq` | **duy nhất cặp** — số thứ tự trong tài khoản; hai người ghi cùng lúc lọt khóa vẫn bị DB chặn (lớp bảo vệ thứ hai) |
| `type` | `START`, `RESERVE`, `RELEASE`, `OPEN`, `MODIFY_SL`, `CLOSE`, `CASH_IN`, `CASH_OUT`, `PEAK`, `DRAWDOWN_RESET` |
| `ref_id` | mã giữ chỗ (`RESERVE`, `RELEASE`) hoặc mã vị thế (`OPEN`, `MODIFY_SL`, `CLOSE`) |
| `once_key` (duy nhất, có thể rỗng) | `END:<giữ chỗ>` cho `RELEASE` và `OPEN` (một giữ chỗ chỉ kết thúc **một lần**: hoặc nhả hoặc khớp); `CLOSE:<vị thế>` (đóng một lần); `START:<tài khoản>` |
| `amount` `NUMERIC(20,8)` | tiền giữ chỗ / PnL ròng / số nạp, rút / vốn đầu |
| `at` | lúc sự kiện có hiệu lực (đồng hồ hệ thống, UTC) |
| `actor`, `reason`, `links` | ai, vì sao, sự kiện gốc (sự kiện bù trừ trỏ về bản gốc) |
| `data` JSON | số chi tiết, lưu dạng **chuỗi** để giữ đúng `Decimal` (lot, giá vào, SL, TP, phí, swap, giá đóng…) |

Lệnh paper khớp ngay (lệnh thị trường) nên "lệnh" = quyết định + sự kiện `OPEN`; "deal" = `OPEN` / `CLOSE`; "vị thế" = suy ra từ sự kiện (mở = có `OPEN`, chưa có `CLOSE`; SL hiện tại = `MODIFY_SL` mới nhất). Không có bảng trạng thái sửa được.

### 12.3 Khóa + idempotency (5-C12, LED-05)

- `ledger.locked(tài khoản)`: Postgres = giao dịch + `pg_advisory_xact_lock(băm("ledger:" + tài khoản))`; SQLite / bộ nhớ = khóa luồng theo tài khoản. Mọi ghi làm đổi ngân sách (giữ chỗ, khớp, đóng, nhả, nạp / rút) đều đi qua khóa này; pha B của Risk (đọc sổ → tính → giữ chỗ) nằm trọn trong một giao dịch, commit cùng lúc **quyết định + `RESERVE`** (không có trạng thái "đã giữ chỗ mà chưa có quyết định" hay ngược lại).
- Risk khi nhận intent: đọc quyết định đã lưu theo `(tài khoản, idempotency_key)` → có thì **trả lại đúng quyết định đó** (không tính lại, không giữ chỗ lần hai); khác nội dung → `IDEMPOTENCY_KEY_REUSED`. Kiểm lại một lần nữa **dưới khóa** ngay trước khi giữ chỗ (hai luồng cùng khóa → luồng sau thấy quyết định của luồng trước). Từ chối ở pha A lưu ngoài khóa; trùng khóa ở DB → trả bản đã lưu. Đọc sổ lỗi → `GATE_READ_ERROR:ledger` (không lưu).
- Crash giữa chừng: trước commit → không có gì (giao dịch hủy); sau commit trước khi trả → gọi lại cùng khóa nhận lại quyết định + giữ chỗ cũ, rồi khớp bình thường (khớp idempotent nhờ `END:<giữ chỗ>`). Quyết định quá hạn (`expires_at`, 30 giây) → không khớp được; `tick` nhả giữ chỗ bằng sự kiện bù trừ `RELEASE` (`RESERVATION_EXPIRED`, trỏ về `RESERVE`).
- Giữ chỗ hết hạn mà chưa được nhả **vẫn tính** vào heat / số lệnh ngày (chặn nhiều hơn = an toàn) cho tới khi có `RELEASE`.

### 12.4 Khớp paper + đóng lệnh (6b, LED-04) — giá trị khởi đầu chưa hiệu chỉnh

- Khớp: quyết định APPROVED / REDUCED còn hạn, giữ chỗ còn mở, giây giá mới nhất ≤ 10 giây, không `CALENDAR_CLOSED`. Giá vào BUY = **ask + đệm trượt giá**, SELL = **bid − đệm** (đệm = số Risk đã dùng, `details.slippage`). SL / TP = của intent.
- **Kiểm lại rủi ro thật lúc khớp:** `(|giá vào − SL|) × cỡ HĐ × lot + (phí + swap một đêm) × lot` phải ≤ số tiền đã giữ chỗ; lớn hơn (giá chạy từ lúc Risk tính) → không khớp (`PRICE_MOVED`), nhả giữ chỗ. Không bao giờ khớp với rủi ro lớn hơn mức đã duyệt.
- Đóng (chỉ giây giá có `available_at ≤ now`): BUY chạm SL khi `bid_low ≤ SL` → giá đóng = `min(SL, bid)` (khoảng trống giá → xấu hơn SL); chạm TP khi `bid ≥ TP` → đóng đúng TP (không tính trượt giá có lợi). SELL đối xứng với `ask_high` / `ask`. Cùng một giây chạm cả hai → coi là **SL** (an toàn). Giây đến muộn vẫn được xét: mỗi lần quét lùi 60 giây, và **mỗi 5 phút quét lại từ lúc mở** (bắt giây đến muộn lâu, vd. Gateway gửi bù sau mất kết nối — chậm phát hiện tối đa 5 phút). Giây có cờ `CALENDAR_CLOSED` bỏ qua. Kho giây giá trả `[từ, tới)` → đoạn cuối mở thêm 1 µs để không bỏ giây đúng bằng `now` (lỗi tìm được khi viết test).
- PnL ròng = chiều × (giá đóng − giá vào) × cỡ HĐ × lot − phí × lot − swap; swap = số mốc ngày (của hồ sơ, theo DST) **thứ Hai–thứ Sáu** đã qua (mốc thứ Bảy / Chủ nhật không có phiên → không swap; ×3 mốc `swap_rollover3days`) × chi phí swap / lot theo thông số lúc mở; swap dương → 0 (không tính là lời). Thông số dùng = thông số lúc khớp (lưu trong `OPEN`).
- Mất giá (không có giây giá mới) → không đóng được, `tick` báo `FEED_STALE` (không bịa giá).

### 12.5 Equity paper + H6 + H10 (6c)

- Sổ cái phải được **bắt đầu** bằng sự kiện `START` (vốn đầu paper = equity MT5 lúc bắt đầu, ai bắt đầu, lý do). Chưa bắt đầu → Risk từ chối `PAPER_LEDGER_NOT_STARTED` (mặc định an toàn; nút bắt đầu ở trang Rủi ro — bước 8).
- Equity paper = vốn đầu + nạp − rút + Σ PnL ròng đã đóng + PnL đang chạy. **Equity Risk dùng để tính lot và hạn mức = min(equity MT5 trong nhịp tim, equity paper)** — không bao giờ lớn hơn tiền thật trên tài khoản, cũng không lớn hơn tiền paper (paper lỗ thì lot nhỏ lại).
- Đỉnh: phát lại sự kiện theo thứ tự — `START` đặt đỉnh = vốn; sau mỗi `CLOSE` đỉnh = max(đỉnh, equity đã chốt); `PEAK` (do `tick` ghi khi equity gồm lãi đang chạy vượt đỉnh đã lưu) nâng đỉnh; **nạp `d` → đỉnh + d; rút `w` → đỉnh × (1 − w / equity trước rút)** (H10); `DRAWDOWN_RESET` (người xác nhận rõ, có lý do) → đỉnh = equity lúc đó.
- H6: sụt = (đỉnh − equity paper hiện tại) / đỉnh ≥ `max_drawdown_halt` → từ chối `DRAWDOWN_HALT` + đề nghị Safety PAUSED. Người mở lại Safety mà **không** ghi `DRAWDOWN_RESET` → lệnh sau lại bị chặn + PAUSED lần nữa ("mở lại cần xác nhận rõ, không chỉ bấm resume").
- H10: lỗ ngày / tuần / tháng + chuỗi thua chỉ tính PnL giao dịch (nạp / rút không vào). Nạp không đổi Safety (không tự mở lại khi đang dừng). Rút lớn hơn equity paper → từ chối ghi.

### 12.6 Quản lý lệnh đang mở (6d) — `PaperMonitor.tick(tài khoản, now)`

Theo thứ tự, mỗi bước đóng = sự kiện `CLOSE` có lý do:

1. SL / TP (12.4).
2. **H8:** thị trường chuyển `WEEKEND` / `HOLIDAY` trong `weekend_close_before_min` phút tới (cùng phép kiểm 5c) → đóng **mọi** lệnh (`WEEKEND_CLOSE`) ở giá đóng hiện tại (bid − đệm cho BUY, ask + đệm cho SELL). Lịch không phủ → đóng hết (an toàn).
3. **H7:** có lệnh cấm tin HIGH đang hiệu lực cho nguồn giá (`CALENDAR_HIGH`, `RELEASE_HIGH_RECEIVED`, hoặc loại `NEWS`) → `CLOSE_ALL`: đóng hết; `KEEP_SAFE_ONLY`: chỉ giữ lệnh **đã an toàn** (SL hiện tại đã qua hòa vốn sau chi phí: rủi ro còn lại = 0), đóng phần còn lại (`NEWS_CLOSE`).
4. Nhả giữ chỗ hết hạn (12.3).
5. Ghi `PEAK` nếu equity paper gồm lãi đang chạy vượt đỉnh đã lưu (6c).

Đóng ở bước 2–3 cần giá: giây giá mới nhất ≤ 10 giây; không có → `FEED_STALE` (không bịa giá; lệnh vẫn mở, báo lên). Hồ sơ không có → dùng chính sách an toàn nhất (`CLOSE_ALL` qua tin; đóng trước 30 phút cuối tuần). `tick` chưa chạy theo nhịp nào (nối ở bước 7 cùng Strategy).
